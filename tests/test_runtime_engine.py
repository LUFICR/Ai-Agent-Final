"""Unit tests for the Runtime Foundation (GAP_ANALYSIS.md M6, RFC-002 Ch3/Ch4).

Verifies:
- RuntimeContext is immutable and request-scoped
- EngineUpdate format
- RuntimeEngine contract
- EngineMetrics generation
- Engine execution through the new interface (all 12 adapters, real engines)
- No engine mutates RuntimeContext
- Exceptions map to EngineUpdate.failed (engines never throw)

Run from the repo root:  python tests/test_runtime_engine.py
"""

import sys
import time
from dataclasses import FrozenInstanceError, replace
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wellness_agent.runtime import (
    EngineCategory,
    EngineMetrics,
    EngineResult,
    EngineUpdate,
    RuntimeContext,
    RuntimeEngine,
    RuntimeStage,
    BaseEngine,
    MemoryAdapter,
    LearningAdapter,
    BeliefAdapter,
    HypothesisAdapter,
    BehaviorAdapter,
    WhyAdapter,
    ProactiveAdapter,
    RootCauseAdapter,
    RoutineAdapter,
    ReportsAdapter,
    SelfEvaluationAdapter,
    EmotionAdapter,
)

from wellness_agent.memory import MemorySystem
from wellness_agent.learning import LearningLayer
from wellness_agent.belief_engine import BeliefEngine
from wellness_agent.hypothesis_engine import HypothesisEngine
from wellness_agent.behavior_engine import BehaviorEngine
from wellness_agent.why_engine import WhyEngine
from wellness_agent.proactive_engine import ProactiveEngine
from wellness_agent.root_cause import RootCauseAnalyzer
from wellness_agent.routine_generator import RoutineGenerator
from wellness_agent.reports import ReportGenerator
from wellness_agent.self_evaluation import SelfEvaluator
from wellness_agent.emotion_engine import EmotionEngine

UID = "rt_m6_test"
DATA_ROOT = Path(__file__).resolve().parent.parent / "data"

FAILURES = []


def check(name, fn):
    try:
        fn()
        print("PASS  %s" % name)
    except Exception as e:  # noqa: BLE001
        FAILURES.append((name, e))
        print("FAIL  %s: %s" % (name, e))


def _cleanup():
    if not DATA_ROOT.exists():
        return
    for sub in DATA_ROOT.iterdir():
        if sub.name in ("evaluations", "stress_reports", "simulations"):
            continue
        if not sub.is_dir():
            continue
        for f in sub.glob("*"):
            if f.name.startswith("rt_m6_"):
                try:
                    f.unlink()
                except OSError:
                    pass


def _context():
    return RuntimeContext.create(
        request_id="req-1", user_id=UID, session_id="sess-1")


def test_context_immutable():
    ctx = _context()
    for mutate in (
        lambda: setattr(ctx, "request", None),
        lambda: setattr(ctx.request, "user_id", "hacked"),
        lambda: setattr(ctx.conversation, "active_branch", "hacked"),
        lambda: setattr(ctx.execution, "stage", RuntimeStage.COMPLETED),
        lambda: setattr(ctx.memory, "profile", {"x": 1}),
        lambda: setattr(ctx.metrics, "total_latency", 999),
        lambda: setattr(ctx.metadata, "environment", "prod"),
    ):
        try:
            mutate()
            raise AssertionError("mutation must raise FrozenInstanceError")
        except FrozenInstanceError:
            pass


def test_context_request_scoped():
    a = RuntimeContext.create(request_id="r-a", user_id="u-a", session_id="s-a")
    b = RuntimeContext.create(request_id="r-b", user_id="u-b", session_id="s-b")
    assert a is not b
    assert a.request.user_id == "u-a" and b.request.user_id == "u-b"
    assert a.memory is not b.memory
    assert a.execution.stage == RuntimeStage.INTENT_RESOLVER


def test_context_validation():
    try:
        RuntimeContext.create().validate()
        raise AssertionError("missing ids must raise ValueError")
    except ValueError:
        pass
    ctx = _context()
    assert ctx.validate() is ctx


def test_context_snapshot_equality():
    ctx = _context()
    assert ctx.snapshot() == ctx
    assert ctx.snapshot() is not ctx


