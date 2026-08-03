"""QUESTION_SELECTION_POLICY.md (v1.0) — integration tests for every rule.

Spec: docs/specifications/QUESTION_SELECTION_POLICY.md

Covered policies:
1. Greeting Policy            — greetings never show category buttons
                               (only conversation-entry quick replies)
2. Rich Free Text Policy      — rich free text always beats buttons
3. Button Policy              — buttons are a fallback, not the primary UI
4. (no category questions when the problem is already described)
5. Maximum Questions Rule     — max two consecutive questions, then value
6. Direct Question Policy     — direct questions interrupt and resume coaching
7. Casual Conversation Policy — casual chat disables coaching
8. Recommendation Policy      — recommendation acceptance moves to Commitment
9. (Commitment)               — Commitment moves to Scheduling or Closure
10. Loop Prevention           — discovery happens only once per conversation
11. Question Priority         — Reflective -> Clarifying -> Narrowing -> Action
                               -> Commitment, never reversed
12. Topic Switching           — switch topic without restarting discovery

Offline: GROQ_API_KEY is popped so rule-based fallbacks are exercised and
every assertion is deterministic.
"""

import os
import re
import sys
import glob
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.pop("GROQ_API_KEY", None)

from wellness_agent.orchestrator import Orchestrator
from wellness_agent.conversation_planner import (
    ConversationMode,
    ConversationPlanner,
    PlannerAction,
    _QUICK_REPLY_ENTRY_BUTTONS,
)

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
    uid = "%s_pol_%d_%d" % (prefix, len(UIDS), int(time.time() * 1000))
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


_ASKING = ("ask_question", "explore_topic", "clarify")

# ─── 1. Greeting Policy ───────────────────────────────────────────────

def test_greetings_never_show_category_buttons():
    for msg in ("hi", "hello", "hey", "hey there", "good morning"):
        o = fresh_orch("gr")
        r = o.process_message(msg)
        pd = r.get("planner_decision") or {}
        # Greeting shows the four conversation-ENTRY quick replies — these
        # start a topic (Work/Relationships/Mental health/Physical health),
        # they are NOT diagnostic category buttons.
        assert r.get("options") == _QUICK_REPLY_ENTRY_BUTTONS, \
            "greeting %r must offer conversation-entry quick replies (got %r)" % (
                msg, r.get("options"))
        assert pd.get("showQuickReplies") is True, pd
        assert pd.get("quickReplyType") == "conversation_entry", pd
        assert action_of(r) == "ask_question", r.get("planner_decision")
        assert meta_of(r).get("greeting"), "greeting metadata missing"
        assert meta_of(r).get("button_mode") == "free", "greeting must be free text"
        text = r["response"].strip().lower()
        assert text.endswith("?"), "greeting must be one open question: %r" % text
        assert not re.search(r"\b(sleep|work|stress|relationships|mood)\b", text), \
            "greeting must not open a category tree: %r" % text


# ─── 2. Rich Free Text Policy ─────────────────────────────────────────

def test_rich_free_text_beats_buttons():
    o = fresh_orch("rich")
    r1 = o.process_message("I'm stressed because of work")
    assert r1.get("options") is None, "rich free text must beat buttons"
    assert action_of(r1) == "explore_topic", r1.get("planner_decision")
    # emotion + context + cause + timeline
    r2 = o.process_message("It got worse after my manager added more scope three weeks ago")
    assert r2.get("options") is None, "rich free text must beat buttons"
    low = r2["response"].lower()
    assert "which of these" not in low and "category" not in low and \
        "choose" not in low, "no category question when problem described: %r" % low
    assert low.strip().endswith("?"), "natural continuation should still move forward"


def test_rich_input_does_not_open_category_tree():
    o = fresh_orch("rich2")
    o.process_message("I'm overwhelmed by my job and it keeps me up at night")
    r = o.process_message("My manager keeps piling on work and I can't sleep because of it")
    assert r.get("options") is None
    low = r["response"].lower()
    for bad in ("which of these", "choose", "category", "which area", "fits best",
                "which one resonates"):
        assert bad not in low, "category-style question after problem described: %r" % low


