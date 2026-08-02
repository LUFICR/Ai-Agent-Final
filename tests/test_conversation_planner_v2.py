"""Conversation Planner V2 integration + unit tests.

Spec: docs/specifications/CONVERSATION_PLANNER_V2.md

Required scenarios:
1. capability question during investigation
2. casual chat mode
3. topic switching
4. recommendation acceptance
5. commitment creation
6. interruption recovery
7. loop prevention
8. mode transitions (valid + invalid, never back to DISCOVERY)
9. planner action selection (deterministic decision space)
10. conversation closure

Offline: GROQ_API_KEY is popped so rule-based fallbacks are exercised and
every assertion is deterministic.
"""

import os
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
    uid = "%s_v2_%d_%d" % (prefix, len(UIDS), int(time.time() * 1000))
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


def decision_of(turn):
    return (turn.get("planner_decision") or {}).get("action")


# ─── 1. capability question during investigation ─────────────────────

def test_capability_during_investigation():
    o = fresh_orch("cap")
    o.process_message("I am completely burned out from work")
    r = o.process_message("What can you help me with?")
    assert decision_of(r) == "answer_capability", r.get("planner_decision")
    assert "sleep" in r["response"].lower() and "stress" in r["response"].lower()
    mode = o.agents.planner.mode_state()
    assert mode["current_mode"] == "question_answering"
    assert mode["previous_mode"] == "discovery", mode
    # still in investigation on the state machine side (no coaching question asked)
    assert not r["response"].startswith(("Which", "On a scale"))


# ─── 2. casual chat mode ─────────────────────────────────────────────

def test_casual_chat_mode():
    o = fresh_orch("casual")
    o.process_message("I have been sleeping badly for weeks")
    o.process_message("I usually get around five hours a night")
    r = o.process_message("Tell me a joke")
    assert decision_of(r) == "casual_chat", r.get("planner_decision")
    assert o.agents.planner.mode_state()["current_mode"] == "casual_chat"
    # coaching suspended: no diagnostic questions while in casual chat
    r2 = o.process_message("Haha nice one")
    assert decision_of(r2) == "casual_chat", r2.get("planner_decision")
    assert not r2["response"].startswith(
        ("Which", "On a scale", "How long", "Does that", "When you")), r2["response"]
    # user introduces a coaching concern -> resume
    r3 = o.process_message("Anyway I still cant sleep at night")
    assert decision_of(r3) == "resume_topic", r3.get("planner_decision")
    assert o.agents.planner.mode_state()["current_mode"] == "investigation"


# ─── 3. topic switching ──────────────────────────────────────────────

def test_topic_switching():
    o = fresh_orch("switch")
    o.process_message("I am stressed out about my deadlines")
    r = o.process_message("Actually I want to talk about my sleep instead")
    assert decision_of(r) == "switch_topic", r.get("planner_decision")
    meta = r.get("planner_decision", {}).get("metadata", {})
    assert meta.get("target_topic") == "sleep", meta
    assert "sleep" in r["response"].lower()
    assert o.current_pillar == "sleep"


# ─── 4. recommendation acceptance ────────────────────────────────────

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


def test_recommendation_acceptance():
    o = fresh_orch("reco")
    _drive_to_recommendation(o)
    r = o.process_message("Sounds good, let's do it")
    assert decision_of(r) == "create_commitment", r.get("planner_decision")
    assert o.agents.planner.mode_state()["current_mode"] == "commitment"
    assert "commitment" in r["response"].lower() or "small" in r["response"].lower()
    # commitment question asks when, not a discovery restart
    assert "tomorrow" in r["response"].lower() or "time" in r["response"].lower()


# ─── 5. commitment creation -> scheduling -> closure ─────────────────

def test_commitment_creation():
    o = fresh_orch("commit")
    _drive_to_recommendation(o)
    r1 = o.process_message("Sounds good, let's do it")
    assert decision_of(r1) == "create_commitment"
    r2 = o.process_message("Yes, tomorrow morning")
    assert decision_of(r2) == "schedule_action", r2.get("planner_decision")
    assert o.agents.planner.mode_state()["current_mode"] == "commitment"
    r3 = o.process_message("Morning works")
    assert decision_of(r3) == "close_conversation", r3.get("planner_decision")
    assert o.agents.planner.mode_state()["current_mode"] == "closure"
    # no re-entering discovery after commitment
    assert o.agents.planner.mode_state()["previous_mode"] is None
    assert "plan" in r3["response"].lower()


# ─── 6. interruption recovery (previous mode resumes) ────────────────