def test_engine_update_format():
    d = {"k": 1}
    ok = EngineUpdate.success(data=d, warnings=("w1",), diagnostics=(1,))
    assert ok.result == EngineResult.SUCCESS and ok.success is True
    assert ok.data == {"k": 1} and ok.warnings == ("w1",) and ok.diagnostics == (1,)
    assert isinstance(ok.metrics, EngineMetrics)

    part = EngineUpdate.partial(data={"x": 2})
    assert part.result == EngineResult.PARTIAL and part.success is True

    bad = EngineUpdate.failed()
    assert bad.result == EngineResult.FAILED and bad.success is False

    skip = EngineUpdate.skipped()
    assert skip.result == EngineResult.SKIPPED and skip.success is False

    try:
        ok.data = {"hacked": 1}
        raise AssertionError("EngineUpdate must be immutable")
    except FrozenInstanceError:
        pass


def test_engine_contract():
    try:
        RuntimeEngine()
        raise AssertionError("RuntimeEngine is abstract")
    except TypeError:
        pass
    adapter = EmotionAdapter(EmotionEngine())
    assert adapter.id == "emotion" and adapter.name and adapter.version
    assert adapter.category == EngineCategory.KNOWLEDGE
    assert isinstance(adapter.metadata.id, str)
    assert adapter.health_check() is True


def test_metrics_generation():
    adapter = EmotionAdapter(EmotionEngine())
    update = adapter.execute({"message": "I feel great today"},
                             _context())
    m = update.metrics
    assert isinstance(m, EngineMetrics)
    assert m.latency_ms >= 0
    assert m.started_at and m.finished_at
    datetime.fromisoformat(m.started_at)
    datetime.fromisoformat(m.finished_at)
    assert m.retry_count == 0
    assert m.finished_at >= m.started_at


def test_exception_maps_to_failed():
    class _Exploding:
        def analyze(self, message, recent_context=None):
            raise RuntimeError("boom")

    adapter = EmotionAdapter(_Exploding())
    update = adapter.execute({"message": "x"}, _context())
    assert update.result == EngineResult.FAILED
    assert update.success is False
    codes = [diag.code for diag in update.diagnostics]
    assert "ENGINE_EXCEPTION" in codes


def test_engine_does_not_mutate_context():
    adapter = EmotionAdapter(EmotionEngine())
    ctx = _context()
    before = ctx.snapshot()
    adapter.execute({"message": "I am so stressed out"}, ctx)
    assert ctx == before
    assert ctx.snapshot() == before


def test_memory_adapter_executes():
    adapter = MemoryAdapter(MemorySystem(UID))
    update = adapter.execute({"message": "I sleep only 5 hours"},
                             _context())
    assert update.result == EngineResult.SUCCESS
    assert isinstance(update.data["facts"], list)


def test_emotion_adapter_executes():
    adapter = EmotionAdapter(EmotionEngine())
    update = adapter.execute({"message": "I am exhausted"},
                             _context())
    assert update.result == EngineResult.SUCCESS
    assert isinstance(update.data["emotion"], dict)


def test_learning_adapter_executes():
    adapter = LearningAdapter(LearningLayer(UID))
    turns = [
        {"user": "I've been unable to fall asleep lately", "assistant": "Tell me more"},
        {"user": "The late nights started after work stress peaked", "assistant": "I see"},
        {"user": "It's work deadlines, they keep piling up", "assistant": "Understood"},
        {"user": "Set up a wind-down routine for me", "assistant": "Good idea"},
        {"user": "That works, let's do that", "assistant": "Great"},
        {"user": "Thank you, goodnight", "assistant": "Good night"},
    ]
    update = adapter.execute(
        {"turns": turns,
         "judge_result": {"dims": {"objective_completion": 80}}},
        _context())
    assert update.result == EngineResult.SUCCESS
    assert isinstance(update.data["updates"], dict)


def test_belief_adapter_executes():
    adapter = BeliefAdapter(BeliefEngine(UID))
    facts = [{"category": "habit", "key": "sleep_hours",
              "value": "5 hours", "confidence": 70, "source": "conversation"}]
    update = adapter.execute({"facts": facts}, _context())
    assert update.result == EngineResult.SUCCESS
    assert isinstance(update.data["beliefs"], list)


def test_hypothesis_adapter_executes():
    adapter = HypothesisAdapter(HypothesisEngine(UID))
    update = adapter.execute({"message": "work stress keeps me up at night"},
                             _context())
    assert update.result == EngineResult.SUCCESS
    assert isinstance(update.data["hypotheses"], dict)


def test_behavior_adapter_executes():
    adapter = BehaviorAdapter(BehaviorEngine(UID))
    update = adapter.execute({"message": "I never want to talk about it"},
                             _context())
    assert update.result == EngineResult.SUCCESS
    assert isinstance(update.data["traits"], dict)


