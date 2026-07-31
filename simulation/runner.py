"""Batch runner — generates large numbers of simulated conversations.

Usage:
    python -m simulation.runner --count 520 --batch sim_batch_1
    python -m simulation.runner --count 100 --lengths 5,10,20,50 --personas all
    python -m simulation.runner --count 10 --live          # real LLM calls

Runs in offline mode by default (no GROQ_API_KEY -> the real orchestrator
pipeline with its deterministic fallbacks). --live loads .env so the
simulations exercise live LLM calls.

Outputs one JSON record per simulation (conversation, reasoning context,
engine outputs, evaluation, memory changes) plus a manifest with batch stats.
"""

import argparse
import json
import os
import random
import sys
import time
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wellness_agent.config import get_data_dir  # noqa: E402

from .personas import PERSONAS, PERSONA_IDS  # noqa: E402
from .simulator import run_simulation  # noqa: E402

DEFAULT_WEIGHTS = {"5": 40, "10": 30, "20": 20, "50": 10}


def build_plan(count, lengths, weights, personas, seed):
    rng = random.Random(seed)
    weight_list = [weights.get(str(l), 1) for l in lengths]
    ordered = list(personas)
    rng.shuffle(ordered)
    plan = []
    for i in range(count):
        length = rng.choices(lengths, weights=weight_list)[0]
        persona = ordered[i % len(ordered)]
        plan.append({"length": length, "persona": persona, "seed": seed + i})
    return plan


def main(argv=None):
    parser = argparse.ArgumentParser(description="Conversation Simulation Engine batch runner")
    parser.add_argument("--count", type=int, default=520, help="number of simulations")
    parser.add_argument("--lengths", default="5,10,20,50", help="turn lengths to generate")
    parser.add_argument("--weights", default="40,30,20,10", help="weights per length")
    parser.add_argument("--personas", default="all", help="comma list or 'all'")
    parser.add_argument("--seed", type=int, default=20260801)
    parser.add_argument("--batch", default=None, help="batch id (default: sim_batch_<ts>)")
    parser.add_argument("--out", default="simulations", help="subdir under data/")
    parser.add_argument("--live", action="store_true", help="load .env and use live LLM")
    parser.add_argument("--keep-stores", action="store_true",
                        help="do not delete per-sim user stores after the run")
    args = parser.parse_args(argv)

    if args.live:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
        print("[sim] LIVE mode — real LLM calls (slower)")
    else:
        os.environ.pop("GROQ_API_KEY", None)
        print("[sim] OFFLINE mode — real pipeline, deterministic fallbacks (no LLM)")

    lengths = [int(x) for x in args.lengths.split(",")]
    weights = {str(l): int(w) for l, w in zip(lengths, args.weights.split(","))}
    personas = PERSONA_IDS if args.personas == "all" else [p.strip() for p in args.personas.split(",")]
    for p in personas:
        if p not in PERSONAS:
            raise SystemExit(f"unknown persona: {p}")

    batch = args.batch or f"sim_batch_{time.strftime('%Y%m%d_%H%M%S')}"
    out_dir = get_data_dir(args.out) / batch
    out_dir.mkdir(parents=True, exist_ok=True)

    plan = build_plan(args.count, lengths, weights, personas, args.seed)
    print(f"[sim] batch={batch} count={len(plan)} lengths={lengths} "
          f"personas={len(personas)} out={out_dir}")

    manifest = {
        "batch_id": batch,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "count": 0,
        "offline": not args.live,
        "personas": {},
        "lengths": {},
        "ended": {},
        "tags": Counter(),
        "files": [],
    }
    t0 = time.time()
    completed = 0

    for i, item in enumerate(plan, 1):
        sim = run_simulation(item["persona"], target_turns=item["length"],
                             seed=item["seed"], keep_stores=args.keep_stores)
        fname = f"{sim['sim_id']}.json"
        with open(out_dir / fname, "w", encoding="utf-8") as f:
            json.dump(sim, f, ensure_ascii=False, indent=1)

        manifest["count"] += 1
        manifest["personas"][item["persona"]] = manifest["personas"].get(item["persona"], 0) + 1
        manifest["lengths"][str(item["length"])] = manifest["lengths"].get(str(item["length"]), 0) + 1
        manifest["ended"][sim["ended"]] = manifest["ended"].get(sim["ended"], 0) + 1
        manifest["tags"].update(sim["tags"])
        manifest["files"].append(fname)
        completed += sim["actual_turns"]

        if i % 50 == 0 or i == len(plan):
            rate = (time.time() - t0) / i
            eta = rate * (len(plan) - i)
            print(f"[sim] {i}/{len(plan)} | {rate:.1f}s/sim | ETA {eta/60:.1f} min | "
                  f"turns={completed}")

    manifest["total_turns"] = completed
    manifest["tags"] = dict(manifest["tags"])
    manifest["duration_s"] = round(time.time() - t0, 1)
    with open(out_dir / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(f"[sim] DONE — {manifest['count']} simulations, {completed} turns, "
          f"{manifest['duration_s']}s")
    print(f"[sim] personas: {dict(manifest['personas'])}")
    print(f"[sim] lengths:  {dict(manifest['lengths'])}")
    print(f"[sim] ended:    {dict(manifest['ended'])}")
    print(f"[sim] manifest: {out_dir / 'manifest.json'}")


if __name__ == "__main__":
    main()
