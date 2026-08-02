"""Intent Resolver 2.0 unit tests (RFC-001 Ch2.5 acceptance criteria).

Covers: intent objects + confidence levels, IntentGraph structure,
multi-intent resolution, relationships, free-text-over-buttons answers,
branch continuity vs explicit topic change, corrections, interruptions,
emotional-vs-task separation, slot extraction, crisis override,
determinism and the EngineUpdate-only contract of IntentResolverEngine.
Offline: GROQ_API_KEY is popped so the rule-based fallback is exercised.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.pop("GROQ_API_KEY", None)

from wellness_agent.runtime.intent_resolver import (
    AMBIGUITY_GAP,
    INTENT_PRIORITIES,
    PRIMARY_THRESHOLD,
    Intent,
    IntentGraph,
    IntentRelationship,
    IntentResolverEngine,
    resolve_intents,
)
from wellness_agent.runtime.runtime_context import RuntimeContext

FAILURES = []


def check(name, fn):
    try:
        fn()
        print("  ok - %s" % name)
    except Exception as exc:  # noqa: BLE001
        FAILURES.append((name, exc))
        print("  FAIL - %s: %s: %s" % (name, type(exc).__name__, exc))


def primary_of(graph):
    return graph.primary_intent


def intents_of(graph, level="secondary"):
    return list(getattr(graph, "%s_intents" % level))


# ─── Intent object & confidence levels (RFC-001 Ch2.2) ────────────────


def test_confidence_levels_follow_rfc_bands():
    high = resolve_intents("I keep thinking about killing myself")
    assert high.primary_intent.confidence >= 0.80, "crisis is high confidence"
    medium = resolve_intents("I have been sleeping five hours for two weeks")
    assert 0.60 <= medium.primary_intent.confidence < 0.80
    low = resolve_intents("I dont know")
    assert 0.40 <= low.primary_intent.confidence < 0.60, "deflection is low"
    unknown = resolve_intents("")
    assert unknown.primary_intent.confidence < 0.40, "empty is unknown"


def test_intent_object_has_reasoning_metadata():
    graph = resolve_intents("I have been sleeping five hours")
    intent = graph.primary_intent
    assert isinstance(intent, Intent)
    assert intent.confidence > 0
    assert intent.evidence, "evidence must explain the signal"
    assert intent.priority == INTENT_PRIORITIES[intent.intent]
    d = intent.to_dict()
    for key in ("intent", "confidence", "priority", "level", "notes",
                "evidence"):
        assert key in d, "to_dict must carry %s" % key


def test_graph_structure_matches_rfc():
    graph = resolve_intents("I am exhausted because work has been stressful")
    d = graph.to_dict()
    for key in ("primary_intent", "secondary_intents", "background_intents",
                "relationships", "overall_confidence"):
        assert key in d, "graph must carry %s" % key
    assert isinstance(graph, IntentGraph)
    assert graph.overall_confidence >= 0.5


# ─── Multi-intent & relationships (RFC-001 Ch2.3) ─────────────────────


def test_cause_clause_ranks_leading_effect_over_cause():
    graph = resolve_intents("I am exhausted because work has been stressful")
    primary = primary_of(graph)
    assert primary.intent == "additional_information", primary
    assert "energy" in primary.notes, "leading clause ('exhausted') is primary"
    assert any("work" in i.notes for i in intents_of(graph)), \
        "trail clause (work stress) stays secondary"


def test_cause_relationship_emitted():
    graph = resolve_intents("I am exhausted because work has been stressful")
    types = [r.type for r in graph.relationships]
    assert "cause" in types
    rel = [r for r in graph.relationships if r.type == "cause"][0]
    assert isinstance(rel, IntentRelationship)
    assert rel.target == "emotion"


def test_multi_intent_message_keeps_commitment_secondary():
    graph = resolve_intents(
        "I am exhausted because work has been stressful and "
        "I promised myself I would exercise")
    kinds = [i.intent for i in intents_of(graph)]
    assert "commitment" in kinds, "commitment survives as secondary"


def test_multi_intent_l2_emotional_plus_sleep():
    graph = resolve_intents(
        "I am anxious, I cant sleep and my relationship is falling apart")
    assert primary_of(graph).intent == "additional_information"
    emotions = [i for i in intents_of(graph)
                if i.intent == "emotional_expression"]
    assert any("anxious" in e.notes for e in emotions)


def test_reinforcement_relationship_between_emotions():
    graph = resolve_intents("I have been exhausted all week")
    types = [r.type for r in graph.relationships]
    assert "reinforcement" in types, "stressed+tired reinforce"


def test_conflict_relationship_on_memory_contradiction():
    graph = resolve_intents(
        "I actually sleep seven hours now",
        memory_facts=[{"key": "sleep_hours", "value": "5 hours"}])
    assert graph.correction is True
    assert primary_of(graph).intent == "correction", \
        "correction overrides the new topic"
    assert any(r.type == "conflict" for r in graph.relationships)


# ─── Free text over buttons / answers (RFC-001 Ch2.5) ─────────────────


def test_answer_to_pending_question_with_slot():
    graph = resolve_intents(
        "About five", previous_question="How many hours do you sleep?")
    assert graph.answered_current_question is True
    assert primary_of(graph).intent == "answer"
    slots = list(graph.new_slots_detected)
    assert any(s["slot"] == "sleep_hours" for s in slots), slots


def test_open_answer_with_topic_context():
    graph = resolve_intents(
        "My job has been overwhelming", previous_question="What concerns you?")
    assert graph.answered_current_question is True
    assert primary_of(graph).intent == "answer"


def test_slot_extraction_multiple_slots():
    graph = resolve_intents("I have been sleeping five hours for two weeks")
    slots = {s["slot"] for s in graph.new_slots_detected}
    assert "sleep_hours" in slots
    assert "duration" in slots


def test_volunteered_information_not_answer():
    graph = resolve_intents("I have been exhausted all week")
    assert primary_of(graph).intent == "additional_information"
    assert graph.answered_current_question is False


# ─── Branch continuity vs topic change (RFC-001 Ch2.2 Intent 7) ───────


def test_explicit_topic_change_requests_branch_switch():
    graph = resolve_intents("I actually want to talk about work",
                            active_branch="sleep")
    assert primary_of(graph).intent == "topic_change"
    assert graph.branch_change_requested is True
    assert graph.continue_branch is False
    assert graph.topic_shift is True
    assert graph.correction is False, \
        "'actually' inside a topic change is not a correction"


def test_forget_topic_change():
    graph = resolve_intents("Forget stress. Lets discuss relationships",
                            active_branch="stress")
    assert primary_of(graph).intent == "topic_change"
    assert graph.branch_change_requested is True


def test_additive_topic_continues_branch():
    graph = resolve_intents("My work has also been stressful",
                            active_branch="energy")
    assert primary_of(graph).intent == "additional_information"
    assert graph.continue_branch is True
    assert graph.branch_change_requested is False
    assert graph.topic_shift is False


def test_family_topic_continues_branch():
    graph = resolve_intents("I am also sleeping badly", active_branch="burnout")
    assert primary_of(graph).intent == "additional_information"
    assert graph.continue_branch is True, "sleep belongs to burnout family"


# ─── Corrections (RFC-001 Ch2.2 Intent 4) ─────────────────────────────


def test_correction_requires_memory_contradiction_or_marker():
    with_memory = resolve_intents(
        "I actually sleep seven hours now",
        memory_facts=[{"key": "sleep_hours", "value": "5 hours"}])
    assert with_memory.correction is True
    without_memory = resolve_intents("I actually sleep seven hours now")
    assert primary_of(without_memory).intent == "additional_information", \
        "marker without contradiction stays informational"


def test_same_value_is_not_a_correction():
    graph = resolve_intents(
        "I am still sleeping five hours",
        memory_facts=[{"key": "sleep_hours", "value": "5 hours"}])
    assert graph.correction is False


# ─── Interruptions (RFC-001 Ch2.1) ────────────────────────────────────


def test_non_answer_to_pending_question_is_interruption():
    graph = resolve_intents("I cant focus at work",
                            previous_question="How many hours do you sleep?")
    assert graph.interruption is True
    assert graph.answered_current_question is False


# ─── Emotional vs task intent separation (RFC-001 Ch2.2 Intent 8) ─────


def test_emotion_is_secondary_to_task_intent():
    graph = resolve_intents("I have been exhausted all week")
    assert primary_of(graph).intent == "additional_information"
    kinds = {i.intent for i in intents_of(graph)}
    assert "emotional_expression" in kinds


def test_pure_emotion_message_is_low_confidence_and_clarifies():
    graph = resolve_intents("Im exhausted")
    assert graph.requires_clarification is True
    assert primary_of(graph).intent == "additional_information"
    kinds = {i.intent for i in intents_of(graph)}
    assert "emotional_expression" in kinds


def test_negated_emotion_is_not_detected():
    graph = resolve_intents("I am not stressed")
    assert primary_of(graph).intent == "unknown", "negation kills the emotion"


# ─── Crisis override (RFC-001 Ch2.2 Intent 1) ─────────────────────────


def test_crisis_overrides_everything():
    graph = resolve_intents("I keep thinking about killing myself")
    assert primary_of(graph).intent == "crisis"
    assert graph.branch_change_requested is True
    assert graph.continue_branch is False
    assert graph.requires_clarification is False


# ─── Questions & deflections ──────────────────────────────────────────


def test_question_intent():
    graph = resolve_intents("Why am I always tired?")
    assert primary_of(graph).intent == "question"
    assert graph.requires_clarification is False


def test_deflection_is_unknown_with_clarification():
    for msg in ("I dont know", "...", "hmm"):
        graph = resolve_intents(msg)
        assert primary_of(graph).intent == "unknown", msg
        assert graph.requires_clarification is True


def test_greeting_and_goodbye():
    assert primary_of(resolve_intents("hi")).intent == "greeting"
    assert primary_of(resolve_intents("bye")).intent == "goodbye"


# ─── Commitment & idioms ──────────────────────────────────────────────


def test_commitment_detected():
    graph = resolve_intents("I will try sleeping earlier")
    assert primary_of(graph).intent == "commitment"


def test_idiom_is_not_a_commitment():
    graph = resolve_intents("I will sleep on it")
    assert primary_of(graph).intent != "commitment"


# ─── Determinism & contracts ──────────────────────────────────────────


def test_deterministic_same_input_same_graph():
    msg = "I have been sleeping five hours for two weeks"
    g1 = resolve_intents(msg)
    g2 = resolve_intents(msg)
    assert g1.to_dict() == g2.to_dict()


def test_engine_returns_engineupdate_and_never_mutates_context():
    engine = IntentResolverEngine()
    ctx = RuntimeContext.create(request_id="r1", user_id="rt_m8_ir_user",
                                session_id="rt_m8_ir_user",
                                message="I am exhausted")
    update = engine.execute({"message": "I am exhausted"}, ctx)
    assert update.success
    assert "intent_graph" in update.data
    assert ctx.conversation.intent_graph == {}, \
        "engine must not write to the context directly"
    assert any(d.code == "IntentGraphBuilt" for d in update.diagnostics)


def test_ambiguous_diagnostic_on_clarification():
    engine = IntentResolverEngine()
    ctx = RuntimeContext.create(request_id="r1", user_id="rt_m8_ir_user",
                                session_id="rt_m8_ir_user",
                                message="...")
    update = engine.execute({"message": "..."}, ctx)
    codes = {d.code for d in update.diagnostics}
    assert "IntentAmbiguous" in codes


def test_metadata_and_version():
    engine = IntentResolverEngine()
    assert engine.id == "intent_resolver"
    assert engine.metadata.version == "2.0.0"
    assert engine.timeout_ms == 5000


def test_confidence_constant_sanity():
    assert PRIMARY_THRESHOLD == 0.60
    assert AMBIGUITY_GAP == 0.10


def main():
    print("Intent Resolver 2.0 unit tests (RFC-001 Ch2.5)")
    print("-" * 60)
    checks = [
        ("confidence levels follow RFC bands",
         test_confidence_levels_follow_rfc_bands),
        ("intent object has reasoning metadata",
         test_intent_object_has_reasoning_metadata),
        ("graph structure matches RFC", test_graph_structure_matches_rfc),
        ("cause clause ranks leading effect over cause",
         test_cause_clause_ranks_leading_effect_over_cause),
        ("cause relationship emitted", test_cause_relationship_emitted),
        ("multi-intent keeps commitment secondary",
         test_multi_intent_message_keeps_commitment_secondary),
        ("multi-intent L2 emotional plus sleep",
         test_multi_intent_l2_emotional_plus_sleep),
        ("reinforcement relationship between emotions",
         test_reinforcement_relationship_between_emotions),
        ("conflict relationship on memory contradiction",
         test_conflict_relationship_on_memory_contradiction),
        ("answer to pending question with slot",
         test_answer_to_pending_question_with_slot),
        ("open answer with topic context", test_open_answer_with_topic_context),
        ("slot extraction multiple slots", test_slot_extraction_multiple_slots),
        ("volunteered information not answer",
         test_volunteered_information_not_answer),
        ("explicit topic change requests branch switch",
         test_explicit_topic_change_requests_branch_switch),
        ("forget topic change", test_forget_topic_change),
        ("additive topic continues branch", test_additive_topic_continues_branch),
        ("family topic continues branch", test_family_topic_continues_branch),
        ("correction requires memory contradiction or marker",
         test_correction_requires_memory_contradiction_or_marker),
        ("same value is not a correction", test_same_value_is_not_a_correction),
        ("non-answer to pending question is interruption",
         test_non_answer_to_pending_question_is_interruption),
        ("emotion is secondary to task intent",
         test_emotion_is_secondary_to_task_intent),
        ("pure emotion message is low confidence and clarifies",
         test_pure_emotion_message_is_low_confidence_and_clarifies),
        ("negated emotion is not detected", test_negated_emotion_is_not_detected),
        ("crisis overrides everything", test_crisis_overrides_everything),
        ("question intent", test_question_intent),
        ("deflection is unknown with clarification",
         test_deflection_is_unknown_with_clarification),
        ("greeting and goodbye", test_greeting_and_goodbye),
        ("commitment detected", test_commitment_detected),
        ("idiom is not a commitment", test_idiom_is_not_a_commitment),
        ("deterministic same input same graph",
         test_deterministic_same_input_same_graph),
        ("engine returns EngineUpdate and never mutates context",
         test_engine_returns_engineupdate_and_never_mutates_context),
        ("ambiguous diagnostic on clarification",
         test_ambiguous_diagnostic_on_clarification),
        ("metadata and version", test_metadata_and_version),
        ("confidence constant sanity", test_confidence_constant_sanity),
    ]
    for name, fn in checks:
        check(name, fn)
    print("-" * 60)
    if FAILURES:
        print("FAILED: %d of %d" % (len(FAILURES), len(checks)))
        sys.exit(1)
    print("OK: all %d tests passed" % len(checks))


if __name__ == "__main__":
    main()