def test_interruption_recovery():
    o = fresh_orch("inter")
    o.process_message("Work stress is crushing me lately")
    o.process_message("It started when my manager added more scope")
    r = o.process_message("What can you do?")
    assert decision_of(r) == "answer_capability"
    assert o.agents.planner.mode_state()["current_mode"] == "question_answering"
    r2 = o.process_message("Let's get back to my work stress")
    assert decision_of(r2) == "resume_topic", r2.get("planner_decision")
    assert o.agents.planner.mode_state()["current_mode"] == "investigation"
    assert "Back to what we were exploring" in r2["response"]


# ─── 7. loop prevention ──────────────────────────────────────────────

def test_loop_prevention_orchestrator():
    o = fresh_orch("loop")
    o.process_message("I am stressed about work")
    o.process_message("Work is constant pressure and deadlines")
    responses = []
    for _ in range(6):
        r = o.process_message("hmm")
        responses.append(r["response"])
        assert r["response"], "empty response"
    assert len(set(responses)) >= 3, "responses must vary, got: %r" % responses
    mode = o.agents.planner.current_mode()
    assert mode != ConversationMode.DISCOVERY, "must not return to discovery"


def test_loop_prevention_unit():
    p = ConversationPlanner()
    ctx = {"message": "I don't know", "intent_graph": {},
           "emotion": {}, "state": "deep_investigation",
           "route": ["question_planner"], "current_pillar": "work"}
    actions = [p.decide(dict(ctx)).action for _ in range(4)]
    # repeated non-progress turns must not repeat the asking action forever
    assert any(a != actions[0] for a in actions[1:]), actions
    assert any(a == PlannerAction.PROVIDE_INSIGHT for a in actions), actions


# ─── 8. mode transitions (valid/invalid) ─────────────────────────────

def test_mode_transitions():
    p = ConversationPlanner()
    ctx = {"message": "hi", "intent_graph": {}, "emotion": {},
           "state": "greeting", "route": []}
    d = p.decide(dict(ctx))
    assert p.current_mode() == ConversationMode.DISCOVERY
    # DISCOVERY -> INVESTIGATION (valid)
    ctx["state"] = "deep_investigation"
    ctx["route"] = ["question_planner"]
    ctx["current_pillar"] = "sleep"
    ctx["message"] = "I sleep badly"
    d = p.decide(dict(ctx))
    assert p.current_mode() == ConversationMode.INVESTIGATION
    # INVESTIGATION -> COACHING (valid)
    ctx["state"] = "routine_planning"
    ctx["route"] = ["routine_generator"]
    d = p.decide(dict(ctx))
    assert p.current_mode() == ConversationMode.COACHING
    assert d.action == PlannerAction.PROVIDE_RECOMMENDATION
    # COACHING -> DISCOVERY must be rejected: state bounces back, mode holds
    ctx["state"] = "guided_discovery"
    ctx["route"] = ["question_planner"]
    ctx["message"] = "Something else"
    p.decide(dict(ctx))
    assert p.current_mode() == ConversationMode.COACHING, \
        "must never regress to DISCOVERY after leaving it"
    # COACHING -> COMMITMENT (valid, via acceptance)
    p._pending_recommendation = True
    d = p.decide(dict(ctx))
    assert p.current_mode() == ConversationMode.COACHING
    ctx["message"] = "Sounds good"
    d = p.decide(dict(ctx))
    assert p.current_mode() == ConversationMode.COMMITMENT
    assert d.action == PlannerAction.CREATE_COMMITMENT
    # COMMITMENT -> CLOSURE (valid)
    ctx["message"] = "Tomorrow morning"
    d = p.decide(dict(ctx))
    ctx["message"] = "Morning works"
    d = p.decide(dict(ctx))
    assert p.current_mode() == ConversationMode.CLOSURE
    assert d.action == PlannerAction.CLOSE_CONVERSATION
    # CLOSURE holds: follow-up state cannot yank it back to discovery
    ctx["state"] = "follow_up"
    ctx["route"] = []
    p.decide(dict(ctx))
    assert p.current_mode() == ConversationMode.CLOSURE


# ─── 9. deterministic planner action selection ───────────────────────

