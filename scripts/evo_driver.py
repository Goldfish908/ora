#!/usr/bin/env python3
"""Self-evolution driver v0.1 — see docs/paper/self_evolution_design_v0.1.md.

Genome = directory evo/genomes/<gid>/ with:
  code.txt   code/API conventions clauses (G-code slot)
  sem.txt    semantic conventions clauses (G-sem slot)
  meta.json  {"gid", "gen", "parents", "operator", "note"}

Fitness (dev40 slice): true-success rate where true success =
witness=="feasible" and grade=="match" (derived, same as the loop's).
Tiebreak: fewer phantoms (witness infeasible & grade better_than_reference),
then fewer total completion tokens.

Commands:
  init                       create gen-0 seed (P3 config) + 7 mutants
  eval --gen N               run m1_pilot.py on dev40 for every unfit genome
                             of gen N (parallel), then score into ledger
  next --gen N               select top-2 elites of gen N, spawn 6 offspring
                             as gen N+1 (2 LLM-drafted clause additions,
                             1 paraphrase, 2 crossovers, 1 deletion)
  champion --gen N           run gen-N champion on gapcheck60 (overfit check)
  status                     print the ledger

Physical isolation: fitness/mutation only ever touch dev40 (F1-F4);
F5-F8 scenario ids never enter this file's inputs.
"""
from __future__ import annotations

import argparse, json, os, re, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVO = ROOT / "evo"
GENOMES = EVO / "genomes"
LEDGER = EVO / "ledger.jsonl"
DEV40 = ROOT / "data/m1_retailopt/dev40_f1f4.jsonl"
GAP60 = ROOT / "data/m1_retailopt/gapcheck60_f1f4.jsonl"
V02 = ROOT / "configs/conventions_priors_v0.2.txt"
SEM01 = ROOT / "configs/semantic_priors_v0.1.txt"
PY = "/home/hewj13/planbb/miniforge3/envs/rl/bin/python"

CODE_HEADER = "[KNOWN PITFALLS"
SEM_HEADER = "[SEMANTIC CONVENTIONS"


def split_clauses(text: str) -> tuple[str, list[str]]:
    """Split a numbered clause file into (header, clauses)."""
    parts = re.split(r"\n(?=\d+\.\s)", text.strip())
    return parts[0], [p.strip() for p in parts[1:]]


def join_clauses(header: str, clauses: list[str]) -> str:
    out = [header.strip()]
    for i, c in enumerate(clauses, 1):
        body = re.sub(r"^\d+\.\s*", "", c)
        out.append(f"{i}. {body}")
    return "\n".join(out) + "\n"


def write_genome(gid: str, gen: int, code: str, sem: str,
                 parents: list[str], operator: str, note: str = "") -> str:
    d = GENOMES / gid
    d.mkdir(parents=True, exist_ok=True)
    (d / "code.txt").write_text(code)
    (d / "sem.txt").write_text(sem)
    (d / "meta.json").write_text(json.dumps(
        {"gid": gid, "gen": gen, "parents": parents,
         "operator": operator, "note": note,
         "created_at": time.strftime("%Y-%m-%d %H:%M:%S")}, indent=1))
    return gid


def read_genome(gid: str) -> tuple[str, str]:
    d = GENOMES / gid
    return (d / "code.txt").read_text(), (d / "sem.txt").read_text()


def combined_file(gid: str) -> Path:
    code, sem = read_genome(gid)
    p = GENOMES / gid / "combined.txt"
    p.write_text(code.strip() + "\n\n\n" + sem.strip() + "\n")
    return p


# ---------------- gen-0 seeding (deterministic, zero LLM) ----------------

