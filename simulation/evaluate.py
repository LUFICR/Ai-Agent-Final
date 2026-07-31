"""Evaluate a batch of simulated conversations with the AI Conversation Judge.

Usage:
    python -m simulation.evaluate --batch sim_main_520
    python -m simulation.evaluate --batch sim_main_520 --commit v1 --leaderboard
    python -m simulation.evaluate --batch sim_main_520_v2 --compare sim_main_520

Evaluates every simulation record in data/simulations/{batch}/, stores one
evaluation per conversation in data/evaluations/, writes a batch aggregate,
rebuilds leaderboards, and (optionally) compares against a previous commit /
batch to measure improvements.
"""

import argparse
import json
import os
import sys
import time
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wellness_agent.conversation_judge import ConversationJudge  # noqa: E402
from wellness_agent.config import get_data_dir  # noqa: E402
from wellness_agent.leaderboards import (  # noqa: E402
    build_leaderboards, compare_commits, format_deltas)
from wellness_agent.utils.storage import load_json, save_json  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description="Evaluate simulation batches with the Conversation Judge")
    parser.add_argument("--batch", required=True, help="batch dir under data/simulations/")
    parser.add_argument("--commit", default=None, help="commit label (default: batch id)")
    parser.add_argument("--leaderboard", action="store_true", help="build leaderboards")
    parser.add_argument("--compare", default=None, help="previous commit/batch to compare against")
    parser.add_argument("--top", type=int, default=10)
    args = parser.parse_args(argv)

    sim_dir = get_data_dir("simulations") / args.batch
    if not sim_dir.exists():
        raise SystemExit(f"no such batch dir: {sim_dir}")
    files = sorted(f for f in os.listdir(sim_dir) if f.endswith(".json") and f != "manifest.json")
    if not files:
        raise SystemExit(f"no simulation records in {sim_dir}")

    commit = args.commit or args.batch
    judge = ConversationJudge(commit_id=commit)
    t0 = time.time()
    for i, fname in enumerate(files, 1):
        record = load_json(sim_dir / fname)
        judge.evaluate_record(record, meta={"batch": args.batch})
        if i % 100 == 0:
            print(f"[judge] {i}/{len(files)}")
    dt = time.time() - t0

    index = load_json(get_data_dir("evaluations") / "index.json") or {"entries": []}
    entries = [e for e in index["entries"]
               if e.get("commit_id") == commit and e.get("batch") == args.batch]
    agg = {k: 0.0 for k in ("overall", "coaching", "memory", "conversation")}
    by_persona = Counter()
    for e in entries:
        for k in agg:
            agg[k] += e[k]
        by_persona[e.get("persona")] += 1
    for k in agg:
        agg[k] = round(agg[k] / max(1, len(entries)), 1)

    batch_summary = {
        "batch": args.batch, "commit": commit, "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "evaluated": len(entries), "duration_s": round(dt, 1),
        "aggregates": agg, "by_persona_count": dict(by_persona),
    }
    batch_dir = get_data_dir("evaluations") / "batches"
    batch_dir.mkdir(parents=True, exist_ok=True)
    save_json(batch_dir / f"{args.batch}.json", batch_summary)
    print(f"[judge] DONE — {len(entries)} conversations evaluated in {dt:.1f}s")
    print(f"[judge] overall={agg['overall']} coaching={agg['coaching']} "
          f"memory={agg['memory']} conversation={agg['conversation']}")

    if args.leaderboard or args.compare:
        lb = build_leaderboards(commit=commit, label=commit, top=args.top)
        print(f"[judge] leaderboard: {lb['conversations']} conversations "
              f"(label {lb['label']})")

    if args.compare:
        try:
            cmp = compare_commits(args.compare, commit)
            print("[judge] comparison:\n" + format_deltas(cmp))
        except ValueError as e:
            print(f"[judge] compare skipped: {e}")


if __name__ == "__main__":
    main()
