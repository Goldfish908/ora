#!/usr/bin/env python3
"""Crash guard v0.4: deterministic pre-flight checks for known PySCIPOpt API
misuse patterns (see docs/paper/crash_guard_mining_v0.1.md).

Pure AST/regex, zero LLM cost. Runs after code generation, before the
pre-solve gate and any solver invocation.

Rules:
  G1 setObjective sense must be literal "minimize"/"maximize"
  G2 setObjective first arg must not be a list/ListComp (wrap in quicksum);
     v0.2: also flags names bound to a list literal that flow in as the arg
  G3 no `==` comparison on Expr/addVar results
  G4 quicksum must be called as a function, not m.quicksum (any casing)
  G5 set*Param parameter names must be in the whitelist
  G6 never reassign `data` (the prelude already loads data.json)
  G7 m.infinity is a method — call it: m.infinity()
  G8 read-mode open() of anything but data.json -> FileNotFoundError
  G9 m.sum(...) — Model has no .sum (gurobipy habit); use quicksum
  G10 gurobipy-only attributes (.ObjVal/.Status/.X/.ub/.lb/.getLb/...)
  G11 (v0.4) tainted expression names in boolean/comparison context:
     a name bound to addVar/quicksum/an expr container, then used in
     if/while/ternary tests or comparisons outside addCons — raises
     NotImplementedError via Expr.__richcmp__ (C-arm residual: 5 cells)
  G12 (v0.4) undefined names (NameError at runtime; C-arm residual)

Usage:
  python3 scripts/guard_check.py FILE.py          # single file, exit 1 if hit
  python3 scripts/guard_check.py --offline-eval   # score on 380 round-1 cells
"""

from __future__ import annotations

import argparse
import ast
import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

VALID_SENSE = {"minimize", "maximize"}
PARAM_WHITELIST = {
    "limits/time", "limits/gap", "limits/nodes", "limits/solutions",
    "limits/stallnodes", "limits/maxorigsol", "parallel/maxnthreads",
    "display/verblevel", "display/freq", "numerics/feastol",
    "numerics/dualfeastol", "presolving/maxrounds", "separating/maxcuts",
    "heuristics/emphasis", "lp/threads",
}

# G10: gurobipy-style attributes that do not exist in PySCIPOpt. Accessing or
# calling them raises AttributeError. Observed in B'' residual crashes:
# m.getLb (8x family), Variable.ub, plus the classic m.Status / m.ObjVal /
# var.X that models carry over from gurobipy habit.
GUROBI_ONLY_ATTRS = {
    "ObjVal", "Obj", "Status", "X", "Pi", "RC", "Start", "ub", "lb",
    "getLb", "getUb", "setLb", "setUb", "obj", "Vars", "Constrs",
}