def cmd_init() -> None:
    code = V02.read_text()
    sem = SEM01.read_text()
    ch, clauses = split_clauses(sem)
    assert len(clauses) == 7, f"semantic clauses != 7: {len(clauses)}"

    write_genome("g0_seed", 0, code, sem, [], "seed", "P3 config verbatim")

    def drop(idx: int) -> str:
        return join_clauses(ch, [c for i, c in enumerate(clauses) if i != idx])

    write_genome("g0_no_subrule", 0, code, drop(2), ["g0_seed"],
                 "deletion", "drop semantic clause 3 (substitution)")
    write_genome("g0_no_dump", 0, code, drop(4), ["g0_seed"],
                 "deletion", "drop semantic clause 5 (dump completeness)")
    write_genome("g0_no_init", 0, code, drop(5), ["g0_seed"],
                 "deletion", "drop semantic clause 6 (initial inventory)")
    scaffold_at = code.find("[MODELING PROCEDURE")
    write_genome("g0_no_scaffold", 0,
                 code[:scaffold_at].strip() + "\n", sem, ["g0_seed"],
                 "deletion", "v0.2 without the modeling-procedure scaffold")
    reordered = join_clauses(ch, [clauses[1], clauses[2], clauses[0]]
                             + clauses[3:])
    write_genome("g0_sem_reorder", 0, code, reordered, ["g0_seed"],
                 "reorder", "demand-equality & substitution clauses first")
    emphasis = sem.strip() + ("\n\nReminder: clauses 2 and 3 above are the "
                              "top failure source; double-check them before "
                              "outputting code.\n")
    write_genome("g0_sem_emph", 0, code, emphasis, ["g0_seed"],
                 "emphasis", "append salience reminder for clauses 2-3")
    # order swap: semantic block precedes code block
    d = GENOMES / "g0_sem_first"
    d.mkdir(parents=True, exist_ok=True)
    (d / "code.txt").write_text(code)
    (d / "sem.txt").write_text(sem)
    (d / "combined.txt").write_text(sem.strip() + "\n\n\n"
                                    + code.strip() + "\n")
    (d / "meta.json").write_text(json.dumps(
        {"gid": "g0_sem_first", "gen": 0, "parents": ["g0_seed"],
         "operator": "reorder", "note": "semantic block before code block",
         "created_at": time.strftime("%Y-%m-%d %H:%M:%S")}, indent=1))
    print("gen-0: 8 genomes written under", GENOMES)


# ---------------- evaluation ----------------

def genomes_of_gen(gen: int) -> list[str]:
    out = []
    for d in sorted(GENOMES.iterdir()):
        m = json.loads((d / "meta.json").read_text())
        if m["gen"] == gen:
            out.append(m["gid"])
    return out


def run_pilot(gid: str, gen: int, scenarios: Path, tag: str) -> Path:
    out_dir = (ROOT / f"runs/evo/gen{gen}").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"m1_pilot_schema_sol_{tag}_{gid}.jsonl"
    if out.exists() and sum(1 for _ in out.open()) >= len(
            scenarios.read_text().splitlines()):
        return out  # already complete
    env = dict(os.environ)
    log = out_dir / f"pilot_{tag}_{gid}.log"
    with log.open("w") as lf:
        subprocess.run(
            [PY, str(ROOT / "scripts/m1_pilot.py"),
             "--modes", "on", "--prompt-mode", "schema_sol",
             "--scenarios-file", str(scenarios),
             "--conventions-file", str(combined_file(gid)),
             "--out-dir", str(out_dir), "--out-tag", f"_{tag}_{gid}"],
            cwd=ROOT, env=env, stdout=lf, stderr=subprocess.STDOUT)
    return out


def score_file(fp: Path) -> dict:
    return score_files([fp])


def score_files(fps: list[Path]) -> dict:
    n = succ = ph = toks = 0
    seen = set()
    for fp in fps:
        for line in fp.open():
            r = json.loads(line)
            if r.get("thinking") != "on":
                continue
            sid = r["scenario_id"]
            if sid in seen:
                continue
            seen.add(sid)
            n += 1
            ts = r.get("true_success")
            if ts is None:
                ts = (r.get("witness") == "feasible"
                      and r.get("grade") == "match")
            succ += bool(ts)
            ph += (r.get("witness") == "infeasible"
                   and r.get("grade") == "better_than_reference")
            toks += r.get("completion_tokens") or 0
    return {"n": n, "success": succ, "phantom": ph, "tokens": toks}


def ledger_add(rec: dict) -> None:
    LEDGER.parent.mkdir(exist_ok=True)
    with LEDGER.open("a") as f:
        f.write(json.dumps(rec) + "\n")


def ledger_fitness(gid: str, gen: int) -> dict | None:
    if not LEDGER.exists():
        return None
    for line in LEDGER.read_text().splitlines():
        r = json.loads(line)
        if r.get("gid") == gid and r.get("gen") == gen and r.get("kind") == "dev40":
            return r
    return None