def test_action_selection():
    base = {"intent_graph": {}, "emotion": {}, "state": "deep_investigation",
            "route": ["question_planner"], "current_pillar": "work"}
    cases = [
        ("What can you help me with?", PlannerAction.ANSWER_CAPABILITY),
        ("Tell me a joke", PlannerAction.CASUAL_CHAT),
        ("Why do I feel so tired?", PlannerAction.ANSWER_DIRECT_QUESTION),
        ("Let's talk about my sleep instead", PlannerAction.SWITCH_TOPIC),
        ("I want to quit my job, what do I do?", PlannerAction.ANSWER_DIRECT_QUESTION),
    ]
    for message, expected in cases:
        p = ConversationPlanner()
        ctx = dict(base, message=message)
        d = p.decide(ctx)
        assert d.action == expected, "message=%r -> %s (expected %s)" % (
            message, d.action, expected)
        assert d.reason and 0 < d.confidence <= 1.0
        assert isinstance(d.to_dict()["action"], str)
    # escalation always wins
    p = ConversationPlanner()
    ctx = dict(base, message="I keep thinking about harming myself",
               emotion={"risk_flag": True, "risk_reason": "self_harm"})
    d = p.decide(ctx)
    assert d.action == PlannerAction.ESCALATE
    assert p.current_mode() == ConversationMode.ESCALATION
    # no planner decision exists outside the action enum
    for a in (d.action, PlannerAction.WAIT, PlannerAction.REFLECT):
        assert a in PlannerAction


# ─── 10. conversation closure ────────────────────────────────────────

def test_conversation_closure():
    o = fresh_orch("close")
    _drive_to_recommendation(o)
    o.process_message("Sounds good, let's do it")
    o.process_message("Yes, tomorrow morning")
    r = o.process_message("Morning works")
    assert decision_of(r) == "close_conversation"
    assert o.agents.planner.mode_state()["current_mode"] == "closure"
    # a follow-up acknowledgment must not restart discovery
    r2 = o.process_message("Thanks, bye")
    assert decision_of(r2) in ("close_conversation", "clarify", "casual_chat"), \
        r2.get("planner_decision")
    assert o.agents.planner.current_mode() != ConversationMode.DISCOVERY


# ─── extras: direct answers, risk, backward compatibility ────────────

def test_direct_question_during_investigation():
    o = fresh_orch("direct")
    o.process_message("I have been sleeping only five hours for weeks")
    r = o.process_message("Why do I feel so tired all the time?")
    assert decision_of(r) == "answer_direct_question", r.get("planner_decision")
    assert len(r["response"]) > 20
    assert "?" not in r["response"] or "want" in r["response"].lower()


def test_risk_still_escalates_first():
    o = fresh_orch("risk")
    r = o.process_message("I keep thinking about killing myself")
    assert r["risk_detected"] is True
    assert (r.get("planner_decision") or {}).get("action") == "escalate"
    assert "988" in r["response"]


def test_backward_compat_select_target_pillar():
    p = ConversationPlanner()
    res = p.select_target_pillar(known_pillars={}, unknown_pillars=["sleep"],
                                 current_state="guided_discovery",
                                 latest_emotion_scores={},
                                 user_message="I feel stressed")
    assert res["target_pillar"] == "stress", res
    assert p.select_target_pillar(current_state="deep_investigation")["target_pillar"]


def test_planner_decision_key_present_on_every_turn():
    o = fresh_orch("keys")
    for msg in ["hi", "I am feeling anxious about everything", "yes"]:
        r = o.process_message(msg)
        assert "planner_decision" in r, "missing planner_decision on %r" % msg
        assert r["planner_decision"]["action"] in PlannerAction


def main():
    print("Conversation Planner V2 suite")
    check("1. capability question during investigation", test_capability_during_investigation)
    check("2. casual chat mode", test_casual_chat_mode)
    check("3. topic switching", test_topic_switching)
    check("4. recommendation acceptance", test_recommendation_acceptance)
    check("5. commitment creation -> scheduling -> closure", test_commitment_creation)
    check("6. interruption recovery", test_interruption_recovery)
    check("7a. loop prevention (orchestrator)", test_loop_prevention_orchestrator)
    check("7b. loop prevention (planner unit)", test_loop_prevention_unit)
    check("8. mode transitions (valid/invalid, never back to discovery)", test_mode_transitions)
    check("9. deterministic planner action selection", test_action_selection)
    check("10. conversation closure", test_conversation_closure)
    check("extra. direct question answered during investigation", test_direct_question_during_investigation)
    check("extra. risk still escalates first", test_risk_still_escalates_first)
    check("extra. backward-compat select_target_pillar", test_backward_compat_select_target_pillar)
    check("extra. planner_decision present every turn", test_planner_decision_key_present_on_every_turn)

    cleanup()
    if FAILURES:
        print("\nFAILURES: %d" % len(FAILURES))
        for name, exc in FAILURES:
            print("  - %s: %s: %s" % (name, type(exc).__name__, exc))
        raise SystemExit(1)
    print("\nALL PASS")


if __name__ == "__main__":
    main()
