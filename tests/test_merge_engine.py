"""M8 Merge Engine tests (spec Ch4): immutability, ownership, rollback,
history, snapshots, state machine, events and metrics."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wellness_agent.runtime.engine_update import EngineUpdate
from wellness_agent.runtime.merge_engine import (
    ContextMergeEngine,
    MergeError,
    MergeHistoryEntry,
)
from wellness_agent.runtime.runtime_context import (
    MetricsContext,
    RuntimeContext,
    RuntimeState,
    StreamingContext,
)

FAILURES = []


def check(name, fn):
    try:
        fn()
        print("  ok - %s" % name)
    except Exception as exc:  # noqa: BLE001
        FAILURES.append((name, exc))
        print("  FAIL - %s: %s: %s" % (name, type(exc).__name__, exc))


def make_context(uid="merge_t"):
    return RuntimeContext.create(request_id="r1", user_id=uid,
                                 session_id=uid, message="hello")


def test_merge_creates_new_immutable_version():
    engine = ContextMergeEngine()
    ctx = make_context()
    ctx = engine.transition(ctx, RuntimeState.VALIDATED)
    ctx = engine.transition(ctx, RuntimeState.EXECUTING)
    result = engine.merge(ctx, EngineUpdate.success({"turn": {"a": 1}}),
                          "conversation")
    assert result.ok, "merge must succeed"
    assert result.context is not ctx, "merge must produce a new context"
    assert result.context.version == ctx.version + 1
    assert result.context.conversation.turn == {"a": 1}
    assert ctx.conversation.turn == {}, "previous context must stay immutable"
    assert result.context.lifecycle == RuntimeState.EXECUTING
    assert result.summary.version == result.context.version
    assert result.summary.merge_latency_ms >= 0


def test_history_preserved_with_snapshots():
    engine = ContextMergeEngine()
    ctx = make_context()
    ctx = engine.transition(ctx, RuntimeState.VALIDATED)
    ctx = engine.transition(ctx, RuntimeState.EXECUTING)
    ctx = engine.merge(ctx, EngineUpdate.success({"turn": {"n": 1}}),
                       "conversation").context
    ctx = engine.merge(ctx, EngineUpdate.success({"turn": {"n": 2}}),
                       "conversation").context
    assert len(ctx.history) == 2
    first, second = ctx.history
    assert isinstance(first, MergeHistoryEntry)
    assert first.version == 1 and second.version == 2
    assert first.engine_id == "conversation"
    assert first.timestamp and first.update is not None
    assert first.snapshot is not None, "snapshot must be stored per merge"
    assert first.snapshot.conversation.turn == {"n": 1}
    assert first.snapshot.version == 1
    assert second.snapshot.conversation.turn == {"n": 2}


def test_ownership_conflict_rejected_with_rollback():
    engine = ContextMergeEngine()
    ctx = make_context()
    ctx = engine.transition(ctx, RuntimeState.VALIDATED)
    ctx = engine.transition(ctx, RuntimeState.EXECUTING)
    # knowledge engine tries to write a conversation-owned field
    result = engine.merge(ctx, EngineUpdate.success({"turn": {"x": 1}}),
                          "knowledge")
    assert not result.ok
    assert result.rolled_back
    assert result.context is not ctx
    assert result.context.conversation.turn == {}, "no partial state restored"
    assert result.context.version == ctx.version, "no version bump on rollback"
    assert result.context.lifecycle == RuntimeState.EXECUTING
    assert result.summary.conflicts_detected == 1
    assert result.summary.rollback_count == 1
    codes = [e.event_type for e in result.context.diagnostics.events]
    for expected in ("MergeStarted", "ConflictDetected", "MergeFailed",
                     "RollbackExecuted"):
        assert expected in codes, "missing event %s" % expected


def test_invalid_field_type_rejected():
    engine = ContextMergeEngine()
    ctx = make_context()
    ctx = engine.transition(ctx, RuntimeState.VALIDATED)
    ctx = engine.transition(ctx, RuntimeState.EXECUTING)
    result = engine.merge(ctx, EngineUpdate.success({"turn": "not a dict"}),
                          "conversation")
    assert not result.ok and result.rolled_back
    assert result.context.conversation.turn == {}


def test_runtime_owned_fields_merge():
    engine = ContextMergeEngine()
    ctx = make_context()
    ctx = engine.transition(ctx, RuntimeState.VALIDATED)
    ctx = engine.transition(ctx, RuntimeState.EXECUTING)
    stream = StreamingContext(stream_id="s1", completed=True)
    result = engine.merge(ctx, EngineUpdate.success({"streaming": stream}),
                          "runtime")
    assert result.ok
    assert result.context.streaming.stream_id == "s1"
    assert result.context.streaming.completed


def test_state_machine_transitions():
    engine = ContextMergeEngine()
    ctx = make_context()
    ctx = engine.transition(ctx, RuntimeState.VALIDATED)
    ctx = engine.transition(ctx, RuntimeState.EXECUTING)
    ctx = engine.transition(ctx, RuntimeState.STREAMING)
    ctx = engine.transition(ctx, RuntimeState.PERSISTING)
    ctx = engine.transition(ctx, RuntimeState.COMPLETED)
    ctx = engine.transition(ctx, RuntimeState.DISPOSED)
    assert ctx.lifecycle == RuntimeState.DISPOSED


def test_invalid_transitions_rejected():
    engine = ContextMergeEngine()
    ctx = make_context()
    for target in (RuntimeState.COMPLETED, RuntimeState.EXECUTING,
                   RuntimeState.DISPOSED):
        raised = False
        try:
            engine.transition(ctx, target)
        except MergeError:
            raised = True
        assert raised, "transition %s -> %s must be rejected" % (
            ctx.lifecycle.value, target.value)
    # valid path: created -> validated -> executing -> failed -> disposed
    ctx = engine.transition(ctx, RuntimeState.VALIDATED)
    ctx = engine.transition(ctx, RuntimeState.EXECUTING)
    ctx = engine.transition(ctx, RuntimeState.FAILED)
    ctx = engine.transition(ctx, RuntimeState.DISPOSED)
    assert ctx.lifecycle == RuntimeState.DISPOSED
    # forbidden: completed -> executing, disposed -> executing
    fresh = make_context()
    fresh = engine.transition(fresh, RuntimeState.VALIDATED)
    fresh = engine.transition(fresh, RuntimeState.EXECUTING)
    fresh = engine.transition(fresh, RuntimeState.STREAMING)
    fresh = engine.transition(fresh, RuntimeState.PERSISTING)
    fresh = engine.transition(fresh, RuntimeState.COMPLETED)
    for state in (fresh, engine.transition(fresh, RuntimeState.DISPOSED)):
        raised = False
        try:
            engine.transition(state, RuntimeState.EXECUTING)
        except MergeError:
            raised = True
        assert raised, "transition %s -> executing must be rejected" % (
            state.lifecycle.value)


def test_merges_rejected_in_terminal_states():
    engine = ContextMergeEngine()
    ctx = make_context()
    ctx = engine.transition(ctx, RuntimeState.VALIDATED)
    ctx = engine.transition(ctx, RuntimeState.EXECUTING)
    ctx = engine.transition(ctx, RuntimeState.STREAMING)
    ctx = engine.transition(ctx, RuntimeState.PERSISTING)
    ctx = engine.transition(ctx, RuntimeState.COMPLETED)
    for state in (ctx, engine.transition(ctx, RuntimeState.DISPOSED)):
        raised = False
        try:
            engine.merge(state, EngineUpdate.success({"turn": {}}),
                         "conversation")
        except MergeError:
            raised = True
        assert raised, "merges into %s must be rejected" % state.lifecycle.value


def test_merge_metrics_accumulate():
    engine = ContextMergeEngine()
    ctx = make_context()
    ctx = engine.transition(ctx, RuntimeState.VALIDATED)
    ctx = engine.transition(ctx, RuntimeState.EXECUTING)
    ctx = engine.merge(ctx, EngineUpdate.success({"turn": {"n": 1}}),
                       "conversation").context
    ctx = engine.merge(ctx, EngineUpdate.success({"turn": {"n": 2}}),
                       "conversation").context
    mm = ctx.metrics.merge_metrics
    assert mm["merges"] == 2
    assert mm["version"] == 2
    assert mm["merge_latency_ms"] >= 0
    assert mm.get("rollback_count", 0) == 0
    assert mm.get("conflicts_detected", 0) == 0


def test_engine_updates_never_mutate_context_directly():
    engine = ContextMergeEngine()
    ctx = make_context()
    ctx = engine.transition(ctx, RuntimeState.VALIDATED)
    ctx = engine.transition(ctx, RuntimeState.EXECUTING)
    before = ctx.snapshot()
    try:
        ctx.conversation.turn = {"hacked": True}
        assert False, "frozen context must reject mutation"
    except Exception:  # noqa: BLE001 - FrozenInstanceError expected
        pass
    assert ctx == before


def test_history_is_immutable():
    engine = ContextMergeEngine()
    ctx = make_context()
    ctx = engine.transition(ctx, RuntimeState.VALIDATED)
    ctx = engine.transition(ctx, RuntimeState.EXECUTING)
    ctx = engine.merge(ctx, EngineUpdate.success({"turn": {"n": 1}}),
                       "conversation").context
    # history tuple is immutable: no append / no entry field reassignment
    try:
        ctx.history[0].engine_id = "hacked"
        assert False, "history entries must be immutable"
    except Exception:  # noqa: BLE001 - FrozenInstanceError expected
        pass
    # snapshot must be a deep copy, not a live reference: mutating the live
    # turn data must never leak into stored snapshots
    ctx = engine.merge(ctx, EngineUpdate.success({"turn": {"n": 2}}),
                       "conversation").context
    assert ctx.history[0].snapshot.conversation.turn == {"n": 1}
    ctx.conversation.turn["hacked"] = True
    assert ctx.history[0].snapshot.conversation.turn == {"n": 1}, \
        "snapshot must not alias live context data"
    assert ctx.history[0].snapshot.version == 1
    assert ctx.history[1].snapshot.conversation.turn == {"n": 2}


def test_non_engine_update_rejected():
    engine = ContextMergeEngine()
    ctx = make_context()
    ctx = engine.transition(ctx, RuntimeState.VALIDATED)
    ctx = engine.transition(ctx, RuntimeState.EXECUTING)
    raised = False
    try:
        engine.merge(ctx, {"not": "an update"}, "conversation")
    except MergeError:
        raised = True
    assert raised


def main():
    checks = [
        ("merge creates new immutable version", test_merge_creates_new_immutable_version),
        ("history preserved with snapshots", test_history_preserved_with_snapshots),
        ("ownership conflict rejected with rollback", test_ownership_conflict_rejected_with_rollback),
        ("invalid field type rejected", test_invalid_field_type_rejected),
        ("runtime owned fields merge", test_runtime_owned_fields_merge),
        ("state machine transitions", test_state_machine_transitions),
        ("invalid transitions rejected", test_invalid_transitions_rejected),
        ("merges rejected in terminal states", test_merges_rejected_in_terminal_states),
        ("merge metrics accumulate", test_merge_metrics_accumulate),
        ("engines never mutate context directly", test_engine_updates_never_mutate_context_directly),
        ("history is immutable", test_history_is_immutable),
        ("non-engine update rejected", test_non_engine_update_rejected),
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
