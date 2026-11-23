import pytest

from ora_agent.population_repair import (
    FEASIBLE,
    INFEASIBLE,
    UNKNOWN,
    BusinessResult,
    Candidate,
    Evaluation,
    Mutation,
    PopulationRepairController,
)


def make_seed(objective=10, status=FEASIBLE, sense="min", **kwargs):
    business = BusinessResult(status=status, objective=objective, sense=sense, **kwargs)
    return Candidate.seed(
        "seed-payload",
        Evaluation({"status": "ok"}, business, cost=0,
                   checkpoint="seed-checkpoint", structure="seed-structure"))


def named_operator(name, transform):
    def operator(parent):
        return Mutation(name, transform(parent))
    return operator


def suffix_operators():
    return [
        named_operator(name, lambda parent, name=name:
                       f"{parent.payload}|{name}|{parent.id}")
        for name in ("local_patch", "requirement_mutation", "declarative_repair")
    ]


def equal_evaluation(mutation, parent):
    return Evaluation(
        {"status": "ok", "payload": mutation.payload},
        BusinessResult(FEASIBLE, objective=10, sense="min"),
        cost=1, checkpoint={"payload": mutation.payload}, structure=mutation.operation)


def test_population_and_single_chain_share_the_same_six_child_evaluation_budget():
    initial = make_seed()
    comparison = PopulationRepairController(k=3, depth=2, evaluation_budget=6).compare(
        initial, equal_evaluation, suffix_operators())

    assert comparison.population.initial is initial
    assert comparison.single_chain.initial is initial
    assert comparison.population.evaluations == 6
    assert comparison.single_chain.evaluations == 6
    assert comparison.population.generation_evaluations == (3, 3)
    assert comparison.single_chain.generation_evaluations == (1, 1, 1, 1, 1, 1)
    assert comparison.population.total_cost == 6
    assert comparison.single_chain.total_cost == 6
    assert len(comparison.population.candidates) == 7
    assert len(comparison.single_chain.candidates) == 7


def test_duplicate_hashes_are_suppressed_before_consuming_evaluation_budget():
    operators = [named_operator(name, lambda parent: "constant")
                 for name in ("local_patch", "requirement_mutation", "declarative_repair")]
    result = PopulationRepairController().run(make_seed(), equal_evaluation, operators)

    assert result.evaluations == 1
    assert result.total_cost == 1
    assert result.stop_reason == "no_new_evaluations"
    assert result.generation_evaluations == (1, 0)
    assert len(result.rejections) == 5
    assert all(rejection.reasons == ("duplicate_hash",) for rejection in result.rejections)
    assert all(rejection.candidate is None for rejection in result.rejections)


def test_unknown_candidate_is_evaluated_but_never_accepted():
    def unknown_evaluation(mutation, parent):
        return Evaluation(
            {"status": "timeout"}, BusinessResult(UNKNOWN), cost=2,
            checkpoint="unknown-checkpoint")

    result = PopulationRepairController(k=1, depth=1, evaluation_budget=1).run(
        make_seed(), unknown_evaluation,
        [named_operator("local_patch", lambda parent: "unknown")])

    assert result.evaluations == 1
    assert result.total_cost == 2
    assert result.accepted == (result.initial,)
    assert result.best is result.initial
    assert result.checkpoint == "seed-checkpoint"
    assert result.rejections[0].reasons == ("unknown",)
    assert result.rejections[0].candidate.business_result.status == UNKNOWN


def test_best_feasible_checkpoint_survives_a_later_worse_candidate():
    initial = make_seed(objective=None, status=INFEASIBLE, violation_count=2)

    def evaluator(mutation, parent):
        objective = 10 if mutation.payload == "feasible" else 20
        return Evaluation(
            {"status": "ok"}, BusinessResult(FEASIBLE, objective=objective),
            cost=1, checkpoint=f"checkpoint-{objective}")

    operators = [named_operator("local_patch", lambda parent: "feasible"),
                 named_operator("declarative_repair", lambda parent: "worse")]
    result = PopulationRepairController(k=1, depth=2, evaluation_budget=2).run(
        initial, evaluator, operators)

    assert result.best.business_result.status == FEASIBLE
    assert result.best.business_result.objective == 10
    assert result.checkpoint == "checkpoint-10"
    assert result.improved_over_initial is True
    assert result.rejections[-1].reasons == ("worse_business",)


@pytest.mark.parametrize(("sense", "expected"), [("min", 5), ("max", 7)])
def test_objective_sense_controls_quality_and_lost_win_direction(sense, expected):
    def evaluator(mutation, parent):
        return Evaluation(
            {"status": "ok"}, BusinessResult(FEASIBLE, mutation.payload, sense=sense),
            cost=1, checkpoint=mutation.payload)

    operators = [named_operator("local_patch", lambda parent: 5),
                 named_operator("empty_spec_regeneration", lambda parent: 7)]
    result = PopulationRepairController(k=1, depth=2, evaluation_budget=2).run(
        make_seed(objective=6, sense=sense), evaluator, operators)

    assert result.best.business_result.objective == expected
    assert result.best.business_result.sense == sense
    assert result.evaluations == 2
    assert len(result.rejections) == 1
    assert "worse_business" in result.rejections[0].reasons


