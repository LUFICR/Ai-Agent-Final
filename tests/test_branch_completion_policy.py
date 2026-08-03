"""Branch Completion Engine — integration tests.

Generic per-branch slot completion: each branch (Sleep, Mental Health,
Productivity, Physical Health, Relationships) declares required slots and a
completion threshold; the planner evaluates completion after every message
and, on threshold met, NEVER asks another discovery question — it moves to
the branch's terminal sequence (insight -> recommendation -> ...).

Verified behaviors:
1. Sleep      duration -> quality/consistency -> insight -> recommendation
2. Mental Health emotion -> duration -> impact  -> insight -> recommendation
3. Productivity overwhelm -> focus -> procrastination -> insight
4. Physical Health activity -> frequency -> insight
5. Relationships relationship/emotion -> insight
6. The generic casual fallback is gone: avoidance at rapport never auto-
   offers "just chat" — it stays a coaching question
7. After branch completion no further discovery questions are ever asked
8. The completion metadata (branch, filled, next_actions) rides the
   planner_decision so the UI/API can see the outcome

Offline: GROQ_API_KEY is popped so rule-based fallbacks are exercised and
every assertion is deterministic.
"""

import glob
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.pop("GROQ_API_KEY", None)

from wellness_agent.conversation_planner import (  # noqa: E402
    ConversationMode,
    ConversationPlanner,
)
from wellness_agent.orchestrator import Orchestrator  # noqa: E402

FAILURES = []


def check(name, fn):
    try:
        fn()
        print("  ok - %s" % name)
    except Exception as exc:  # noqa: BLE001
        FAILURES.append((name, exc))
        print("  FAIL - %s: %s: %s" % (name, type(exc).__name__, exc))


DATA_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
UIDS = []


def fresh_orch(prefix):
    uid = "%s_bc_%d_%d" % (prefix, len(UIDS), int(time.time() * 1000))
    UIDS.append(uid)
    return Orchestrator(user_id=uid, enable_learning=False, enable_auto_judge=False)


def cleanup():
    for uid in UIDS:
        for sub in ("sessions", "memory", "beliefs", "learning"):
            for f in glob.glob(os.path.join(DATA_ROOT, sub, "%s*.json" % uid)):
                try:
                    os.remove(f)
                except OSError:
                    pass


def action_of(turn):
    return (turn.get("planner_decision") or {}).get("action")


def meta_of(turn):
    return (turn.get("planner_decision") or {}).get("metadata") or {}


def planner_ctx(pillar, message):
    return {"message": message, "intent_graph": {}, "emotion": {},
            "state": "deep_investigation", "route": ["question_planner"],
            "current_pillar": pillar}


def run_branch(pillar, messages):
    """Deterministic planner-level branch run (explicit pillar)."""
    p = ConversationPlanner()
    decisions = [p.decide(planner_ctx(pillar, m)) for m in messages]
    return p, decisions


def completion_turn(decisions):
    for i, d in enumerate(decisions):
        if d.metadata.get("branch_completion"):
            return i, d
    raise AssertionError("no branch_completion decision in: %r" % [
        (d.action.value, dict(d.metadata)) for d in decisions])


# ─── 1. Sleep branch ───────────────────────────────────────────────────

def test_sleep_branch_completes_to_insight():
    p, decisions = run_branch("sleep", [
        "about 5 hours",                            # duration (1/2)
        "the quality is poor and I wake up a lot",  # quality + consistency -> COMPLETE
    ])
    assert decisions[0].action.value == "explore_topic", decisions[0].action
    i, d = completion_turn(decisions)
    assert d.action.value == "provide_insight", d.action
    assert p.current_mode() == ConversationMode.COACHING, p.current_mode()
    meta = d.metadata
    assert meta["branch"] == "sleep" and meta["pillar"] == "sleep", meta
    assert set(meta["filled"]) >= {"duration", "quality", "consistency"}, meta
    assert meta["missing"] == [] and meta["next_actions"][0] == "provide_insight", meta
    # completion is one-shot: no second branch_completion on further input
    d_after = p.decide(planner_ctx("sleep", "I wake up at 3am every night"))
    assert not d_after.metadata.get("branch_completion"), d_after.metadata


