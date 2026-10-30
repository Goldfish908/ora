"""m2gen core: render structure templates into problem instances and
validate them by executing witnesses.

Independence rule (m2_design §2): the solve.py compiler path fills
connection slots from spec.json; the witness path is a separately written
numeric rule checker that never sees the slots. The two share nothing but
params.json and the solution.json contract.
"""

import json
import os
import random
import re
import shutil
import string
import subprocess
import sys
from pathlib import Path

from .instantiate import SAMPLERS

HERE = Path(__file__).resolve().parent
SPEC = json.loads((HERE / "spec.json").read_text())
RL_PY = "/home/hewj13/planbb/miniforge3/envs/rl/bin/python"
MAX_DRAWS = 60


def mip_python() -> str:
    env = os.environ.get("ORA_MIP_PYTHON")
    if env:
        return env
    return RL_PY if os.path.exists(RL_PY) else sys.executable


def _render(tmpl_dir: Path, name: str, mapping: dict) -> str:
    return string.Template((tmpl_dir / name).read_text()).substitute(mapping)


def _slot_mapping(struct: dict, problem_id: str, artifact_id: str,
                  overrides: dict) -> dict:
    m = {"PROBLEM_ID": problem_id, "ARTIFACT_ID": artifact_id}
    for conn in struct["connections"]:
        m[conn["slot"]] = overrides.get(conn["id"], conn["correct"])
    return m


def artifacts_of(struct: dict) -> list:
    """[(artifact_id, {connection_id: fragment}), mutant_meta]"""
    out = [("correct", {}, None)]
    for conn in struct["connections"]:
        for mut in conn["mutants"]:
            out.append((mut["id"], {conn["id"]: mut["fragment"]},
                        {"connection": conn["id"], **mut}))
    return out


def emit_instance(struct_id: str, params: dict, out_dir: Path,
                  problem_id: str) -> Path:
    """Write one full five-piece instance (problem/data/correct/mutants/
    witness/labels) plus flip variants for connections with flip_text."""
    struct = SPEC["structures"][struct_id]
    tmpl = HERE / "templates" / struct_id
    inst = out_dir / problem_id
    if inst.exists():
        shutil.rmtree(inst)
    (inst / "data").mkdir(parents=True)
    (inst / "data" / "params.json").write_text(
        json.dumps(params, indent=2, ensure_ascii=False))

    phrase_map = {f"PHRASE_{c['id'].upper()}": c.get("flip_text", {})
                  .get("correct", "") for c in struct["connections"]}
    (inst / "problem.md").write_text(_render(
        tmpl, "problem.md.tmpl",
        {"PROBLEM_ID": problem_id, **phrase_map}))

    witness_src = (tmpl / "witness.py.tmpl").read_text()
    for aid, overrides, _ in artifacts_of(struct):
        art = inst / ("correct" if aid == "correct" else f"mutants/{aid}")
        art.mkdir(parents=True)
        (art / "solve.py").write_text(_render(
            tmpl, "solve.py.tmpl",
            _slot_mapping(struct, problem_id, aid, overrides)))
        wdir = inst / "witness"
        wdir.mkdir(exist_ok=True)
        (wdir / f"{aid}.py").write_text(
            string.Template(witness_src).substitute({"PROBLEM_ID": problem_id}))

    for conn in struct["connections"]:
        flip = conn.get("flip_text")
        if not flip:
            continue
        flip_dir = inst / f"flip_{conn['id']}"
        (flip_dir / "correct").mkdir(parents=True)
        flipped_phrases = {**phrase_map,
                           f"PHRASE_{conn['id'].upper()}": flip["flipped"]}
        (flip_dir / "problem.md").write_text(_render(
            tmpl, "problem.md.tmpl",
            {"PROBLEM_ID": problem_id + "__flip_" + conn["id"],
             **flipped_phrases}))
        # the flipped text makes flip_ref (default: the single mutant
        # fragment) the correct reference implementation of flipped semantics
        flipped_ref = conn.get("flip_ref") or conn["mutants"][0]["fragment"]
        (flip_dir / "correct" / "solve.py").write_text(_render(
            tmpl, "solve.py.tmpl",
            _slot_mapping(struct, problem_id + "__flip_" + conn["id"],
                          "correct", {conn["id"]: flipped_ref})))
        (flip_dir / "data").mkdir(exist_ok=True)
        (flip_dir / "data" / "params.json").write_text(
            json.dumps(params, indent=2, ensure_ascii=False))
    return inst


def run_witness(inst: Path, aid: str, timeout: int = 180) -> dict:
    inst = inst.resolve()  # subprocess cwd makes relative script paths rot
    r = subprocess.run([mip_python(), str(inst / "witness" / f"{aid}.py")],
                       cwd=inst, capture_output=True, text=True,
                       timeout=timeout)
    out = (r.stdout or "").strip()
    m = re.search(r"objective=([-\d.eE]+)", out)
    objective = float(m.group(1)) if m else None
    if objective is None:  # FAIL path prints no objective; read the artifact's
        sol_path = (inst / ("correct" if aid == "correct"
                            else f"mutants/{aid}") / "solution.json")
        if sol_path.exists():
            objective = json.loads(sol_path.read_text()).get("objective")
    return {
        "returncode": r.returncode,
        "stdout": out[-400:],
        "passed": r.returncode == 0 and out.startswith("PASS"),
        "crash": out.startswith("FAIL:crash"),
        "rules": ([] if r.returncode == 0
                  else re.findall(r"(W\d+)", out.split(":", 1)[-1])),
        "objective": objective,
    }