class Guard(ast.NodeVisitor):
    def __init__(self) -> None:
        self.hits: list[dict] = []
        self._safe_cmp: set[int] = set()   # Compare nodes directly inside addCons*
        self._list_names: set[str] = set()  # names currently bound to a list
        self._called_attrs: set[int] = set()  # Attribute nodes used as call func
        self._tainted: set[str] = set()  # names holding Expr / expr-containers
        self._exprfuncs: set[str] = set()  # functions returning expressions

    def _prescan(self, tree: ast.AST) -> None:
        """Global pre-pass: expr containers + expr-returning functions.

        Single-pass taint misses (a) names assigned on one branch then reset
        on another, (b) helper functions returning expressions. Prescan the
        whole tree so both are known before any use-site is visited.
        """
        expr_call = lambda n: isinstance(n, ast.Call) and (  # noqa: E731
            (isinstance(n.func, ast.Attribute) and n.func.attr in
             ("addVar", "quicksum")) or
            (isinstance(n.func, ast.Name) and n.func.id in
             ("addVar", "quicksum")))
        containers: set[str] = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Assign):
                for t in n.targets:
                    if (isinstance(t, ast.Subscript)
                            and isinstance(t.value, ast.Name)
                            and any(expr_call(x) for x in ast.walk(n.value))):
                        containers.add(t.value.id)
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for r in ast.walk(n):
                    if isinstance(r, ast.Return) and r.value is not None:
                        vals = list(ast.walk(r.value))
                        if (any(expr_call(x) for x in vals) or any(
                                isinstance(x, ast.Subscript)
                                and isinstance(x.value, ast.Name)
                                and x.value.id in containers for x in vals)):
                            self._exprfuncs.add(n.name)
                            break
        self._tainted |= containers

    # G11: expression-taint analysis -------------------------------------
    def _exprish(self, v: ast.AST) -> bool:
        """True if v statically evaluates to a PySCIPOpt expression."""
        if isinstance(v, ast.Call):
            f = v.func
            nm = f.attr if isinstance(f, ast.Attribute) else (
                f.id if isinstance(f, ast.Name) else "")
            if nm == "sum":
                # builtin sum is Expr-producing only when its input is
                # (CEGIS refinement: plain sum(costs) must NOT be tainted)
                return any(self._exprish(a) for a in v.args)
            return nm in ("addVar", "quicksum", "addCons") \
                or nm in self._exprfuncs
        if isinstance(v, ast.GeneratorExp):
            return self._exprish(v.elt)
        if isinstance(v, (ast.List, ast.Tuple, ast.Set)):
            return any(self._exprish(e) for e in v.elts)
        if isinstance(v, ast.Dict):
            return any(self._exprish(x) for x in v.values)
        if isinstance(v, ast.Name):
            return v.id in self._tainted
        if isinstance(v, ast.Subscript):
            # sub[...] / sales[...] where the container holds Exprs
            return isinstance(v.value, ast.Name) and v.value.id in self._tainted
        if isinstance(v, ast.BinOp):
            return self._exprish(v.left) or self._exprish(v.right)
        if isinstance(v, ast.BoolOp):
            return any(self._exprish(x) for x in v.values)
        if isinstance(v, ast.UnaryOp):
            return self._exprish(v.operand)
        if isinstance(v, ast.Compare):
            return self._exprish(v.left) or any(
                self._exprish(c) for c in v.comparators)
        if isinstance(v, ast.IfExp):
            return self._exprish(v.body) or self._exprish(v.orelse)
        return False

    def _taint_propagate(self, node: ast.AST) -> None:
        """Assign/AugAssign handler: spread Expr taint through names."""
        if isinstance(node, ast.Assign):
            tainted = self._exprish(node.value)
            for t in node.targets:
                if isinstance(t, ast.Name):
                    if tainted:
                        self._tainted.add(t.id)
                elif isinstance(t, ast.Subscript) and tainted \
                        and isinstance(t.value, ast.Name):
                    # sub[k] = m.addVar(...) -> `sub` is an expr container
                    self._tainted.add(t.value.id)
        elif isinstance(node, ast.AugAssign) and isinstance(node.target,
                                                            ast.Name):
            if node.target.id in self._tainted or self._exprish(node.value):
                self._tainted.add(node.target.id)

    def _check_bool_ctx(self, test: ast.AST, node: ast.AST) -> None:
        """G11: tainted name used as a boolean or in a comparison here."""
        for n in ast.walk(test):
            if isinstance(n, ast.Name) and n.id in self._tainted:
                self._hit("G11", node, f"名称 {n.id!r} 持有 PySCIPOpt 表达式，"
                                       "不能用于 if/while/比较（会触发 "
                                       "Expr.__richcmp__ 的 "
                                       "NotImplementedError）；比较请写进 "
                                       "m.addCons(...)，计数用普通 int/float")
                return

    def visit_Assign(self, node: ast.Assign) -> None:
        # G11 taint: track names bound to expressions (once tainted, stays
        # tainted — a name reset to 0 on one branch may still hold an Expr
        # on another)
        self._taint_propagate(node)
        is_list = isinstance(node.value, (ast.List, ast.ListComp))
        for t in node.targets:
            if isinstance(t, ast.Name):
                if is_list:
                    self._list_names.add(t.id)
                else:
                    self._list_names.discard(t.id)
                # G6: prelude already loads `data`; reassigning it to a
                # None-producing value (directly or via `... if C else None`)
                # kills every later data[...] (NoneType subscript crash)
                if t.id == "data" and self._none_producing(node.value):
                    self._hit("G6", node, "不要把 data 重赋为 None；prelude 已从 "
                                          "data.json 载入数据，直接用 data[...]")
        self.generic_visit(node)

    @staticmethod
    def _none_producing(v: ast.AST) -> bool:
        if isinstance(v, ast.Constant) and v.value is None:
            return True
        if isinstance(v, ast.IfExp):
            return (Guard._none_producing(v.body)
                    or Guard._none_producing(v.orelse))
        return False

    def _hit(self, rule: str, node: ast.AST, msg: str) -> None:
        self.hits.append({"rule": rule, "line": getattr(node, "lineno", 0),
                          "msg": msg})

    def visit_Call(self, node: ast.Call) -> None:
        fn = node.func
        name = ""
        if isinstance(fn, ast.Attribute):
            self._called_attrs.add(id(fn))
            name = fn.attr
            # G4: m.quicksum(...) / m.quickSum(...)
            if name.lower() == "quicksum":
                self._hit("G4", node, "quicksum 是模块函数，不是 Model 方法；"
                                     "用 from pyscipopt import quicksum 后直接调用")
            # G9: m.sum(...) — gurobipy habit; PySCIPOpt Model has no .sum
            if name == "sum" and isinstance(fn.value, ast.Name) \
                    and fn.value.id in ("m", "model"):
                self._hit("G9", node, "Model 没有 .sum() 方法（那是 gurobipy）；"
                                     "用 quicksum([...]) 汇总表达式")
        elif isinstance(fn, ast.Name):
            name = fn.id
            # G8: read-mode open() of anything but data.json -> FileNotFoundError
            if name == "open" and node.args and isinstance(node.args[0], ast.Constant):
                tgt = node.args[0].value
                mode = "r"
                if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
                    mode = node.args[1].value
                for kw in node.keywords:
                    if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                        mode = kw.value.value
                if (isinstance(tgt, str) and tgt != "data.json"
                        and str(mode) in ("r", "rb")):
                    self._hit("G8", node, f"数据只从 data.json 读；读 {tgt!r} "
                                          "会 FileNotFoundError")
        if name.startswith("addCons"):
            for a in node.args:
                if isinstance(a, ast.Compare):
                    self._safe_cmp.add(id(a))
        if name == "setObjective":
            # G1: sense kwarg literal
            for kw in node.keywords:
                if kw.arg == "sense":
                    v = kw.value
                    if isinstance(v, ast.Constant) and isinstance(v.value, str):
                        if v.value.lower() not in VALID_SENSE:
                            self._hit("G1", node,
                                      f"sense={v.value!r} 非法，"
                                      f"PySCIPOpt 只认 'minimize'/'maximize'")
                    else:
                        self._hit("G1", node, "sense 不是字符串字面量，无法静态确认")
            # G2: first positional arg list (literal or name bound to a list)
            if node.args:
                a0 = node.args[0]
                if (isinstance(a0, (ast.List, ast.ListComp)) or
                        (isinstance(a0, ast.Name) and a0.id in self._list_names)):
                    self._hit("G2", node, "目标参数是 list；PySCIPOpt 需要 Expr，"
                                          "用 quicksum([...]) 包一层")
            # positional sense=1 / sense=0
            if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
                v = node.args[1].value
                if isinstance(v, (int, str)) and str(v).lower() not in VALID_SENSE:
                    self._hit("G1", node, f"位置参数 sense={v!r} 非法，"
                                          f"用 'minimize'/'maximize'")
        if name in ("setRealParam", "setIntParam", "setParam",
                    "setLongintParam", "setBoolParam", "setCharParam",
                    "setStringParam"):
            if node.args and isinstance(node.args[0], ast.Constant):
                p = node.args[0].value
                if isinstance(p, str) and p not in PARAM_WHITELIST:
                    self._hit("G5", node, f"SCIP 参数名 {p!r} 不在白名单，"
                                          f"疑似笔误（如 limits/time）")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        # G7: m.infinity is a METHOD in PySCIPOpt; passing it uncalled as
        # ub/lb raises "must be real number, not builtin_function_or_method"
        if node.attr == "infinity" and id(node) not in self._called_attrs:
            self._hit("G7", node, "m.infinity 是方法不是属性，要调用："
                                  "ub=m.infinity()")
        # G10: gurobipy-only attributes (called or not) don't exist in
        # PySCIPOpt — flag regardless of call context
        if node.attr in GUROBI_ONLY_ATTRS:
            self._hit("G10", node, f".{node.attr} 是 gurobipy 用法，"
                                   "PySCIPOpt 不存在；目标值用 m.getObjVal()、"
                                   "状态用 m.getStatus()、取值用 m.getVal(v)、"
                                   "改界用 m.chgVarLb(v, ...)")
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self._taint_propagate(node)
        self.generic_visit(node)

    def visit_If(self, node: ast.If) -> None:
        self._check_bool_ctx(node.test, node)
        self.generic_visit(node)

    def visit_While(self, node: ast.While) -> None:
        self._check_bool_ctx(node.test, node)
        self.generic_visit(node)

    def visit_IfExp(self, node: ast.IfExp) -> None:
        self._check_bool_ctx(node.test, node)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            fake = ast.Assign(targets=[node.target], value=node.value)
            self._taint_propagate(fake)
        self.generic_visit(node)

    def visit_Compare(self, node: ast.Compare) -> None:
        # G3: `==` on expressions is only legal directly inside addCons(...).
        # Flag Eq comparisons elsewhere (if/while/assert/assignment contexts)
        # and chained comparisons on expr-like operands (raises
        # NotImplementedError via Expr.__richcmp__).
        def looks_expr(n: ast.AST) -> bool:
            if isinstance(n, ast.Call):
                f = n.func
                nm = f.attr if isinstance(f, ast.Attribute) else (
                    f.id if isinstance(f, ast.Name) else "")
                return nm in ("addVar", "quicksum")
            if isinstance(n, ast.BinOp):
                return True
            return False
        chained = len(node.ops) > 1
        tainted_op = (isinstance(node.left, ast.Name)
                      and node.left.id in self._tainted) or any(
            isinstance(c, ast.Name) and c.id in self._tainted
            for c in node.comparators)
        exprish = looks_expr(node.left) or any(looks_expr(c)
                                               for c in node.comparators)
        if exprish and (chained or (any(isinstance(op, ast.Eq) for op in node.ops)
                                    and id(node) not in self._safe_cmp)):
            self._hit("G3", node, "对表达式在不安全上下文用比较运算；"
                                  "约束请写进 m.addCons(...)，链式比较不被支持")
        elif tainted_op and id(node) not in self._safe_cmp:
            self._hit("G11", node, "比较运算的操作数是 PySCIPOpt 表达式（经变量"
                                   "传递）；约束请写进 m.addCons(...)，不要"
                                   "在普通比较/if 中使用")
        self.generic_visit(node)


