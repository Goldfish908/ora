#!/usr/bin/env python3
"""Recompute and plot proxy/truth/phantom curves from official optimization runs."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def ratio(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator else None


def with_rates(row: dict) -> dict:
    n = row["n"]
    executable = row["executable"]
    proxy = row["proxy_match"]
    observed = row.get("observed", n - row.get("runner_errors", 0))
    truth_observed = n - row.get("truth_unknown", 0)
    return {**row,
            "observed": observed,
            "truth_observed": truth_observed,
            "executable_rate": ratio(executable, n),
            "proxy_rate": ratio(proxy, n),
            "true_rate": ratio(row["true_correct"], n),
            "observed_proxy_rate": ratio(proxy, observed),
            "observed_true_rate": ratio(row["true_correct"], truth_observed),
            "phantom_share": ratio(row["phantom"], executable),
            "phantom_proxy_share": ratio(row["phantom_proxy"], proxy)}


def mcnemar_exact(b: int, c: int) -> float:
    if b + c == 0:
        return 1.0
    tail = min(b, c)
    probability = sum(math.comb(b + c, k) for k in range(tail + 1)) / (2 ** (b + c))
    return min(1.0, 2 * probability)


def load_gepa(path: Path) -> list[dict]:
    analysis = json.loads((path / "analysis.json").read_text())
    return [with_rates(row) for row in analysis["curves"]]


def load_alphaopt(path: Path) -> list[dict]:
    analysis = json.loads((path / "analysis.json").read_text())
    return [with_rates(row) for row in analysis["curves"]]


def plot_amplification(runs: dict[str, list[dict]], destination: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 2, figsize=(13, 8.5))
    metrics = (("proxy_rate", "Proxy objective-match rate"),
               ("true_rate", "Independent true-correct rate"),
               ("phantom_proxy_share", "Proxy-pass but witness-fail / proxy-pass"),
               ("executable_rate", "Executable rate"))
    for axis, (metric, title) in zip(axes.flat, metrics):
        for label, rows in runs.items():
            x = list(range(len(rows)))
            axis.plot(x, [row[metric] for row in rows], marker="o", label=label)
        axis.set_title(title)
        axis.set_xlabel("Full-evaluated candidate (incl. seed) / official iteration")
        axis.set_ylim(-0.02, 1.02)
        axis.set_ylabel("Rate")
        axis.grid(alpha=0.2)
    axes[0, 0].legend()
    fig.tight_layout()
    destination.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(destination, dpi=170, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gepa")
    parser.add_argument("--alphaopt")
    parser.add_argument("--figure", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    runs = {}
    if args.gepa:
        runs["GEPA"] = load_gepa(Path(args.gepa))
    if args.alphaopt:
        runs["AlphaOPT"] = load_alphaopt(Path(args.alphaopt))
    if not runs:
        raise ValueError("at least one official run is required")
    figure = (ROOT / args.figure).resolve()
    report = (ROOT / args.report).resolve()
    plot_amplification(runs, figure)
    lines = ["# 代理信号放大曲线", "",
             "所有指标由官方运行制品重算。横轴包含 seed 和完整验证候选，不是仅全局改进候选，也不是所有被拒绝提议。",
             "主幻影指标为 phantom_proxy/proxy_match：弱代理通过但独立强检查失败。普通不可执行或代理未通过不混入该指标。",
             "完整分母 N 用于曲线；observed 排除生成/基础设施错误，truth observed 另排除 UNKNOWN。覆盖不完整时不得把缺失当成真实负例。", "",
             "| 方法 | 代/候选 | 覆盖 observed/N | 真值覆盖/N | 代理匹配 | 真正确 | 幻影/代理通过 | 可执行率 |",
             "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for label, rows in runs.items():
        for index, row in enumerate(rows):
            def fmt(value):
                return "NA" if value is None else f"{value:.1%}"
            lines.append(f"| {label} | {index} | {row['observed']}/{row['n']} | {row['truth_observed']}/{row['n']} | "
                         f"{fmt(row['proxy_rate'])} | {fmt(row['true_rate'])} | "
                         f"{fmt(row['phantom_proxy_share'])} | {fmt(row['executable_rate'])} |")
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("\n".join(lines) + "\n")
    print(json.dumps({"figure": str(figure), "report": str(report),
                      "methods": {label: len(rows) for label, rows in runs.items()}}, indent=1))


if __name__ == "__main__":
    main()