# ─── 3. Button Policy (fallback only) ─────────────────────────────────

def test_buttons_only_in_fallback_conditions():
    o = fresh_orch("btn")
    o.process_message("I'm really stressed about work deadlines")
    # uncertainty -> buttons are the sanctioned recovery tool
    r = o.process_message("I don't know")
    assert r.get("options"), "uncertainty fallback must offer buttons"
    assert meta_of(r).get("button_mode") == "choice"
    # ...but rich free text immediately wins again
    r2 = o.process_message("Actually it's mostly my manager and the constant pressure")
    assert r2.get("options") is None, "free text always beats buttons"
    # plain short input (no uncertainty) -> free text, not buttons
    o2 = fresh_orch("btn2")
    o2.process_message("I've been feeling anxious every morning this week")
    r3 = o2.process_message("yes")
    assert r3.get("options") is None, "plain minimal input must stay free text"


# ─── 5. Maximum Questions Rule ────────────────────────────────────────

def test_max_two_consecutive_questions_then_value_unit():
    p = ConversationPlanner()
    ctx = {"message": "I don't know", "intent_graph": {}, "emotion": {},
           "state": "deep_investigation", "route": ["question_planner"],
           "current_pillar": "work", "avoidance_count": 0}
    d1 = p.decide(dict(ctx))
    d2 = p.decide(dict(ctx))
    d3 = p.decide(dict(ctx))
    assert d1.action == PlannerAction.EXPLORE_TOPIC, d1.action
    assert d2.action == PlannerAction.EXPLORE_TOPIC, d2.action
    # third consecutive question MUST provide value, never WAIT
    assert d3.action == PlannerAction.PROVIDE_INSIGHT, d3.action
    assert d3.metadata.get("insight"), d3.metadata
    # a fresh arc may begin after value, at Reflective again
    d4 = p.decide(dict(ctx))
    assert d4.action == PlannerAction.EXPLORE_TOPIC, d4.action
    assert d4.metadata.get("question_priority") == "reflective", d4.metadata


def test_max_two_consecutive_questions_integration():
    o = fresh_orch("maxq")
    o.process_message("I am stressed about work")
    o.process_message("Work is constant pressure and deadlines")
    actions = []
    for _ in range(6):
        r = o.process_message("hmm")
        actions.append(action_of(r))
    run = 0
    longest = 0
    for a in actions:
        run = run + 1 if a in _ASKING else 0
        longest = max(longest, run)
    assert longest <= 2, "more than two consecutive questions: %r" % actions
    # value must appear (insight/reflection/summary/recommendation/close)
    value = {"provide_insight", "provide_recommendation", "reflect", "summarize",
             "close_conversation", "wait", "casual_chat"}
    assert any(a in value for a in actions), "no value action after questions: %r" % actions


# ─── 6. Direct Question Policy ────────────────────────────────────────

def test_direct_question_interrupts_coaching_and_resumes():
    o = fresh_orch("dq")
    o.process_message("I have been sleeping only five hours for weeks")
    r = o.process_message("Why do I feel so tired all the time?")
    assert action_of(r) == "answer_direct_question", r.get("planner_decision")
    assert o.agents.planner.mode_state()["current_mode"] == "question_answering"
    # the response answers; it is not a new coaching question
    assert "?" not in r["response"] or "want" in r["response"].lower()
    # previous mode resumes, discovery does not restart
    r2 = o.process_message("It's the lack of sleep and too much coffee")
    assert action_of(r2) == "resume_topic", r2.get("planner_decision")
    assert o.agents.planner.mode_state()["current_mode"] == "investigation"
    assert "Back to what we were exploring" in r2["response"]


# ─── 7. Casual Conversation Policy ────────────────────────────────────