def test_sleep_branch_orchestrator_arc():
    o, results, actions = run_arc([
        "hello",                                    # greeting
        "I have been sleeping badly for weeks",     # duration (1/2)
        "about 5 hours",                            # explore continues
        "the quality is poor and I wake up a lot",  # quality+consistency -> COMPLETE
        "I feel exhausted all day",                 # recommendation
    ])
    assert o.current_pillar == "sleep", o.current_pillar
    insight_idx = actions.index("provide_insight")
    rec_idx = actions.index("provide_recommendation")
    assert rec_idx > insight_idx, actions
    assert "casual_chat" not in actions, actions
    completion = [i for i, r in enumerate(results) if meta_of(r).get("branch_completion")]
    assert completion == [3], completion
    meta = meta_of(results[3])
    assert meta["branch"] == "sleep" and meta["pillar"] == "sleep", meta
    assert set(meta["filled"]) >= {"duration", "quality", "consistency"}, meta
    assert meta["next_actions"][0] == "provide_insight", meta


# ─── 2. Mental Health branch ───────────────────────────────────────────

def test_mental_health_branch_completes_to_insight():
    p, decisions = run_branch("mood", [
        "I have been feeling really anxious lately",  # emotion + duration (2/3)
        "it's affecting my work",                     # impact -> COMPLETE
    ])
    assert decisions[0].action.value == "explore_topic", decisions[0].action
    i, d = completion_turn(decisions)
    assert d.action.value == "provide_insight", d.action
    meta = d.metadata
    assert meta["branch"] == "mental_health", meta
    assert set(meta["filled"]) >= {"predominant_emotion", "duration", "impact"}, meta
    assert "summarize" in meta["next_actions"], meta
    # below threshold: emotion + duration alone is not enough
    p2 = ConversationPlanner()
    d1 = p2.decide(planner_ctx("mood", "I have been really anxious lately"))
    d2 = p2.decide(planner_ctx("mood", "I've felt this way for months"))
    assert d1.action.value == "explore_topic"
    assert not d2.metadata.get("branch_completion"), d2.metadata


def test_mental_health_optional_slots_tracked_not_required():
    from wellness_agent.branch_policy import evaluate_branch_completion
    ev = evaluate_branch_completion(
        "I feel anxious all the time and it's ruining everything",
        "mood", {}, set())
    assert ev["completed"], ev  # emotion + duration + impact in one message
    ev2 = evaluate_branch_completion(
        "I have been anxious since my promotion", "mood", {},
        filled={"predominant_emotion", "duration", "impact"})
    assert ev2["completed"], ev2
    ev3 = evaluate_branch_completion(
        "since my promotion", "mood", {}, filled={"predominant_emotion"})
    assert not ev3["completed"] and "trigger" in ev3["filled"], ev3


# ─── 3. Productivity branch ────────────────────────────────────────────

def test_productivity_branch_completes_to_insight():
    p, decisions = run_branch("work", [
        "I can't focus on anything",     # focus (1/2)
        "I keep putting everything off", # procrastination -> COMPLETE
    ])
    assert decisions[0].action.value == "explore_topic", decisions[0].action
    i, d = completion_turn(decisions)
    assert d.action.value == "provide_insight", d.action
    meta = d.metadata
    assert meta["branch"] == "productivity", meta
    assert "focus" in meta["filled"] and "procrastination" in meta["filled"], meta


# ─── 4. Physical Health branch ─────────────────────────────────────────

def test_physical_health_branch_completes_to_insight():
    p, decisions = run_branch("exercise", [
        "I used to run every morning",   # activity (1/2)
        "but now I have no time",        # barrier -> COMPLETE
    ])
    assert decisions[0].action.value == "explore_topic", decisions[0].action
    i, d = completion_turn(decisions)
    assert d.action.value == "provide_insight", d.action
    meta = d.metadata
    assert meta["branch"] == "physical_health", meta
    assert "activity" in meta["filled"] and "barrier" in meta["filled"], meta


# ─── 5. Relationships branch ───────────────────────────────────────────

def test_relationships_branch_completes_to_insight():
    p, decisions = run_branch("relationships", [
        "My partner keeps ignoring me",  # relationship (1/2)
        "I feel so lonely lately",       # emotion + duration -> COMPLETE
    ])
    assert decisions[0].action.value == "explore_topic", decisions[0].action
    i, d = completion_turn(decisions)
    assert d.action.value == "provide_insight", d.action
    meta = d.metadata
    assert meta["branch"] == "relationships", meta
    assert "relationship" in meta["filled"] and "emotion" in meta["filled"], meta