def test_population_branches_have_parent_ids_and_reconstructable_lineage():
    result = PopulationRepairController().run(
        make_seed(), equal_evaluation, suffix_operators())
    first_generation = [candidate for candidate in result.candidates
                        if candidate.generation == 1]
    second_generation = [candidate for candidate in result.candidates
                         if candidate.generation == 2]

    assert len(first_generation) == len(second_generation) == 3
    assert {candidate.parent_id for candidate in first_generation} == {result.initial.id}
    assert {candidate.operation for candidate in first_generation} == {
        "local_patch", "requirement_mutation", "declarative_repair"}
    first_generation_ids = {candidate.id for candidate in first_generation}
    assert {candidate.parent_id for candidate in second_generation} <= first_generation_ids
    for candidate in second_generation:
        lineage = result.lineage(candidate)
        assert len(lineage) == 3
        assert lineage[0] is result.initial
        assert lineage[-1] is candidate
        assert [item.generation for item in lineage] == [0, 1, 2]
        assert lineage[1].id == candidate.parent_id
        assert candidate.payload_hash
        assert candidate.execution_result["status"] == "ok"
        assert candidate.cost == 1
        assert candidate.checkpoint == {"payload": candidate.payload}


def test_structural_diversity_cannot_promote_a_worse_business_candidate():
    outcomes = {
        "good": (5, "structure-a"),
        "worse-but-diverse": (7, "structure-b"),
        "equal": (5, "structure-c"),
    }

    def evaluator(mutation, parent):
        objective, structure = outcomes[mutation.payload]
        return Evaluation(
            {"status": "ok"}, BusinessResult(FEASIBLE, objective), cost=1,
            checkpoint=mutation.payload, structure=structure)

    operators = [named_operator(name, lambda parent, payload=payload: payload)
                 for name, payload in zip(
                     ("local_patch", "requirement_mutation", "declarative_repair"),
                     outcomes)]
    result = PopulationRepairController(k=3, depth=1, evaluation_budget=3).run(
        make_seed(), evaluator, operators)

    assert [candidate.business_result.objective for candidate in result.population] == [5, 5]
    assert {candidate.structure for candidate in result.population} == {
        "structure-a", "structure-c"}
    rejected = next(rejection for rejection in result.rejections
                    if rejection.candidate is not None
                    and rejection.candidate.payload == "worse-but-diverse")
    assert rejected.reasons == ("worse_business",)


def test_new_hard_error_is_rejected_even_when_business_result_improves():
    initial = make_seed(objective=None, status=INFEASIBLE,
                        violation_count=1, hard_errors={"existing"})

    def evaluator(mutation, parent):
        return Evaluation(
            {"status": "crash"},
            BusinessResult(FEASIBLE, objective=1,
                           hard_errors={"existing", "new-runtime-error"}),
            cost=1, checkpoint="unsafe")

    result = PopulationRepairController(k=1, depth=1, evaluation_budget=1).run(
        initial, evaluator, [named_operator("local_patch", lambda parent: "unsafe")])

    assert result.best is initial
    assert result.rejections[0].reasons == ("new_hard_error",)


def test_losing_an_initial_feasible_win_is_rejected():
    def evaluator(mutation, parent):
        return Evaluation(
            {"status": "ok"},
            BusinessResult(INFEASIBLE, objective=None, violation_count=1),
            cost=1, checkpoint="lost-win")

    result = PopulationRepairController(k=1, depth=1, evaluation_budget=1).run(
        make_seed(objective=1), evaluator,
        [named_operator("requirement_mutation", lambda parent: "lost-win")])

    assert result.best is result.initial
    assert result.checkpoint == "seed-checkpoint"
    assert result.rejections[0].reasons == ("lost_win", "worse_business")


def test_population_worse_than_single_chain_is_reported_as_a_negative_result():
    initial = Candidate.seed(
        20, Evaluation({"status": "ok"}, BusinessResult(FEASIBLE, objective=20),
                       cost=0, checkpoint=20))
    operators = [
        named_operator(name, lambda parent, step=step:
                       parent.business_result.objective - step)
        for name, step in (("local_patch", 1), ("requirement_mutation", 2),
                           ("declarative_repair", 3))
    ]

    def evaluator(mutation, parent):
        return Evaluation(
            {"status": "ok"}, BusinessResult(FEASIBLE, objective=mutation.payload),
            cost=1, checkpoint=mutation.payload)

    comparison = PopulationRepairController().compare(initial, evaluator, operators)

    assert comparison.population.evaluations == comparison.single_chain.evaluations == 6
    assert comparison.population.best.business_result.objective == 14
    assert comparison.single_chain.best.business_result.objective == 8
    assert comparison.population_better is False
    assert comparison.negative_result is True
    assert comparison.winner == "single_chain"
    assert comparison.population_advantage == -6


