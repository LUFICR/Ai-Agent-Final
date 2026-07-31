"""Batch runner: stress-test all scenarios x seeds, write JSON + auto reports.

Usage (from C:\\test):
    python -m stress.runner --seeds 3
    python -m stress.runner --scenarios suicidal_user,angry_user --seeds 5
    python -m stress.runner --keep-stores --no-report

Outputs:
    data/stress_reports/{run_id}/runs.json      per-run records + scores
    data/stress_reports/{run_id}/report.md      auto-generated report
    data/stress_reports/{run_id}/report.json    machine-readable report
"""

import argparse
import json
import os
import time
from datetime import datetime

from stress.scenarios import SCENARIOS, SCENARIO_IDS
from stress.engine import run_scenario
from stress.scorer import score_run

REPORTS_DIR = os.path.join("data", "stress_reports")


def build_report_dir():
    run_id = datetime.now().strftime("stress_%Y%m%d_%H%M%S")
    path = os.path.join(REPORTS_DIR, run_id)
    os.makedirs(path, exist_ok=True)
    return run_id, path


def run_batch(scenario_ids=None, seeds=(1,), offline=True, keep_stores=False,
              evaluate=True):
    scenario_ids = scenario_ids or list(SCENARIOS.keys())
    results = []
    for sid in scenario_ids:
        for seed in seeds:
            result = run_scenario(sid, seed=seed, offline=offline,
                                  keep_stores=keep_stores, evaluate=evaluate)
            result["score"] = score_run(result)
            results.append(result)
    return results


def summarize(results):
    by_scenario = {}
    for r in results:
        by_scenario.setdefault(r["scenario_id"], []).append(r)
    summary = {
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "scenarios": len(by_scenario),
        "runs": len(results),
        "overall_mean": round(
            sum(r["score"]["overall"] for r in results) / max(1, len(results)), 1),
        "worst_scenarios": [],
        "top_issues": [],
    }
    sc = []
    for sid, runs in by_scenario.items():
        means = {}
        for name in ("safety", "recovery", "memory", "coaching",
                     "state_transitions", "objective_tracking"):
            vals = [r["score"]["measures"].get(name) for r in runs]
            vals = [v for v in vals if v is not None]
            means[name] = round(sum(vals) / len(vals), 1) if vals else None
        agg = round(sum(r["score"]["overall"] for r in runs) / len(runs), 1)
        sc.append({
            "scenario_id": sid,
            "label": runs[0]["label"],
            "category": runs[0]["category"],
            "difficulty": runs[0]["difficulty"],
            "runs": len(runs),
            "mean_overall": agg,
            "mean_measures": means,
            "issues": [i for r in runs for i in r["score"]["issues"]],
        })
    sc.sort(key=lambda s: s["mean_overall"])
    summary["scenario_summary"] = sc
    summary["worst_scenarios"] = [s["scenario_id"] for s in sc[:3]]
    issues = sorted((i for s in sc for i in s["issues"]),
                    key=lambda i: sum(1 for s in sc if i in s["issues"]),
                    reverse=True)
    seen, top = set(), []
    for i in issues:
        if i not in seen:
            seen.add(i)
            top.append(i)
        if len(top) >= 8:
            break
    summary["top_issues"] = top
    return summary


def render_markdown(summary, results):
    L = []
    L.append(f"# AI Stress Test Report")
    L.append(f"\nRun: {summary['run_at']} | {summary['scenarios']} scenarios x "
             f"{summary['runs'] // max(1, summary['scenarios'])} seeds | "
             f"overall mean: **{summary['overall_mean']}**")
    L.append("\n## Scenario summary\n")
    L.append("| scenario | category | diff | runs | overall | safety | recovery | "
             "memory | coaching | states | objectives |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for s in summary["scenario_summary"]:
        m = s["mean_measures"]
        row = [str(s["scenario_id"]), s["category"], str(s["difficulty"]),
               str(s["runs"]), f"{s['mean_overall']:.1f}"]
        for k in ("safety", "recovery", "memory", "coaching",
                  "state_transitions", "objective_tracking"):
            row.append(f"{m[k]:.1f}" if m.get(k) is not None else "-")
        L.append("| " + " | ".join(row) + " |")
    L.append("\n## Worst scenarios\n")
    for sid in summary["worst_scenarios"]:
        s = next(x for x in summary["scenario_summary"] if x["scenario_id"] == sid)
        L.append(f"- **{sid}** ({s['label']}): {s['mean_overall']:.1f}")
    L.append("\n## Top recurring issues\n")
    if summary["top_issues"]:
        for i in summary["top_issues"]:
            L.append(f"- {i}")
    else:
        L.append("- none")
    L.append("\n## Per-run detail\n")
    for r in results:
        sc = r["score"]
        m = sc["measures"]
        L.append(f"\n### {r['scenario_id']} seed={r['seed']} "
                 f"overall={sc['overall']} turns={r['turns']} "
                 f"elapsed={r['elapsed']}s")
        L.append(f"Measures: {json.dumps(m)}")
        if sc["issues"]:
            L.append("Issues:")
            for i in sc["issues"]:
                L.append(f"- {i}")
        L.append("")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenarios", default=", ".join(SCENARIO_IDS))
    ap.add_argument("--seeds", type=int, default=1)
    ap.add_argument("--offline", action="store_true", default=True)
    ap.add_argument("--keep-stores", action="store_true")
    ap.add_argument("--no-eval", action="store_true")
    ap.add_argument("--no-report", action="store_true")
    args = ap.parse_args()

    scenario_ids = [s.strip() for s in args.scenarios.split(",") if s.strip()]
    seeds = tuple(range(1, args.seeds + 1))
    run_id, path = build_report_dir()
    started = time.time()

    results = run_batch(scenario_ids, seeds, offline=args.offline,
                        keep_stores=args.keep_stores, evaluate=not args.no_eval)
    summary = summarize(results)

    with open(os.path.join(path, "runs.json"), "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "results": results}, f,
                  ensure_ascii=False, indent=1, default=str)
    if not args.no_report:
        with open(os.path.join(path, "report.md"), "w", encoding="utf-8") as f:
            f.write(render_markdown(summary, results))
        with open(os.path.join(path, "report.json"), "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=1, default=str)

    print(f"stress run {run_id}: {len(results)} runs in "
          f"{time.time() - started:.1f}s | overall mean {summary['overall_mean']}")
    for s in summary["scenario_summary"]:
        print(f"  {s['scenario_id']:<24} {s['mean_overall']:>5.1f}  "
             f"{s['mean_measures']}")
    print(f"top issues: {summary['top_issues'][:3]}")
    print(f"report: {path}")


if __name__ == "__main__":
    main()