def _solve_objective(solve_py: Path, timeout: int = 180):
    """Run a solve.py directly; return its solution.json objective."""
    solve_py = solve_py.resolve()  # subprocess cwd rots relative paths
    r = subprocess.run([mip_python(), str(solve_py)], cwd=solve_py.parent,
                       capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        return None
    sol = solve_py.parent / "solution.json"
    return json.loads(sol.read_text())["objective"] if sol.exists() else None


def check_flip_discrimination(inst: Path, correct_obj) -> dict:
    """A flip pair only discriminates if the flipped-semantics reference
    reaches a DIFFERENT objective than the base reference (flow_dir's
    hub_conservation flip is the counterexample: slack is never useful
    under minimization, so == and >= optima coincide)."""
    out = {}
    for flip_dir in sorted(inst.glob("flip_*")):
        solve_py = flip_dir / "correct" / "solve.py"
        if not solve_py.exists():
            continue
        flip_obj = _solve_objective(solve_py)
        out[flip_dir.name] = {
            "flip_objective": flip_obj,
            "discriminating": (flip_obj is not None and correct_obj is not None
                               and abs(flip_obj - correct_obj) > 1e-6),
        }
    return out


def validate_instance(inst: Path, struct_id: str) -> tuple:
    """Run every artifact's witness. Acceptance: correct PASSes; every
    mutant FAILs, is not a crash, and its expected rules all fire.
    Returns (ok, report)."""
    struct = SPEC["structures"][struct_id]
    report = {}
    ok = True
    for aid, _, meta in artifacts_of(struct):
        res = run_witness(inst, aid)
        entry = {"verdict": "PASS" if res["passed"] else "FAIL",
                 "objective": res["objective"], "rules": res["rules"],
                 "crash": res["crash"]}
        if aid == "correct":
            if not res["passed"]:
                ok = False
                entry["violation"] = "correct artifact failed witness"
        else:
            missing = [r for r in meta["expect_rules"]
                       if r not in res["rules"]]
            if res["passed"] or res["crash"] or missing:
                ok = False
                entry["violation"] = (
                    "mutant passed witness" if res["passed"]
                    else "mutant crashed" if res["crash"]
                    else f"expected rules not fired: {missing}")
        report[aid] = entry
    if "correct" in report:
        report["_flips"] = check_flip_discrimination(
            inst, report["correct"]["objective"])
    return ok, report


def write_labels(inst: Path, struct_id: str, params: dict, report: dict,
                 seed: int) -> None:
    struct = SPEC["structures"][struct_id]
    artifacts = {}
    for aid, _, meta in artifacts_of(struct):
        ent = report[aid]
        artifacts[aid] = {
            "path": "correct/solve.py" if aid == "correct"
                    else f"mutants/{aid}/solve.py",
            "kind": "correct" if aid == "correct" else "mutant",
            "mutation_type": None if aid == "correct"
                             else f"connection_{meta['connection']}",
            "expected_witness": "PASS" if aid == "correct" else "FAIL",
            "expected_objective": ent["objective"],
            "description": "Correct reference implementation."
            if aid == "correct" else meta["description"],
        }
    labels = {
        "problem": inst.name,
        "family": SPEC["family"],
        "structure": struct_id,
        "seed": seed,
        "reference_objective": report["correct"]["objective"],
        "tolerance": 1e-6,
        "witness_semantics": struct["witness_semantics"],
        "connection_classes": {c["class"]: c["id"]
                               for c in struct["connections"]},
        "flips": report.get("_flips", {}),
        "artifacts": artifacts,
    }
    (inst / "labels.json").write_text(
        json.dumps(labels, indent=2, ensure_ascii=False))


def generate(struct_id: str, n: int, seed: int, out_dir: Path,
             fixed_params: dict | None = None) -> list:
    """Generate n validated instances; resamples (deterministically) until
    each drawn instance passes validate_instance. Returns instance dirs."""
    struct = SPEC["structures"][struct_id]
    sampler = SAMPLERS[struct["sampler"]]
    out_dir.mkdir(parents=True, exist_ok=True)
    made, draw = [], 0
    while len(made) < n and draw < MAX_DRAWS:
        rng = random.Random(seed * 100003 + draw * 101 + 7)
        params = fixed_params or sampler(rng)
        pid = f"{struct_id}__s{seed}i{len(made)}"
        inst = emit_instance(struct_id, params, out_dir, pid)
        ok, report = validate_instance(inst, struct_id)
        if ok or fixed_params is not None:
            write_labels(inst, struct_id, params, report, seed)
            made.append((inst, ok, report))
        else:
            shutil.rmtree(inst)
        draw += 1
    return made
