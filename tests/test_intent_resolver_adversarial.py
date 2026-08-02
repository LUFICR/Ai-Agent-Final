"""Intent Resolver 2.0 adversarial tests.

Attacks: negations, idioms, substring traps, short deflections, empty and
noisy messages, ambiguous near-equal pairs, cause/negation clause
interaction, memory contradictions, determinism under repetition, and
context immutability (the engine returns EngineUpdate only).
Offline: GROQ_API_KEY is popped so the rule-based fallback is exercised.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.pop("GROQ_API_KEY", None)

from wellness_agent.runtime.intent_resolver import resolve_intents
from wellness_agent.runtime.runtime_context import (
    RuntimeContext,
    RuntimeState,
)
from wellness_agent.runtime.merge_engine import ContextMergeEngine
from wellness_agent.runtime.engine_update import EngineUpdate
from wellness_agent.runtime.intent_resolver import IntentResolverEngine

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


def kinds_of(graph):
    return [i.intent for i in graph.secondary_intents]


# ─── Negation attacks ─────────────────────────────────────────────────


def test_negation_kills_emotion():
    for msg in ("I am not stressed", "I am not tired at all",
                "I am never anxious", "I am not sad, just tired"):
        graph = resolve_intents(msg)
        if "tired" in msg and "not sad, just tired" in msg:
            assert primary_of(graph).intent == "emotional_expression", msg
            continue
        assert primary_of(graph).intent == "unknown", msg


def test_negation_does_not_leak_into_following_clause():
    graph = resolve_intents("I am not stressed but my sleep is broken")
    assert primary_of(graph).intent == "additional_information"
    assert "sleep" in primary_of(graph).notes


def test_negated_topic_with_positive_topic():
    graph = resolve_intents("Work is not stressful but I sleep badly")
    assert primary_of(graph).intent == "additional_information"
    assert "sleep" in primary_of(graph).notes


# ─── Idiom / phrase attacks ───────────────────────────────────────────


def test_sleep_on_it_is_not_a_commitment():
    graph = resolve_intents("I will sleep on it")
    assert primary_of(graph).intent != "commitment"
    assert primary_of(graph).intent != "answer"


def test_ill_is_not_a_substring_topic():
    graph = resolve_intents("I feel ill today")
    assert primary_of(graph).intent in ("unknown", "additional_information")


def test_stress_does_not_match_inside_other_words():
    graph = resolve_intents("I am not stressing anymore")
    assert primary_of(graph).intent == "unknown", "boundary aware negation"


# ─── Short / empty / noisy messages ───────────────────────────────────


def test_empty_and_whitespace_messages_do_not_crash():
    for msg in ("", "   ", "\n", "!!!"):
        graph = resolve_intents(msg)
        assert primary_of(graph).intent == "unknown", repr(msg)


def test_bare_deflection_words():
    for msg in ("maybe", "whatever", "idk", "i dont know", "not sure", "nah"):
        graph = resolve_intents(msg)
        assert primary_of(graph).intent == "unknown", msg
        assert graph.requires_clarification is True, msg


def test_bare_confirmations_are_confirmations():
    for msg in ("ok", "ok", "yes", "yep", "yeah", "sure"):
        graph = resolve_intents(msg)
        assert primary_of(graph).intent == "confirmation", msg
        assert graph.requires_clarification is False, msg


def test_bare_okay_fine_are_ambiguous_and_clarify():
    for msg in ("okay", "fine"):
        graph = resolve_intents(msg)
        assert graph.requires_clarification is True, msg


# ─── Ambiguity ────────────────────────────────────────────────────────


def test_ambiguous_short_message_clarifies():
    graph = resolve_intents("I am tired")
    assert graph.requires_clarification is True
    assert graph.primary_intent.confidence < 0.80


def test_strong_signal_is_not_ambiguous():
    graph = resolve_intents("I have been sleeping five hours for two weeks")
    assert graph.requires_clarification is False


# ─── Corrections & memory ─────────────────────────────────────────────


def test_memory_contradiction_with_word_numbers():
    graph = resolve_intents(
        "Actually I sleep seven hours now",
        memory_facts=[{"key": "sleep_hours", "value": "five hours"}])
    assert graph.correction is True
    assert any(r.type == "conflict" for r in graph.relationships)


def test_contradiction_across_fact_value_format():
    graph = resolve_intents(
        "I actually sleep 8 hours now",
        memory_facts=[{"key": "sleep_hours", "value": "5"}])
    assert graph.correction is True


def test_no_correction_without_contradiction():
    graph = resolve_intents(
        "I am still sleeping five hours",
        memory_facts=[{"key": "sleep_hours", "value": "5 hours"}])
    assert graph.correction is False


# ─── Interruption & answers ───────────────────────────────────────────


def test_answer_beats_interruption():
    graph = resolve_intents("About five",
                            previous_question="How many hours do you sleep?")
    assert graph.answered_current_question is True
    assert graph.interruption is False


def test_interruption_not_answered():
    graph = resolve_intents("I cant focus at work",
                            previous_question="How many hours do you sleep?")
    assert graph.interruption is True
    assert graph.answered_current_question is False


# ─── Engine contract: EngineUpdate only, context frozen ───────────────


def test_engine_never_mutates_runtime_context():
    engine = IntentResolverEngine()
    merge = ContextMergeEngine()
    ctx = RuntimeContext.create(request_id="r1", user_id="rt_m8_adv_user",
                                session_id="rt_m8_adv_user",
                                message="I am exhausted")
    ctx = merge.transition(ctx, RuntimeState.VALIDATED)
    ctx = merge.transition(ctx, RuntimeState.EXECUTING)
    before = ctx.conversation.intent_graph
    update = engine.execute({"message": "I am exhausted"}, ctx)
    assert ctx.conversation.intent_graph == before, "context must stay frozen"
    assert update.success
    assert isinstance(update, EngineUpdate)


def test_engine_update_merges_cleanly():
    engine = IntentResolverEngine()
    merge = ContextMergeEngine()
    ctx = RuntimeContext.create(request_id="r1", user_id="rt_m8_adv_user",
                                session_id="rt_m8_adv_user",
                                message="I am exhausted")
    ctx = merge.transition(ctx, RuntimeState.VALIDATED)
    ctx = merge.transition(ctx, RuntimeState.EXECUTING)
    update = engine.execute({"message": "I am exhausted"}, ctx)
    result = merge.merge(ctx, update, "intent_resolver")
    assert result.ok
    assert result.context.conversation.intent_graph.get("primary_intent")
    assert ctx.conversation.intent_graph == {}, "previous context immutable"


# ─── Determinism & stability ──────────────────────────────────────────


def test_repeated_calls_identical():
    msg = "I am anxious, I cant sleep and my relationship is falling apart"
    first = resolve_intents(msg).to_dict()
    for _ in range(20):
        assert resolve_intents(msg).to_dict() == first


def test_case_and_whitespace_insensitive():
    a = resolve_intents("I AM SLEEPING FIVE HOURS")
    b = resolve_intents("   i am sleeping five hours   ")
    assert a.primary_intent.intent == b.primary_intent.intent
    assert a.primary_intent.confidence == b.primary_intent.confidence


def test_punctuation_only_variants():
    for msg in ("...", "??", "ok...", "hmm."):
        graph = resolve_intents(msg)
        assert primary_of(graph).intent == "unknown", msg


def test_crisis_not_triggered_by_safe_phrases():
    for msg in ("I am sick of this", "I wish I could sleep",
                "I am dead tired"):
        graph = resolve_intents(msg)
        assert primary_of(graph).intent != "crisis", msg


def test_topic_change_not_triggered_by_casual_mention():
    graph = resolve_intents("At work they ask about my sleep",
                            active_branch="sleep")
    assert primary_of(graph).intent == "additional_information"
    assert graph.branch_change_requested is False


def main():
    print("Intent Resolver 2.0 adversarial tests")
    print("-" * 60)
    checks = [
        ("negation kills emotion", test_negation_kills_emotion),
        ("negation does not leak into following clause",
         test_negation_does_not_leak_into_following_clause),
        ("negated topic with positive topic",
         test_negated_topic_with_positive_topic),
        ("sleep on it is not a commitment", test_sleep_on_it_is_not_a_commitment),
        ("ill is not a substring topic", test_ill_is_not_a_substring_topic),
        ("stress does not match inside other words",
         test_stress_does_not_match_inside_other_words),
        ("empty and whitespace messages do not crash",
         test_empty_and_whitespace_messages_do_not_crash),
        ("bare deflection words", test_bare_deflection_words),
        ("bare confirmations are confirmations",
         test_bare_confirmations_are_confirmations),
        ("bare okay/fine are ambiguous and clarify",
         test_bare_okay_fine_are_ambiguous_and_clarify),
        ("ambiguous short message clarifies",
         test_ambiguous_short_message_clarifies),
        ("strong signal is not ambiguous", test_strong_signal_is_not_ambiguous),
        ("memory contradiction with word numbers",
         test_memory_contradiction_with_word_numbers),
        ("contradiction across fact value format",
         test_contradiction_across_fact_value_format),
        ("no correction without contradiction",
         test_no_correction_without_contradiction),
        ("answer beats interruption", test_answer_beats_interruption),
        ("interruption not answered", test_interruption_not_answered),
        ("engine never mutates runtime context",
         test_engine_never_mutates_runtime_context),
        ("engine update merges cleanly", test_engine_update_merges_cleanly),
        ("repeated calls identical", test_repeated_calls_identical),
        ("case and whitespace insensitive",
         test_case_and_whitespace_insensitive),
        ("punctuation only variants", test_punctuation_only_variants),
        ("crisis not triggered by safe phrases",
         test_crisis_not_triggered_by_safe_phrases),
        ("topic change not triggered by casual mention",
         test_topic_change_not_triggered_by_casual_mention),
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