def test_casual_chat_disables_coaching():
    o = fresh_orch("cc")
    o.process_message("I have been sleeping badly for weeks")
    r = o.process_message("Let's just chat")
    assert action_of(r) == "casual_chat"
    assert o.agents.planner.mode_state()["current_mode"] == "casual_chat"
    # no coaching, no diagnosis, no categories while casual
    r2 = o.process_message("Haha nice one")
    assert action_of(r2) == "casual_chat"
    assert not r2["response"].startswith(
        ("Which", "On a scale", "How long", "Does that", "When you")), r2["response"]
    assert r2.get("options") is None
    # coaching resumes only when the user introduces a coaching topic
    r3 = o.process_message("Anyway I still cant sleep at night")
    assert action_of(r3) == "resume_topic", r3.get("planner_decision")
    assert o.agents.planner.mode_state()["current_mode"] == "investigation"


# ─── 8. Recommendation Acceptance -> Commitment ───────────────────────

def _drive_to_recommendation(o):
    script = [
        "I am totally burned out from work deadlines",
        "Work is just constant pressure and I cant switch off",
        "I sleep badly, maybe 5 hours a night",
        "I keep checking my phone in bed",
        "I dont have any wind-down routine",
        "Mornings I feel exhausted",
        "I want a proper sleep schedule",
        "Yes, that's it",
    ]
    last = None
    for msg in script:
        last = o.process_message(msg)
    return last


def test_recommendation_acceptance_moves_to_commitment():
    o = fresh_orch("rec")
    rec = _drive_to_recommendation(o)
    assert action_of(rec) == "provide_recommendation", rec.get("planner_decision")
    r = o.process_message("Sounds good, let's do it")
    assert action_of(r) == "create_commitment", r.get("planner_decision")
    assert o.agents.planner.mode_state()["current_mode"] == "commitment"
    # commitment asks WHEN — it never returns to discovery
    assert "tomorrow" in r["response"].lower() or "time" in r["response"].lower()


# ─── 9. Commitment -> Scheduling or Closure ───────────────────────────

def test_commitment_moves_to_scheduling_then_closure():
    o = fresh_orch("com")
    _drive_to_recommendation(o)
    r1 = o.process_message("Sounds good, let's do it")
    assert action_of(r1) == "create_commitment"
    r2 = o.process_message("Yes, tomorrow morning")
    assert action_of(r2) == "schedule_action", r2.get("planner_decision")
    assert o.agents.planner.mode_state()["current_mode"] == "commitment"
    r3 = o.process_message("Morning works")
    assert action_of(r3) == "close_conversation", r3.get("planner_decision")
    assert o.agents.planner.mode_state()["current_mode"] == "closure"


def test_commitment_decline_moves_to_closure():
    o = fresh_orch("com2")
    _drive_to_recommendation(o)
    r1 = o.process_message("Sounds good, let's do it")
    assert action_of(r1) == "create_commitment"
    r2 = o.process_message("Not right now")
    assert action_of(r2) == "close_conversation", r2.get("planner_decision")
    assert o.agents.planner.mode_state()["current_mode"] == "closure"


# ─── 10. Discovery only once per conversation ─────────────────────────

def test_discovery_happens_once_per_conversation():
    p = ConversationPlanner()
    ctx = {"message": "hi", "intent_graph": {}, "emotion": {},
           "state": "greeting", "route": []}
    p.decide(dict(ctx))
    assert p.current_mode() == ConversationMode.DISCOVERY
    ctx.update({"state": "deep_investigation", "route": ["question_planner"],
                "current_pillar": "sleep", "message": "I sleep badly"})
    p.decide(dict(ctx))
    assert p.current_mode() == ConversationMode.INVESTIGATION
    # a bounce back to discovery states must never re-enter DISCOVERY
    ctx.update({"state": "guided_discovery", "message": "Something else"})
    for _ in range(3):
        p.decide(dict(ctx))
        assert p.current_mode() != ConversationMode.DISCOVERY, \
            "discovery must not re-enter"


