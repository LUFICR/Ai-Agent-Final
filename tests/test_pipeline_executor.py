"""M8 PipelineExecutor tests (spec Ch3): deterministic order, registry-only
resolution, retries, timeouts, optional fallback, hooks and stage results."""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wellness_agent.runtime.engine_result import EngineResult
from wellness_agent.runtime.engine_update import EngineUpdate
from wellness_agent.runtime.pipeline_executor import (
    PipelineError,
    PipelineExecutor,
    PipelineStage,
)
from wellness_agent.runtime.registry import EngineRegistry
from wellness_agent.runtime.runtime_context import RuntimeContext
from wellness_agent.runtime.runtime_engine import BaseEngine, EngineMetadata, RetryPolicy

FAILURES = []


def check(name, fn):
    try:
        fn()
        print("  ok - %s" % name)
    except Exception as exc:  # noqa: BLE001
        FAILURES.append((name, exc))
        print("  FAIL - %s: %s: %s" % (name, type(exc).__name__, exc))


class MockEngine(BaseEngine):
    def __init__(self, engine_id, result=EngineResult.SUCCESS, data=None,
                 delay=0.0, fail_times=0):
        self._id = engine_id
        self._result = result
        self._data = data or {}
        self._delay = delay
        self._fail_times = fail_times
        self.calls = 0
        self.received_inputs = []

    @property
    def metadata(self):
        return EngineMetadata(id=self._id, name=self._id)

    def _invoke(self, engine_input, context):
        self.calls += 1
        self.received_inputs.append(engine_input)
        if self._delay:
            time.sleep(self._delay)
        if self.calls <= self._fail_times or self._result == EngineResult.FAILED:
            return EngineUpdate.failed(
                diagnostics=[__import__("wellness_agent.runtime.diagnostics",
                                        fromlist=["Diagnostic"]).Diagnostic(
                    level="error", code="MOCK_FAIL", engine=self._id,
                    message="mock failure %d" % self.calls)])
        return EngineUpdate.success(self._data)


def make_context():
    return RuntimeContext.create(request_id="r1", user_id="u",
                                 session_id="u", message="hi")


def make_registry(engines):
    reg = EngineRegistry(user_id="pipe_t")
    for engine in engines:
        reg.register_instance(engine.id, engine)
    return reg


def test_stages_execute_in_order():
    order = []
    a = MockEngine("a", data={"step": "a"})
    b = MockEngine("b", data={"step": "b"})
    a._invoke = lambda i, c: (order.append("a"),
                              EngineUpdate.success({"step": "a"}))[1]
    b._invoke = lambda i, c: (order.append("b"),
                              EngineUpdate.success({"step": "b"}))[1]
    reg = make_registry([a, b])
    executor = PipelineExecutor(reg, [
        PipelineStage(id="s1", engine_id="a"),
        PipelineStage(id="s2", engine_id="b"),
    ])
    results = executor.execute({}, make_context())
    assert order == ["a", "b"], "stages must run in declared order"
    assert [r.stage_id for r in results] == ["s1", "s2"]
    assert all(r.status == EngineResult.SUCCESS for r in results)
    assert results[0].latency_ms >= 0


def test_input_builder_used_per_stage():
    captured = {}
    a = MockEngine("a")
    a._invoke = lambda i, c: (captured.update(i),
                              EngineUpdate.success({}))[1]
    reg = make_registry([a])
    executor = PipelineExecutor(reg, [
        PipelineStage(id="s1", engine_id="a",
                      input_builder=lambda ctx: {"built": ctx.request.message}),
    ])
    executor.execute({}, make_context())
    assert captured.get("built") == "hi", "input_builder must provide stage input"


def test_unknown_engine_raises():
    reg = EngineRegistry(user_id="pipe_t")
    executor = PipelineExecutor(reg, [
        PipelineStage(id="s1", engine_id="missing"),
    ])
    raised = False
    try:
        executor.execute({}, make_context())
    except PipelineError:
        raised = True
    assert raised


def test_required_failure_terminates_pipeline():
    reg = make_registry([MockEngine("a", result=EngineResult.FAILED)])
    executor = PipelineExecutor(reg, [
        PipelineStage(id="s1", engine_id="a"),
    ])
    raised = False
    try:
        executor.execute({}, make_context())
    except PipelineError:
        raised = True
    assert raised