def test_duplicate_mutation_costs_are_charged_without_adding_evaluation_cost():
    operators = [
        lambda parent: Mutation("local_patch", "constant", cost=2),
        lambda parent: Mutation("requirement_mutation", "constant", cost=3),
        lambda parent: Mutation("declarative_repair", "constant", cost=5),
    ]
    result = PopulationRepairController(k=3, depth=1, evaluation_budget=3).run(
        make_seed(), equal_evaluation, operators)

    assert result.evaluations == 1
    assert result.proposal_cost == 10
    assert result.evaluation_cost == 1
    assert result.total_cost == 11
    evaluated = result.accepted[-1]
    assert evaluated.proposal_cost == 2
    assert evaluated.evaluation_cost == 1
    assert evaluated.cost == 3
    assert [rejection.proposal_cost for rejection in result.rejections] == [3, 5]
    assert [rejection.evaluation_cost for rejection in result.rejections] == [0, 0]
    assert all(rejection.reasons == ("duplicate_hash",)
               for rejection in result.rejections)


def test_exploration_regression_can_parent_recovery_but_never_enters_final_elite():
    operators = [
        lambda parent: Mutation("local_patch", 12, cost=1),
        lambda parent: Mutation("empty_spec_regeneration", 9, cost=2),
    ]

    def evaluator(mutation, parent):
        cost = 10 if mutation.payload == 12 else 20
        return Evaluation(
            {"status": "ok"}, BusinessResult(FEASIBLE, objective=mutation.payload),
            cost=cost, checkpoint=mutation.payload)

    result = PopulationRepairController(k=1, depth=2, evaluation_budget=2).run(
        make_seed(), evaluator, operators, allow_exploration=True)

    regression = result.exploration[0]
    recovery = result.best
    assert regression.business_result.objective == 12
    assert regression.role == "exploration"
    assert recovery.business_result.objective == 9
    assert recovery.role == "elite"
    assert recovery.parent_id == regression.id
    assert [candidate.business_result.objective for candidate in result.elites] == [10, 9]
    assert result.elite_population == (recovery,)
    assert result.checkpoint == 9
    assert [candidate.role for candidate in result.lineage(recovery)] == [
        "elite", "exploration", "elite"]
    assert result.proposal_cost == 3
    assert result.evaluation_cost == 30
    assert result.total_cost == 33
    assert (regression.proposal_cost, regression.evaluation_cost, regression.cost) == (1, 10, 11)
    assert (recovery.proposal_cost, recovery.evaluation_cost, recovery.cost) == (2, 20, 22)


def test_unrecovered_exploration_is_available_for_parenting_but_not_delivery():
    result = PopulationRepairController(k=1, depth=1, evaluation_budget=1).run(
        make_seed(),
        lambda mutation, parent: Evaluation(
            {"status": "ok"}, BusinessResult(FEASIBLE, objective=12),
            cost=1, checkpoint="regression-checkpoint"),
        [lambda parent: Mutation("local_patch", 12, cost=1)],
        allow_exploration=True)

    regression = result.exploration[0]
    assert result.population == (regression,)
    assert result.accepted == (result.initial, regression)
    assert result.elites == (result.initial,)
    assert result.elite_population == (result.initial,)
    assert result.best is result.initial
    assert result.checkpoint == "seed-checkpoint"
    assert result.improved_over_initial is False


@pytest.mark.parametrize("case", ["unknown", "lost_feasibility", "new_hard_error"])
def test_unsafe_candidates_cannot_enter_exploration(case):
    initial = make_seed(hard_errors={"existing"})

    def evaluator(mutation, parent):
        if case == "unknown":
            business = BusinessResult(UNKNOWN)
        elif case == "lost_feasibility":
            business = BusinessResult(INFEASIBLE, violation_count=1)
        else:
            business = BusinessResult(
                FEASIBLE, objective=1, hard_errors={"existing", "new-error"})
        return Evaluation({"status": "checked"}, business, cost=1, checkpoint="unsafe")

    result = PopulationRepairController(k=1, depth=1, evaluation_budget=1).run(
        initial, evaluator, [lambda parent: Mutation("local_patch", case)],
        allow_exploration=True)

    assert result.exploration == ()
    assert result.elites == (initial,)
    assert result.best is initial
    assert result.rejections[0].candidate.role == "rejected"
    expected_reason = {"unknown": "unknown", "lost_feasibility": "lost_win",
                       "new_hard_error": "new_hard_error"}[case]
    assert expected_reason in result.rejections[0].reasons