def cmd_eval(gen: int, shards: int = 2) -> None:
    for var in ("ORA_LLM_BASE_URL", "ORA_LLM_API_KEY"):
        if not os.environ.get(var):
            sys.exit(f"missing env {var}: export ORA_LLM_BASE_URL="
                     "$QWEN27B_BASE_URL ORA_LLM_API_KEY=$QWEN27B_API_KEY "
                     "ORA_LLM_MODEL=Qwen3_8-27B ORA_LLM_INSECURE=1 first")
    gids = [g for g in genomes_of_gen(gen)
            if ledger_fitness(g, gen) is None]
    print(f"gen{gen}: {len(gids)} genomes to evaluate on dev40 "
          f"({shards} shards each)")
    out_dir = (ROOT / f"runs/evo/gen{gen}").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    # shard slices of dev40, written once per gen
    rows = [l for l in DEV40.read_text().splitlines() if l.strip()]
    part_files = []
    for pi in range(shards):
        pf = out_dir / f"dev40_part{pi}.jsonl"
        pf.write_text("".join(rows[pi::shards]))
        part_files.append(pf)
    procs = []
    for gid in gids:
        need = False
        for pi in range(shards):
            out = out_dir / f"m1_pilot_schema_sol_dev40_{gid}_p{pi}.jsonl"
            if not (out.exists() and len(out.read_text().splitlines())
                    >= len(rows[pi::shards])):
                need = True
        if not need:
            continue
        for pi in range(shards):
            log = (out_dir / f"pilot_dev40_{gid}_p{pi}.log").open("w")
            p = subprocess.Popen(
                [PY, str(ROOT / "scripts/m1_pilot.py"),
                 "--modes", "on", "--prompt-mode", "schema_sol",
                 "--scenarios-file", str(part_files[pi]),
                 "--conventions-file", str(combined_file(gid)),
                 "--out-dir", str(out_dir),
                 "--out-tag", f"_dev40_{gid}_p{pi}"],
                cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
            procs.append((gid, p))
        print("launched", gid)
    for gid, p in procs:
        p.wait()
    for gid in gids:
        outs = sorted(out_dir.glob(f"m1_pilot_schema_sol_dev40_{gid}_p*.jsonl"))
        if not outs:
            print("MISSING output for", gid); continue
        s = score_files(outs)
        ledger_add({"kind": "dev40", "gen": gen, "gid": gid, **s})
        print(f"scored {gid}: {s['success']}/{s['n']} ph={s['phantom']}")


# ---------------- selection & mutation ----------------

def llm_draft_clause(fail_summaries: list[str]) -> str:
    """One LLM call: draft ONE new convention clause from failure summaries."""
    import openai
    client = openai.OpenAI(
        base_url=os.environ["QWEN27B_BASE_URL"],
        api_key=os.environ["QWEN27B_API_KEY"], timeout=300)
    prompt = (
        "You are improving a prompt-injected conventions file for an LLM that "
        "writes PySCIPOpt code for retail inventory MILPs. Below are failure "
        "summaries from its latest run. Draft ONE new numbered convention "
        "clause (max 5 lines, imperative voice, no instance-specific numbers) "
        "that would prevent the most common failure class. Output ONLY the "
        "clause text.\n\nFAILURES:\n" + "\n".join(fail_summaries[:12]))
    r = client.chat.completions.create(
        model="Qwen3_8-27B",
        messages=[{"role": "user", "content": prompt}],
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        temperature=0.7)
    return r.choices[0].message.content.strip()


def strip_fences(text: str) -> str:
    """Remove markdown code-fence lines an LLM may wrap its output in."""
    lines = [l for l in text.strip().splitlines()
             if not l.strip().startswith("```")]
    return "\n".join(lines).strip()


def failure_summaries(gid: str, gen: int) -> list[str]:
    fps = sorted((ROOT / f"runs/evo/gen{gen}").glob(
        f"m1_pilot_schema_sol_dev40_{gid}*.jsonl"))
    out = []
    if not fps:
        return out
    for fp in fps:
        for line in fp.open():
            r = json.loads(line)
            ts = r.get("true_success")
            if ts is None:
                ts = (r.get("witness") == "feasible"
                      and r.get("grade") == "match")
            if ts:
                continue
            sid = r["scenario_id"]
            if re.search(r"_f[5-8]_", sid):
                raise RuntimeError(f"isolation breach: {sid}")
            det = (r.get("witness_details") or [""])[0][:120]
            err = (r.get("stderr_tail") or "").splitlines()[-1][:120] \
                if r.get("stderr_tail") else ""
            out.append(f"{sid}: witness={r.get('witness')} "
                       f"{','.join(r.get('witness_rules') or [])} {det} {err}")
    return out


def cmd_next(gen: int) -> None:
    cands = []
    for gid in genomes_of_gen(gen):
        f = ledger_fitness(gid, gen)
        if f:
            cands.append((f["success"], -f["phantom"], -f["tokens"], gid))
    cands.sort(reverse=True)
    assert len(cands) >= 2, "need at least 2 scored genomes"
    e1, e2 = cands[0][3], cands[1][3]
    print(f"gen{gen} elites: {e1} {cands[0][:3]}, {e2} {cands[1][:3]}")
    c1, s1 = read_genome(e1)
    c2, s2 = read_genome(e2)
    ng = gen + 1

    # o1/o2: LLM-drafted clause addition from each elite's own failures
    for elite, (ec, es) in ((e1, (c1, s1)), (e2, (c2, s2))):
        fails = failure_summaries(elite, gen)
        clause = strip_fences(llm_draft_clause(fails)) if fails else ""
        if clause:
            h, cl = split_clauses(es)
            clause = re.sub(r"^\d+\.\s*", "", clause.splitlines()[0]) \
                if clause.startswith(tuple("0123456789")) else clause
            es2 = join_clauses(h, cl + [clause])
        else:
            es2 = es
        write_genome(f"g{ng}_{elite}_draft", ng, ec, es2, [elite],
                     "ledger_addition", clause[:200])

    # o3: paraphrase of elite-1 semantic block (one LLM call)
    h1, cl1 = split_clauses(s1)
    import openai
    client = openai.OpenAI(base_url=os.environ["QWEN27B_BASE_URL"],
                           api_key=os.environ["QWEN27B_API_KEY"], timeout=300)
    pr = client.chat.completions.create(
        model="Qwen3_8-27B",
        messages=[{"role": "user", "content":
                   "Rewrite each numbered clause below keeping EXACT semantics "
                   "but different wording and sentence structure. Keep the "
                   "numbering and the header line. Output only the rewritten "
                   "file.\n\n" + s1}],
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        temperature=0.9)
    sem_para = strip_fences(pr.choices[0].message.content)
    if not split_clauses(sem_para)[1]:  # malformed rewrite: keep original
        sem_para, note_o3 = s1, "paraphrase fallback (malformed LLM output)"
    else:
        note_o3 = "paraphrase"
    write_genome(f"g{ng}_para_{e1}", ng, c1, sem_para, [e1], note_o3)

    # o4/o5: crossover
    write_genome(f"g{ng}_x_{e1}x{e2}", ng, c1, s2, [e1, e2], "crossover")
    write_genome(f"g{ng}_x_{e2}x{e1}", ng, c2, s1, [e2, e1], "crossover")

    # o6: deletion of the longest semantic clause of elite-1 (verbosity penalty)
    _, cl1 = split_clauses(s1)
    longest = max(range(len(cl1)), key=lambda i: len(cl1[i]))
    write_genome(f"g{ng}_del_{e1}", ng, c1,
                 join_clauses(h1, [c for i, c in enumerate(cl1)
                                   if i != longest]),
                 [e1], "deletion", f"dropped longest clause #{longest+1}")
    print(f"gen{ng}: 6 offspring written")


def cmd_champion(gen: int) -> None:
    cands = []
    for gid in genomes_of_gen(gen):
        f = ledger_fitness(gid, gen)
        if f:
            cands.append((f["success"], -f["phantom"], -f["tokens"], gid))
    cands.sort(reverse=True)
    champ = cands[0][3]
    print(f"gen{gen} champion: {champ}; running gapcheck60 ...")
    run_pilot(champ, gen, GAP60, "gap60")
    out = ROOT / f"runs/evo/gen{gen}/m1_pilot_schema_sol_gap60_{champ}.jsonl"
    s = score_file(out)
    ledger_add({"kind": "gapcheck60", "gen": gen, "gid": champ, **s})
    fit = ledger_fitness(champ, gen)
    dev_rate = fit["success"] / fit["n"]
    gap_rate = s["success"] / s["n"]
    print(f"champion {champ}: dev40 {dev_rate:.1%} vs gap60 {gap_rate:.1%} "
          f"gap {dev_rate - gap_rate:+.1%} "
          f"{'OK' if dev_rate - gap_rate <= 0.05 else 'OVERFIT ALARM'}")


def cmd_status() -> None:
    if not LEDGER.exists():
        print("no ledger yet"); return
    for line in LEDGER.read_text().splitlines():
        r = json.loads(line)
        print(f"gen{r['gen']} {r['kind']:10s} {r['gid']:24s} "
              f"succ {r['success']}/{r['n']}  ph {r['phantom']}  "
              f"tok {r['tokens']}")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    pe = sub.add_parser("eval"); pe.add_argument("--gen", type=int, required=True)
    pn = sub.add_parser("next"); pn.add_argument("--gen", type=int, required=True)
    pc = sub.add_parser("champion"); pc.add_argument("--gen", type=int, required=True)
    sub.add_parser("status")
    args = ap.parse_args()
    {"init": lambda: cmd_init(),
     "eval": lambda: cmd_eval(args.gen),
     "next": lambda: cmd_next(args.gen),
     "champion": lambda: cmd_champion(args.gen),
     "status": cmd_status}[args.cmd]()


if __name__ == "__main__":
    main()