def test_why_adapter_executes():
    adapter = WhyAdapter(WhyEngine(MemorySystem(UID)))
    update = adapter.execute({}, _context())
    assert update.result == EngineResult.SUCCESS
    assert isinstance(update.data["patterns"], list)


def test_proactive_adapter_executes():
    mem = MemorySystem(UID)
    adapter = ProactiveAdapter(ProactiveEngine(
        mem, WhyEngine(mem), BehaviorEngine(UID)))
    update = adapter.execute({}, _context())
    assert update.result == EngineResult.SUCCESS
    assert isinstance(update.data["checkin"], dict)


def test_root_cause_adapter_executes():
    adapter = RootCauseAdapter(RootCauseAnalyzer())
    update = adapter.execute({"pillar": "sleep"}, _context())
    assert update.result == EngineResult.SUCCESS
    assert isinstance(update.data["root_cause"], dict)


def test_routine_adapter_executes():
    adapter = RoutineAdapter(RoutineGenerator())
    update = adapter.execute({"goal": "improve my sleep"}, _context())
    assert update.result == EngineResult.SUCCESS
    assert isinstance(update.data["routine"], dict)


def test_reports_adapter_executes():
    adapter = ReportsAdapter(ReportGenerator())
    update = adapter.execute({"period": "daily"}, _context())
    assert update.result == EngineResult.SUCCESS
    assert isinstance(update.data["report"], dict)


def test_self_evaluation_adapter_executes():
    adapter = SelfEvaluationAdapter(SelfEvaluator(UID))
    update = adapter.execute(
        {"reply": "That works, let's do that",
         "objective": {"objective": "build_rapport"}},
        _context())
    assert update.result == EngineResult.SUCCESS
    assert isinstance(update.data["result"], dict)


def test_adapters_all_expose_contract():
    mem = MemorySystem(UID)
    adapters = [
        MemoryAdapter(mem),
        LearningAdapter(LearningLayer(UID)),
        BeliefAdapter(BeliefEngine(UID)),
        HypothesisAdapter(HypothesisEngine(UID)),
        BehaviorAdapter(BehaviorEngine(UID)),
        WhyAdapter(WhyEngine(mem)),
        ProactiveAdapter(ProactiveEngine(mem, WhyEngine(mem), BehaviorEngine(UID))),
        RootCauseAdapter(RootCauseAnalyzer()),
        RoutineAdapter(RoutineGenerator()),
        ReportsAdapter(ReportGenerator()),
        SelfEvaluationAdapter(SelfEvaluator(UID)),
        EmotionAdapter(EmotionEngine()),
    ]
    ids = [a.id for a in adapters]
    assert len(ids) == len(set(ids)), "engine ids must be unique"
    for a in adapters:
        assert isinstance(a, RuntimeEngine)
        assert isinstance(a, BaseEngine)
        assert a.metadata.version
        assert a.timeout_ms > 0


def main():
    checks = [
        ("RuntimeContext immutable", test_context_immutable),
        ("RuntimeContext request-scoped", test_context_request_scoped),
        ("RuntimeContext validation", test_context_validation),
        ("RuntimeContext snapshot equality", test_context_snapshot_equality),
        ("EngineUpdate format", test_engine_update_format),
        ("Engine contract", test_engine_contract),
        ("EngineMetrics generation", test_metrics_generation),
        ("exceptions map to FAILED", test_exception_maps_to_failed),
        ("engine never mutates context", test_engine_does_not_mutate_context),
        ("memory adapter executes", test_memory_adapter_executes),
        ("emotion adapter executes", test_emotion_adapter_executes),
        ("learning adapter executes", test_learning_adapter_executes),
        ("belief adapter executes", test_belief_adapter_executes),
        ("hypothesis adapter executes", test_hypothesis_adapter_executes),
        ("behavior adapter executes", test_behavior_adapter_executes),
        ("why adapter executes", test_why_adapter_executes),
        ("proactive adapter executes", test_proactive_adapter_executes),
        ("root cause adapter executes", test_root_cause_adapter_executes),
        ("routine adapter executes", test_routine_adapter_executes),
        ("reports adapter executes", test_reports_adapter_executes),
        ("self-evaluation adapter executes", test_self_evaluation_adapter_executes),
        ("all 12 adapters expose contract", test_adapters_all_expose_contract),
    ]
    _cleanup()
    try:
        for name, fn in checks:
            check(name, fn)
    finally:
        _cleanup()
    print("-" * 60)
    if FAILURES:
        print("FAILED: %d of %d" % (len(FAILURES), len(checks)))
        sys.exit(1)
    print("OK: all %d tests passed" % len(checks))


if __name__ == "__main__":
    main()