def test_optional_failure_skipped_and_continues():
    a = MockEngine("a", result=EngineResult.FAILED)
    b = MockEngine("b")
    reg = make_registry([a, b])
    executor = PipelineExecutor(reg, [
        PipelineStage(id="s1", engine_id="a", optional=True),
        PipelineStage(id="s2", engine_id="b"),
    ])
    results = executor.execute({}, make_context())
    assert results[0].status == EngineResult.SKIPPED
    assert results[1].status == EngineResult.SUCCESS
    assert b.calls == 1, "pipeline must continue after optional skip"


def test_retry_policy_retries_then_succeeds():
    engine = MockEngine("a", fail_times=2)
    reg = make_registry([engine])
    executor = PipelineExecutor(reg, [
        PipelineStage(id="s1", engine_id="a",
                      retry_policy=RetryPolicy(enabled=True, max_retries=3)),
    ])
    results = executor.execute({}, make_context())
    assert engine.calls == 3, "engine must be retried per policy"
    assert results[0].status == EngineResult.SUCCESS
    assert results[0].update.metrics.retry_count == 2


def test_retry_policy_exhausted_fails_required_stage():
    engine = MockEngine("a", fail_times=99)
    reg = make_registry([engine])
    executor = PipelineExecutor(reg, [
        PipelineStage(id="s1", engine_id="a",
                      retry_policy=RetryPolicy(enabled=True, max_retries=2)),
    ])
    raised = False
    try:
        executor.execute({}, make_context())
    except PipelineError:
        raised = True
    assert raised
    assert engine.calls == 3, "1 attempt + 2 retries"


def test_timeout_enforced():
    engine = MockEngine("a", delay=0.05)
    reg = make_registry([engine])
    executor = PipelineExecutor(reg, [
        PipelineStage(id="s1", engine_id="a", timeout_ms=5, optional=True),
    ])
    results = executor.execute({}, make_context())
    assert results[0].status == EngineResult.SKIPPED, \
        "optional timed-out stage must fall back to skipped"
    codes = [d.code for d in results[0].update.diagnostics]
    assert "ENGINE_TIMEOUT" in codes
    assert "STAGE_SKIPPED" in codes


def test_disabled_stage_skipped():
    a = MockEngine("a")
    reg = make_registry([a])
    executor = PipelineExecutor(reg, [
        PipelineStage(id="s1", engine_id="a", enabled=False),
    ])
    results = executor.execute({}, make_context())
    assert results == [] and a.calls == 0


def test_pipeline_hooks_emitted():
    events = []
    a = MockEngine("a")
    b = MockEngine("b", result=EngineResult.FAILED)
    reg = make_registry([a, b])
    executor = PipelineExecutor(
        reg, [
            PipelineStage(id="s1", engine_id="a"),
            PipelineStage(id="s2", engine_id="b", optional=True),
        ],
        on_event=lambda event: events.append(event.event_type))
    executor.execute({}, make_context())
    types = events
    assert "PipelineStarted" in types
    assert "EngineStarted" in types and "EngineCompleted" in types
    assert "EngineFailed" in types
    assert "StageCompleted" in types
    assert "PipelineCompleted" in types


def test_failed_pipeline_emits_pipeline_failed():
    events = []
    reg = make_registry([MockEngine("a", result=EngineResult.FAILED)])
    executor = PipelineExecutor(
        reg, [PipelineStage(id="s1", engine_id="a")],
        on_event=lambda event: events.append(event.event_type))
    raised = False
    try:
        executor.execute({}, make_context())
    except PipelineError:
        raised = True
    assert raised
    assert "PipelineFailed" in events


def test_engines_resolved_only_through_registry():
    engine = MockEngine("a")
    reg = make_registry([engine])
    executor = PipelineExecutor(reg, [PipelineStage(id="s1", engine_id="a")])
    executor.execute({}, make_context())
    assert reg.get("a") is engine, "engine must be the registry singleton"


def main():
    checks = [
        ("stages execute in order", test_stages_execute_in_order),
        ("input builder used per stage", test_input_builder_used_per_stage),
        ("unknown engine raises", test_unknown_engine_raises),
        ("required failure terminates", test_required_failure_terminates_pipeline),
        ("optional failure skipped", test_optional_failure_skipped_and_continues),
        ("retry policy retries then succeeds", test_retry_policy_retries_then_succeeds),
        ("retry policy exhausted fails", test_retry_policy_exhausted_fails_required_stage),
        ("timeout enforced", test_timeout_enforced),
        ("disabled stage skipped", test_disabled_stage_skipped),
        ("pipeline hooks emitted", test_pipeline_hooks_emitted),
        ("failed pipeline emits PipelineFailed", test_failed_pipeline_emits_pipeline_failed),
        ("engines resolved only through registry", test_engines_resolved_only_through_registry),
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
