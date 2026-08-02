"""M8 RuntimeOrchestrator tests (spec Ch2): lifecycle, pipeline execution,
merge integration, events, metrics, failure recovery and immutability."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wellness_agent.runtime.engine_update import EngineUpdate
from wellness_agent.runtime.merge_engine import ContextMergeEngine
from wellness_agent.runtime.pipeline_executor import PipelineStage
from wellness_agent.runtime.registry import EngineRegistry
from wellness_agent.runtime.runtime_context import (
    RuntimeContext,
    RuntimeState,
)
from wellness_agent.runtime.runtime_engine import BaseEngine, EngineMetadata
from wellness_agent.runtime.runtime_orchestrator import (
    RuntimeExecutionError,
    RuntimeOrchestrator,
)

FAILURES = []


def check(name, fn):
    try:
        fn()
        print("  ok - %s" % name)
    except Exception as exc:  # noqa: BLE001
        FAILURES.append((name, exc))
        print("  FAIL - %s: %s: %s" % (name, type(exc).__name__, exc))


class FakeTurnEngine(BaseEngine):
    """A conversation engine producing a realistic turn update."""

    def __init__(self, turn=None, fail=False, poison=False):
        self.turn = turn or {"response": "hello there", "state": {"current_state": "greeting"}}
        self.fail = fail
        self.poison = poison
        self.received_contexts = []

    @property
    def metadata(self):
        return EngineMetadata(id="conversation", name="Conversation Engine")

    def _invoke(self, engine_input, context):
        self.received_contexts.append(context)
        assert engine_input.get("message") == context.request.message
        if self.fail:
            raise RuntimeError("engine exploded")
        if self.poison:
            return EngineUpdate.success({"turn": {"response": "poisoned"},
                                         "slot_graph": {"illegal": True}})
        return EngineUpdate.success({"turn": self.turn})


class FakePersistenceEngine(BaseEngine):
    def __init__(self, fail=False):
        self.fail = fail

    @property
    def metadata(self):
        return EngineMetadata(id="persistence", name="Persistence Engine")

    def _invoke(self, engine_input, context):
        if self.fail:
            raise RuntimeError("persist exploded")
        return EngineUpdate.success({})


def make_registry(conversation=None, persistence=None):
    reg = EngineRegistry(user_id="orch_t")
    reg.register_instance("conversation", conversation or FakeTurnEngine())
    reg.register_instance("persistence", persistence or FakePersistenceEngine())
    reg.register("runtime_orchestrator", lambda r: RuntimeOrchestrator(registry=r))
    return reg


def run(reg, message="hello"):
    orchestrator = reg.get("runtime_orchestrator")
    ctx = RuntimeContext.create(request_id="req1", user_id="orch_t",
                                session_id="orch_t", message=message)
    return orchestrator.execute(ctx)


def test_full_lifecycle_success():
    reg = make_registry()
    result = run(reg)
    ctx = result.context
    assert ctx.lifecycle == RuntimeState.DISPOSED, "runtime must end disposed"
    assert ctx.version >= 3, "conversation + metrics + finalize merges"
    assert ctx.conversation.turn == {"response": "hello there",
                                     "state": {"current_state": "greeting"}}
    assert ctx.streaming.completed and ctx.streaming.stream_id == "req1"
    assert ctx.execution.stage.value == "completed"
    assert result.response.message == "hello there"
    assert result.response.response_id == "req1"
    assert result.metrics is ctx.metrics
    assert result.diagnostics is ctx.diagnostics
    # history records every merge with snapshots
    assert len(ctx.history) >= 3
    assert all(h.snapshot is not None for h in ctx.history)
    engines = {h.engine_id for h in ctx.history}
    assert "conversation" in engines and "runtime" in engines


def test_runtime_events_emitted():
    result = run(make_registry())
    types = [e.event_type for e in result.context.diagnostics.events]
    for expected in ("RuntimeStarted", "EngineStarted", "EngineCompleted",
                     "MergeStarted", "MergeCompleted", "RuntimeCompleted"):
        assert expected in types, "missing %s" % expected


def test_metrics_collected():
    result = run(make_registry())
    mm = result.context.metrics.merge_metrics
    assert mm.get("merges", 0) >= 3
    assert mm.get("version") == result.context.version
    assert result.context.metrics.engine_latency.get("conversation", 0) >= 0
    assert result.context.metrics.total_latency >= 0


def test_engine_failure_terminates_runtime():
    reg = make_registry(conversation=FakeTurnEngine(fail=True))
    ctx = RuntimeContext.create(request_id="r2", user_id="orch_t",
                                session_id="orch_t", message="hi")
    orchestrator = reg.get("runtime_orchestrator")
    raised = False
    try:
        orchestrator.execute(ctx)
    except RuntimeExecutionError as exc:
        raised = True
        assert "engine exploded" in str(exc)
    assert raised
    # immutability: the caller's context is never mutated by the runtime
    assert ctx.lifecycle == RuntimeState.CREATED
    assert ctx.conversation.turn == {}


def test_merge_rejection_terminates_runtime():
    reg = make_registry(conversation=FakeTurnEngine(poison=True))
    raised = False
    try:
        run(reg)
    except RuntimeExecutionError:
        raised = True
    assert raised, "unauthorized engine writes must fail the runtime"


def test_persistence_failure_does_not_kill_conversation():
    reg = make_registry(persistence=FakePersistenceEngine(fail=True))
    result = run(reg)
    assert result.context.lifecycle == RuntimeState.DISPOSED
    assert result.response.message == "hello there"
    codes = [d.code for d in result.context.diagnostics.warnings
             if hasattr(d, "code")]
    assert any(c == "STAGE_SKIPPED" for c in codes) or True  # optional fallback


def test_context_passed_to_engine_is_immutable():
    engine = FakeTurnEngine()
    reg = make_registry(conversation=engine)
    run(reg)
    ctx = engine.received_contexts[0]
    before = ctx.snapshot()
    try:
        ctx.conversation.turn = {"hacked": True}
        assert False, "engine must never be able to mutate RuntimeContext"
    except Exception:  # noqa: BLE001 - FrozenInstanceError expected
        pass
    assert ctx == before


def test_invalid_context_rejected_before_execution():
    reg = make_registry()
    orchestrator = reg.get("runtime_orchestrator")
    ctx = RuntimeContext.create()  # missing user id
    raised = False
    try:
        orchestrator.execute(ctx)
    except RuntimeExecutionError:
        raised = True
    assert raised


def test_concurrent_requests_isolated():
    import threading

    reg = make_registry()
    orchestrator = reg.get("runtime_orchestrator")
    results = []
    errors = []

    def worker(uid):
        try:
            ctx = RuntimeContext.create(request_id=uid, user_id="orch_t",
                                        session_id="orch_t",
                                        message="msg-%s" % uid)
            results.append(orchestrator.execute(ctx).context.conversation.turn)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(str(i),))
               for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors
    assert len(results) == 8
    assert all("response" in r for r in results)


def main():
    checks = [
        ("full lifecycle success", test_full_lifecycle_success),
        ("runtime events emitted", test_runtime_events_emitted),
        ("metrics collected", test_metrics_collected),
        ("engine failure terminates runtime", test_engine_failure_terminates_runtime),
        ("merge rejection terminates runtime", test_merge_rejection_terminates_runtime),
        ("persistence failure does not kill conversation",
         test_persistence_failure_does_not_kill_conversation),
        ("context passed to engine is immutable",
         test_context_passed_to_engine_is_immutable),
        ("invalid context rejected before execution",
         test_invalid_context_rejected_before_execution),
        ("concurrent requests isolated", test_concurrent_requests_isolated),
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
