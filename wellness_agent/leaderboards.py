"""Leaderboards and cross-commit comparison for conversation evaluations.

Reads the evaluation index (data/evaluations/index.json) built by the
ConversationJudge and produces:

  - leaderboards: best conversations per dimension, per persona, per length
  - comparisons: per-dimension deltas between two commits/batches, plus
    per-persona deltas, so improvements across commits are measurable.

All outputs are plain JSON under data/leaderboards.
"""

from collections import defaultdict

from .config import get_data_dir
from .utils.storage import load_json, save_json, now_iso

DIMENSIONS = [
    "coaching", "empathy", "curiosity", "memory_usage", "personalization",
    "pattern_recognition", "recommendation_quality", "naturalness",
    "objective_completion", "hallucination_risk", "contradictions",
    "trust", "return",
]
AGGREGATES = ["overall", "coaching", "memory", "conversation"] + DIMENSIONS


def _index():
    return load_json(get_data_dir("evaluations") / "index.json") or {"entries": []}


def _entries_for(commit=None, batch=None, persona=None):
    entries = _index().get("entries", [])
    if commit:
        entries = [e for e in entries if e.get("commit_id") == commit]
    if batch:
        entries = [e for e in entries if e.get("batch") == batch]
    if persona:
        entries = [e for e in entries if e.get("persona") == persona]
    return entries


def build_leaderboards(commit=None, batch=None, label=None, top=10):
    """Overall + per-dimension leaderboards over the given scope."""
    entries = _entries_for(commit=commit, batch=batch)
    out = {
        "label": label or commit or batch or "all",
        "commit_id": commit,
        "batch": batch,
        "built_at": now_iso(),
        "conversations": len(entries),
        "overall_top": [],
        "dimension_top": {},
        "by_persona": {},
        "by_turn_bucket": {},
    }
    for e in entries:
        out["overall_top"].append({
            "conversation_id": e["conversation_id"], "persona": e.get("persona"),
            "overall": e["overall"], "turns": e["turns"], "generated_at": e["generated_at"],
        })
    out["overall_top"].sort(key=lambda x: x["overall"], reverse=True)
    out["overall_top"] = out["overall_top"][:top]

    for dim in DIMENSIONS + ["overall"]:
        def _score(e, d=dim):
            return e.get(d) if d == "overall" else e.get("dims", {}).get(d, 0)
        ranked = sorted(entries, key=_score, reverse=True)
        out["dimension_top"][dim] = [{
            "conversation_id": e["conversation_id"], "persona": e.get("persona"),
            "score": _score(e), "turns": e["turns"],
        } for e in ranked[:5]]

    by_persona = defaultdict(list)
    for e in entries:
        if e.get("persona"):
            by_persona[e["persona"]].append(e)
    for p, es in sorted(by_persona.items()):
        out["by_persona"][p] = {
            "count": len(es),
            "avg_overall": round(sum(e["overall"] for e in es) / len(es), 1),
            "avg_coaching": round(sum(e["coaching"] for e in es) / len(es), 1),
            "avg_memory": round(sum(e["memory"] for e in es) / len(es), 1),
            "avg_conversation": round(sum(e["conversation"] for e in es) / len(es), 1),
        }

    buckets = defaultdict(list)
    for e in entries:
        t = e.get("turns") or 0
        b = "1-4" if t <= 4 else ("5-10" if t <= 10 else ("11-20" if t <= 20 else "21+"))
        buckets[b].append(e)
    for b, es in sorted(buckets.items()):
        out["by_turn_bucket"][b] = {
            "count": len(es),
            "avg_overall": round(sum(e["overall"] for e in es) / len(es), 1),
        }

    save_json(get_data_dir("leaderboards") / f"leaderboard_{out['label']}.json", out)
    return out


def aggregate(entries):
    out = {"count": len(entries)}
    for key in AGGREGATES:
        if key in DIMENSIONS:
            vals = [e.get("dims", {}).get(key)
                    for e in entries if isinstance(e.get("dims", {}).get(key), (int, float))]
        else:
            vals = [e.get(key) for e in entries if isinstance(e.get(key), (int, float))]
        out[key] = round(sum(vals) / len(vals), 1) if vals else None
    return out


def compare_commits(a, b, out_dir="leaderboards"):
    """Compare aggregates between two commits/batches. Returns deltas (b - a)."""
    ea, eb = _entries_for(commit=a), _entries_for(commit=b)
    if not ea or not eb:
        raise ValueError(f"no evaluations for a={a} ({len(ea)}) or b={b} ({len(eb)})")
    ga, gb = aggregate(ea), aggregate(eb)
    result = {
        "a": {"label": a, "count": len(ea)},
        "b": {"label": b, "count": len(eb)},
        "compared_at": now_iso(),
        "deltas": {k: (round(gb[k] - ga[k], 1) if ga[k] is not None and gb[k] is not None
                       else None) for k in AGGREGATES},
        "aggregates_a": ga,
        "aggregates_b": gb,
        "by_persona": {},
    }
    pa, pb = defaultdict(list), defaultdict(list)
    for e in ea:
        if e.get("persona"):
            pa[e["persona"]].append(e)
    for e in eb:
        if e.get("persona"):
            pb[e["persona"]].append(e)
    for p in sorted(set(pa) & set(pb)):
        aa, ab = aggregate(pa[p]), aggregate(pb[p])
        result["by_persona"][p] = {
            "count_a": aa["count"], "count_b": ab["count"],
            "delta_overall": round(ab["overall"] - aa["overall"], 1),
            "delta_coaching": round(ab["coaching"] - aa["coaching"], 1),
            "delta_memory": round(ab["memory"] - aa["memory"], 1),
            "delta_conversation": round(ab["conversation"] - aa["conversation"], 1),
        }
    get_data_dir(out_dir).mkdir(parents=True, exist_ok=True)
    save_json(get_data_dir(out_dir) / f"compare_{a}_{b}.json", result)
    return result


def format_deltas(result):
    lines = [f"compare {result['a']['label']} ({result['a']['count']}) -> "
             f"{result['b']['label']} ({result['b']['count']})"]
    for k in ["overall", "coaching", "memory", "conversation"]:
        v = result["deltas"].get(k)
        lines.append(f"  {k:14s} {result['aggregates_a'][k]} -> {result['aggregates_b'][k]} "
                     f"({v:+.1f})")
    return "\n".join(lines)