def _undefined_names(tree: ast.AST) -> list[str]:
    """G12: Name Load sites never defined anywhere in the file.

    File-wide collector (any scope) -> low false-positive by design: a name
    assigned in ANY branch counts as defined. The prelude contract adds
    `data`; quicksum/Model come from imports the model writes itself.
    """
    import builtins
    defined = set(dir(builtins)) | {"data"}
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef,
                          ast.ClassDef)):
            defined.add(n.name)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                a = n.args
                for arg in (a.posonlyargs + a.args + a.kwonlyargs):
                    defined.add(arg.arg)
                for arg in (a.vararg, a.kwarg):
                    if arg:
                        defined.add(arg.arg)
        elif isinstance(n, ast.Import):
            defined.update(al.asname or al.name.split(".")[0]
                           for al in n.names)
        elif isinstance(n, ast.ImportFrom):
            defined.update(al.asname or al.name for al in n.names)
        elif isinstance(n, ast.Name) and isinstance(
                n.ctx, (ast.Store, ast.Del)):
            defined.add(n.id)
        elif isinstance(n, ast.NamedExpr) and isinstance(n.target, ast.Name):
            defined.add(n.target.id)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            defined.add(n.name)
    undef = {}
    for n in ast.walk(tree):
        if (isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
                and n.id not in defined):
            undef.setdefault(n.id, n.lineno)
    return sorted(undef.items())


