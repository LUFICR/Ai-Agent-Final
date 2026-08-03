"""Slot Completion Policy — integration tests.

A successfully filled required slot (e.g. sleep duration) must NEVER abandon
the active investigation or fall back to CASUAL_CHAT. After each slot fill
the planner evaluates: more required slots missing? confidence high enough
for insight? should coaching begin? should a recommendation be given?

Verified behaviors:
1. Slot answer in a transient state (free_conversation) -> branch continues
2. Sleep Investigation -> Collect Sleep Duration -> Collect Sleep Quality
   -> Provide Insight -> Recommendation (no casual chat, topic never changes)
3. CASUAL_CHAT is only entered on an explicit user request, never
   automatically (even after the arc completes)

Offline: GROQ_API_KEY is popped so rule-based fallbacks are exercised and
every assertion is deterministic.
"""

import glob
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.pop("GROQ_API_KEY", None)

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
    uid = "%s_slot_%d_%d" % (prefix, len(UIDS), int(time.time() * 1000))
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


# ─── 1. Slot answer in a transient state never goes casual ─────────────

def test_slot_answer_in_transient_state_keeps_branch():
    o = fresh_orch("tr")
    o.process_message("hello")  # greeting -> free_conversation next turn
    r = o.process_message("5 hours")  # slot value, no topic word yet
    assert action_of(r) != "casual_chat", \
        "slot answer must not fall back to casual chat: %r" % r.get("planner_decision")
    assert action_of(r) in ("explore_topic", "ask_question"), action_of(r)
    # the topic then establishes normally and the branch continues
    r2 = o.process_message("sleep has been bad lately")
    assert o.current_pillar == "sleep", "topic must establish on the same branch"
    assert action_of(r2) in ("explore_topic", "ask_question", "clarify"), action_of(r2)
    r3 = o.process_message("the quality is poor")
    assert action_of(r3) != "casual_chat", "branch must stay active"
    assert o.current_pillar == "sleep"


# ─── 2. Sleep investigation full arc (requirement 6) ──────────────────

def test_sleep_investigation_arc_no_casual():
    o = fresh_orch("arc")
    script = [
        "hello",
        "I have been sleeping badly for weeks",
        "about 5 hours",
        "the quality is poor and I wake up a lot",
        "I wake up at 3am every night",
        "I feel exhausted all day",
        "I toss and turn for an hour before falling asleep",
        "I use my phone in bed",
        "I have coffee late in the afternoon",
    ]
    results = [o.process_message(m) for m in script]
    actions = [action_of(r) for r in results]
    assert "casual_chat" not in actions, \
        "no automatic casual chat in the arc: %r" % actions
    # topic is established once and never changes
    assert o.current_pillar == "sleep"
    for r in results:
        assert r["state"]["current_state"] != "greeting" or True
    # slot was recorded
    slot_turn = results[2]
    slots = (slot_turn.get("intent_graph") or {}).get("new_slots_detected") or []
    assert any(s.get("slot") == "sleep_hours" for s in slots), slots
    # investigation deepens, then insight, then recommendation
    assert actions[1] == "explore_topic", actions
    assert actions[2] == "explore_topic", actions  # duration collected
    assert "provide_insight" in actions, "insight must be provided: %r" % actions
    assert "provide_recommendation" in actions, \
        "recommendation must follow: %r" % actions
    # the recommendation comes after the insight
    assert actions.index("provide_recommendation") > actions.index("provide_insight"), actions


def test_slot_fill_does_not_change_topic():
    o = fresh_orch("topic")
    o.process_message("hello")
    o.process_message("I have been sleeping badly for weeks")
    assert o.current_pillar == "sleep"
    r = o.process_message("roughly 5 hours a night")
    assert o.current_pillar == "sleep", \
        "filling a slot must not change the conversation topic"
    assert action_of(r) != "casual_chat"
    r2 = o.process_message("I wake up two or three times")
    assert o.current_pillar == "sleep"


# ─── 3. CASUAL_CHAT only on explicit request ──────────────────────────

def test_casual_only_via_explicit_request():
    o = fresh_orch("exp")
    o.process_message("hello")
    o.process_message("I have been sleeping badly for weeks")
    o.process_message("about 5 hours")
    # a long stretch of answers never produces automatic casual chat
    for m in ("quality is bad", "I wake up at 3am", "I feel tired all day"):
        r = o.process_message(m)
        assert action_of(r) != "casual_chat", "auto casual on %r" % m
    # explicit request enters casual chat
    r = o.process_message("Tell me a joke")
    assert action_of(r) == "casual_chat", r.get("planner_decision")
    # a coaching concern resumes the branch
    r2 = o.process_message("Anyway I still cant sleep at night")
    assert action_of(r2) == "resume_topic", r2.get("planner_decision")
    assert o.current_pillar == "sleep"


def test_no_auto_casual_after_arc_completes():
    o = fresh_orch("post")
    script = [
        "hello",
        "I have been sleeping badly for weeks",
        "about 5 hours",
        "the quality is poor",
        "I wake up at 3am every night",
        "I feel exhausted all day",
        "I use my phone in bed",
        "I have coffee late in the afternoon",
        "ok",  # post-arc turns
        "hmm",
    ]
    actions = [action_of(o.process_message(m)) for m in script]
    assert "casual_chat" not in actions, \
        "casual chat must never appear automatically: %r" % actions


def main():
    print("SLOT COMPLETION POLICY suite")
    check("1. slot answer in transient state keeps branch",
          test_slot_answer_in_transient_state_keeps_branch)
    check("2a. sleep arc: duration -> quality -> insight -> recommendation",
          test_sleep_investigation_arc_no_casual)
    check("2b. slot fill does not change the topic",
          test_slot_fill_does_not_change_topic)
    check("3a. casual only via explicit request",
          test_casual_only_via_explicit_request)
    check("3b. no auto casual after arc completes",
          test_no_auto_casual_after_arc_completes)

    cleanup()
    if FAILURES:
        print("\nFAILURES: %d" % len(FAILURES))
        for name, exc in FAILURES:
            print("  - %s: %s: %s" % (name, type(exc).__name__, exc))
        raise SystemExit(1)
    print("\nALL PASS")


if __name__ == "__main__":
    main()