# ─── 6. Generic casual fallback removed ────────────────────────────────

def test_no_generic_casual_fallback_on_avoidance():
    o = fresh_orch("nofb")
    o.process_message("hello")
    o.process_message("I have been having trouble sleeping lately")
    o.process_message("about 5 hours")
    # two short deflections drive the hard avoidance counter to 2, which
    # used to trigger "avoidance at rapport -> offer casual chat"
    r1 = o.process_message("no")
    r2 = o.process_message("no")
    assert action_of(r1) != "casual_chat", r1.get("planner_decision")
    assert action_of(r2) != "casual_chat", r2.get("planner_decision")
    assert action_of(r2) in ("ask_question", "explore_topic", "clarify"), \
        r2.get("planner_decision")
    assert "just chat" not in r2["response"].lower(), r2["response"]
    assert "chat about your day" not in r2["response"].lower(), r2["response"]
    assert not meta_of(r2).get("casual_offer"), r2.get("planner_decision")
    # an EXPLICIT casual request still enters casual chat
    r3 = o.process_message("Tell me a joke")
    assert action_of(r3) == "casual_chat", r3.get("planner_decision")


# ─── 7. No discovery questions after completion ────────────────────────

def test_no_discovery_question_after_branch_completion():
    o, results, actions = run_arc([
        "hello",
        "I have been sleeping badly for weeks",
        "about 5 hours",
        "the quality is poor and I wake up a lot",  # COMPLETE -> insight
        "I feel exhausted all day",                 # recommendation
        "I wake up at 3am every night",             # recommendation continues
        "ok",                                       # acceptance -> commitment
    ])
    insight_idx = actions.index("provide_insight")
    after = actions[insight_idx + 1:]
    assert after, actions
    for a in after:
        assert a not in ("ask_question", "explore_topic", "clarify"), \
            "discovery question after branch completion: %s (%r)" % (a, actions)
    assert "provide_recommendation" in after and "create_commitment" in after, actions


# ─── 8. Completion metadata rides the planner decision ─────────────────

def test_branch_completion_metadata_on_decision():
    o = fresh_orch("meta")
    o.process_message("hello")
    o.process_message("I have been sleeping badly for weeks")
    o.process_message("about 5 hours")
    r = o.process_message("the quality is poor and I wake up at 3am")
    meta = meta_of(r)
    assert meta.get("branch_completion") is True, meta
    assert meta.get("branch") == "sleep", meta
    assert meta.get("pillar") == "sleep", meta
    assert meta.get("insight") is True, meta
    assert set(meta.get("filled") or []) >= {"duration", "quality", "consistency"}, meta
    assert "missing" in meta and meta["next_actions"][0] == "provide_insight", meta
    assert (r.get("planner_decision") or {}).get("action") == "provide_insight"


def run_arc(script):
    o = fresh_orch("arc")
    results = [o.process_message(m) for m in script]
    return o, results, [action_of(r) for r in results]


def main():
    print("BRANCH COMPLETION POLICY suite")
    check("1a. sleep branch: slots -> insight (planner)",
          test_sleep_branch_completes_to_insight)
    check("1b. sleep branch: natural orchestrator arc -> recommendation",
          test_sleep_branch_orchestrator_arc)
    check("2a. mental health branch: emotion/duration/impact -> insight",
          test_mental_health_branch_completes_to_insight)
    check("2b. optional slots tracked but never required",
          test_mental_health_optional_slots_tracked_not_required)
    check("3. productivity branch: overwhelm/focus/procrastination",
          test_productivity_branch_completes_to_insight)
    check("4. physical health branch: activity/barrier",
          test_physical_health_branch_completes_to_insight)
    check("5. relationships branch: relationship/emotion",
          test_relationships_branch_completes_to_insight)
    check("6. generic casual fallback removed (explicit only)",
          test_no_generic_casual_fallback_on_avoidance)
    check("7. no discovery questions after completion",
          test_no_discovery_question_after_branch_completion)
    check("8. completion metadata rides planner_decision",
          test_branch_completion_metadata_on_decision)

    cleanup()
    if FAILURES:
        print("\nFAILURES: %d" % len(FAILURES))
        for name, exc in FAILURES:
            print("  - %s: %s: %s" % (name, type(exc).__name__, exc))
        raise SystemExit(1)
    print("\nALL PASS")


if __name__ == "__main__":
    main()