def test_no_discovery_restart_after_commitment_orchestrator():
    o = fresh_orch("nd")
    _drive_to_recommendation(o)
    o.process_message("Sounds good, let's do it")
    o.process_message("Yes, tomorrow morning")
    o.process_message("Morning works")
    assert o.agents.planner.mode_state()["current_mode"] == "closure"
    r = o.process_message("I'm actually still stressed about work")
    assert o.agents.planner.mode_state()["current_mode"] != ConversationMode.DISCOVERY
    assert action_of(r) != "ask_question" or "greeting" not in (meta_of(r) or {})


# ─── 11. Question Priority ladder (never reversed) ────────────────────

def test_question_priority_never_reversed():
    o = fresh_orch("lad")
    r1 = o.process_message("I'm stressed because of work")
    assert meta_of(r1).get("question_priority") == "reflective", meta_of(r1)
    assert action_of(r1) == "explore_topic"
    r2 = o.process_message("work")
    assert action_of(r2) == "explore_topic", r2.get("planner_decision")
    assert meta_of(r2).get("question_priority") == "clarifying", meta_of(r2)
    order = ["reflective", "clarifying", "narrowing", "action", "commitment"]
    idx = [order.index(meta_of(r)["question_priority"]) for r in (r1, r2)]
    assert idx == sorted(idx), "question priority reversed: %r" % idx
    # both questions are free text (buttons are fallback only)
    assert r1.get("options") is None and r2.get("options") is None


# ─── 12. Topic switching without discovery restart ────────────────────

def test_topic_switch_without_discovery_restart():
    o = fresh_orch("sw")
    o.process_message("I am stressed out about my deadlines")
    r = o.process_message("Actually I want to talk about my sleep instead")
    assert action_of(r) == "switch_topic", r.get("planner_decision")
    assert meta_of(r).get("target_topic") == "sleep"
    assert o.current_pillar == "sleep"
    # natural free-text continuation, no category buttons, no discovery tree
    assert r.get("options") is None
    assert "sleep" in r["response"].lower()


# ─── Golden Rule: value before data ───────────────────────────────────

def test_rich_input_gets_continuation_not_interrogation():
    o = fresh_orch("gold")
    r = o.process_message("Since the breakup two weeks ago I've been sad and can't focus")
    assert r.get("options") is None
    low = r["response"].lower()
    assert not re.search(r"\b(scale of 1-10|how many hours|how long)\b", low), \
        "no numeric interrogation when rich context exists: %r" % low


def main():
    print("QUESTION_SELECTION_POLICY suite")
    check("1. greetings never show category buttons", test_greetings_never_show_category_buttons)
    check("2a. rich free text always beats buttons", test_rich_free_text_beats_buttons)
    check("2b. no category tree when problem described", test_rich_input_does_not_open_category_tree)
    check("3. buttons are a fallback, not the primary UI", test_buttons_only_in_fallback_conditions)
    check("5a. max two questions then value (planner unit)", test_max_two_consecutive_questions_then_value_unit)
    check("5b. max two questions then value (orchestrator)", test_max_two_consecutive_questions_integration)
    check("6. direct questions interrupt coaching and resume", test_direct_question_interrupts_coaching_and_resumes)
    check("7. casual chat disables coaching", test_casual_chat_disables_coaching)
    check("8. recommendation acceptance moves to commitment", test_recommendation_acceptance_moves_to_commitment)
    check("9a. commitment -> scheduling -> closure", test_commitment_moves_to_scheduling_then_closure)
    check("9b. commitment decline -> closure", test_commitment_decline_moves_to_closure)
    check("10a. discovery happens once (planner unit)", test_discovery_happens_once_per_conversation)
    check("10b. no discovery restart after commitment", test_no_discovery_restart_after_commitment_orchestrator)
    check("11. question priority never reversed", test_question_priority_never_reversed)
    check("12. topic switch without discovery restart", test_topic_switch_without_discovery_restart)
    check("golden. value before data for rich input", test_rich_input_gets_continuation_not_interrogation)

    cleanup()
    if FAILURES:
        print("\nFAILURES: %d" % len(FAILURES))
        for name, exc in FAILURES:
            print("  - %s: %s: %s" % (name, type(exc).__name__, exc))
        raise SystemExit(1)
    print("\nALL PASS")


if __name__ == "__main__":
    main()