def guard_source(src: str) -> list[dict]:
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return [{"rule": "G0", "line": e.lineno or 0,
                 "msg": f"SyntaxError: {e.msg}"}]
    g = Guard()
    g._prescan(tree)
    g.visit(tree)
    for nm, ln in _undefined_names(tree):
        g.hits.append({"rule": "G12", "line": ln,
                       "msg": f"名称 {nm!r} 从未定义（NameError）；"
                              "检查变量名拼写与定义顺序"})
    return g.hits


def guard_file(path: str | Path) -> list[dict]:
    return guard_source(Path(path).read_text())


def offline_eval() -> None:
    """Score guard on all round-1 gen.py against witness ground truth."""
    import collections
    pilot = ROOT / "runs" / "m1_pilot"
    gt = {}
    for f in sorted(pilot.glob("m1_pilot_schema_sol*.jsonl")):
        for line in f.read_text().splitlines():
            r = json.loads(line)
            gt[(r["scenario_id"], r["thinking"])] = r

    def cls(r: dict) -> str:
        if r["exec_status"] != "ok":
            return "crash"
        if r.get("witness") != "feasible":
            return "phantom"
        return "win" if r.get("grade") == "match" else "other"

    stats = collections.defaultdict(lambda: [0, 0])  # cls -> [flagged, total]
    rule_hits = collections.Counter()
    for (sid, mode), r in sorted(gt.items()):
        for cand in (pilot / "sandbox" / f"schema_sol__{sid}__{mode}" / "gen.py",
                     pilot / "sandbox" / f"{sid}__{mode}" / "gen.py"):
            if cand.exists():
                hits = guard_file(cand)
                c = cls(r)
                stats[c][1] += 1
                if hits:
                    stats[c][0] += 1
                    for h in hits:
                        rule_hits[f"{h['rule']}(→{c})"] += 1
                break
    print("离线评测：380 个 round-1 gen.py")
    for c in ("crash", "phantom", "win", "other"):
        fl, tot = stats.get(c, [0, 0])
        if tot:
            print(f"  {c:8s}: 检出 {fl}/{tot} ({fl/tot:.1%})")
    print("规则命中分布:", dict(rule_hits.most_common()))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("file", nargs="?")
    ap.add_argument("--offline-eval", action="store_true")
    ap.add_argument("--rules", default=None,
                    help="comma whitelist (e.g. G1,G3); hits outside the "
                         "list are dropped. Interface for the evolution "
                         "genome's G-guard slot")
    args = ap.parse_args()
    if args.offline_eval:
        offline_eval()
        return
    if not args.file:
        ap.error("need FILE or --offline-eval")
    hits = guard_file(args.file)
    if args.rules:
        allow = {x.strip() for x in args.rules.split(",") if x.strip()}
        hits = [h for h in hits if h["rule"] in allow]
    for h in hits:
        print(f"[{h['rule']}] line {h['line']}: {h['msg']}")
    sys.exit(1 if hits else 0)


if __name__ == "__main__":
    main()
