"""Select candidate references only on authorized experiment splits."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def select_reference(split, problem_id, base=None):
    if split not in {"dev", "validation", "frozen"}:
        raise ValueError("reference selection is restricted to dev/validation/frozen")
    allowed = set((ROOT / f"data/dvsa/bwor/{split}.txt").read_text().splitlines())
    if problem_id not in allowed:
        raise ValueError(f"unauthorized problem ID: {problem_id}")
    base = base or ROOT / f"work/dvsa/bwor_reference/{split}"
    target = base / problem_id
    variants = []
    if split == "dev":
        variants.append(("structural_r1", "model_r1.json", "solution_r1.json", "result_r1.json"))
    variants.extend([("syntax_r1", "model_syntax_r1.json", "solution_syntax_r1.json", "result_syntax_r1.json"),
                     ("initial", "model.json", "solution.json", "result.json")])
    failures = []
    for revision, model_name, solution_name, result_name in variants:
        if not (target / result_name).exists():
            continue
        result = json.loads((target / result_name).read_text())
        solve = result.get("solve", result)
        error = result.get("objective_absolute_error")
        if (solve.get("status") == "optimal" and solve.get("audit", {}).get("verdict") == "VALID"
                and error is not None and error <= 0.1):
            return {"problem_id": problem_id, "split": split, "revision": revision,
                    "model": json.loads((target / model_name).read_text()),
                    "solution": json.loads((target / solution_name).read_text()),
                    "result": result, "model_path": target / model_name,
                    "solution_path": target / solution_name,
                    "question_path": target / "question.txt",
                    "question": (target / "question.txt").read_text()}
        failures.append({"revision": revision, "status": result.get("status"),
                         "objective_absolute_error": error})
    raise ValueError(f"no candidate reference for {problem_id}: {failures}")
