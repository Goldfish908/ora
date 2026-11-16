from ora_agent.structured_models import (
    code_prompt,
    evaluation_prompt,
    model_prompt,
    select_max_min,
    validate_evaluation,
    validate_model,
)

QUESTION = "Produce at most 10 chairs. Each chair yields 5 profit."
MODEL = {
    "parameters": [{"name": "limit", "value": 10, "source": "at most 10 chairs"}],
    "variables": [{"name": "chairs", "symbol": "x", "type": "integer", "bounds": [0, 10], "source": "chairs"}],
    "objective": {"direction": "maximize", "expression": "5*x", "variables": ["x"],
                  "source": "Each chair yields 5 profit"},
    "constraints": [{"name": "capacity", "expression": "x <= 10", "type": "<=",
                     "source": "at most 10 chairs"}],
}


def evaluation(values):
    return {"scores": dict(zip(("parameters", "variables", "constraints", "objective"), values)),
            "weak_points": ["constraints may be incomplete"]}


def test_structured_model_requires_verbatim_business_evidence():
    assert validate_model(MODEL, QUESTION) == []
    invalid = {**MODEL, "constraints": [{"name": "capacity", "expression": "x <= 10", "type": "<=",
                                         "source": "not present in question"}]}
    assert any("source" in error for error in validate_model(invalid, QUESTION))


def test_source_matching_normalizes_markdown_whitespace_only():
    model = {"parameters": [{"name": "cost", "value": 9, "source": "I | 9 | 4"}],
             "variables": [{"name": "x", "symbol": "x", "type": "binary", "bounds": [0, 1],
                            "source": "worker I"}],
             "objective": {"direction": "minimize", "expression": "9*x", "variables": ["x"],
                           "source": "total working hours"},
             "constraints": []}
    question = "| I      | 9   | 4 |\nworker I must finish. Compute total working hours."
    assert validate_model(model, question) == []
    model["parameters"][0]["source"] = "II | 9 | 4"
    assert validate_model(model, question)


def test_later_candidate_receives_previous_weaknesses_and_max_min_selection():
    first = {"candidate_id": "A", "model": MODEL, "schema_errors": [],
             "evaluation": validate_evaluation(evaluation((90, 90, 40, 90)))}
    second = {"candidate_id": "B", "model": MODEL, "schema_errors": [],
              "evaluation": validate_evaluation(evaluation((80, 85, 85, 85)))}
    history = [{"model": first["model"], "evaluation": first["evaluation"]}]
    prompt = model_prompt(QUESTION, history)
    assert "low-confidence dimensions" in prompt
    assert "weak_points" in prompt
    assert "constraints may be incomplete" in prompt
    selected, minima, method = select_max_min([first, second])
    assert selected == 1
    assert minima == {"A": 40.0, "B": 80.0}
    assert method == "max_min_confidence"
    assert "reference objective" in evaluation_prompt(QUESTION, MODEL)
    assert "en_answer" not in code_prompt(QUESTION, MODEL)


def test_empty_confidence_falls_back_to_first_without_crashing():
    candidates = [{"candidate_id": "A", "model": MODEL, "schema_errors": [],
                   "evaluation": {"scores": {}, "weak_points": []}},
                  {"candidate_id": "B", "model": MODEL, "schema_errors": [],
                   "evaluation": validate_evaluation(evaluation((80, 80, 80, 80)))}]
    selected, minima, method = select_max_min(candidates)
    assert selected == 1
    assert minima == {"B": 80.0}
    assert method == "max_min_confidence"
    empty = [{"candidate_id": "A", "model": MODEL, "schema_errors": [],
              "evaluation": {"scores": {}, "weak_points": []}}]
    assert select_max_min(empty) == (0, {}, "no_valid_candidate_fallback_first")
