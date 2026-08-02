"""Unit tests for the Engine Registry and DI (GAP_ANALYSIS.md M7, RFC-002 Ch2).

Covers: registration, duplicate registration, dependency resolution,
singleton behavior, mock replacement, health checks, lifecycle, circular
dependency detection, the AgentRegistry DI facade, and orchestrator wiring.

Run from the repo root:  python tests/test_engine_registry.py
"""

import sys
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wellness_agent.agents import AgentRegistry, build_user_registry
from wellness_agent.memory import MemorySystem
from wellness_agent.runtime import (
    CircularDependencyError,
    EngineRegistry,
    RegistrationError,
    UnknownEngineError,
    EngineCategory,
)

UID = "rt_m7_test"
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
            if f.name.startswith("rt_m7_"):
                try:
                    f.unlink()
                except OSError:
                    pass


def test_registration_and_lazy_init():
    reg = build_user_registry(UID + "_lazy")
    assert reg.initialized() == [], "registration must not build engines (lazy init)"
    memory = reg.get("memory")
    assert isinstance(memory, MemorySystem)
    assert reg.initialized() == ["memory"]
    assert reg.get("memory") is memory, "get() must return the singleton"


def test_every_engine_registered_once():
    reg = build_user_registry(UID + "_all")
    ids = reg.ids()
    assert len(ids) == len(set(ids)), "engine ids must be unique"
    assert len(ids) == 29, "17 raw engines + 12 adapters, got %d: %s" % (len(ids), ids)
    assert "memory" in ids and "report_generator" in ids
    assert "memory_adapter" in ids and "self_evaluation_adapter" in ids
    for engine_id in ids:
        for dep in reg.dependency_graph()[engine_id]:
            assert dep in ids, "%s declares missing dep %s" % (engine_id, dep)


def test_duplicate_registration_raises():
    reg = EngineRegistry(user_id=UID + "_dup")
    reg.register("a", lambda r: {"engine": "a"})
    try:
        reg.register("a", lambda r: {"engine": "b"})
        raise AssertionError("duplicate factory registration must raise")
    except RegistrationError:
        pass
    try:
        reg.register_instance("a", object())
        raise AssertionError("duplicate instance registration must raise")
    except RegistrationError:
        pass
    try:
        reg.register("", lambda r: None)
        raise AssertionError("empty id must raise")
    except RegistrationError:
        pass
    try:
        reg.register("x", None)
        raise AssertionError("non-callable factory must raise")
    except RegistrationError:
        pass


def test_dependency_resolution():
    reg = EngineRegistry(user_id=UID + "_deps")
    reg.register("memory", lambda r: MemorySystem(UID + "_deps_mem"))
    reg.register("planner", lambda r: {"memory": r.get("memory")}, deps=("memory",))
    assert reg.dependency_graph()["planner"] == ("memory",)
    assert reg.get("planner")["memory"] is reg.get("memory")

    bad = EngineRegistry(user_id=UID + "_missing_dep")
    bad.register("a", lambda r: r.get("ghost"), deps=("ghost",))
    try:
        bad.get("a")
        raise AssertionError("missing dependency must raise")
    except RegistrationError as e:
        assert "ghost" in str(e)


def test_singleton_behavior():
    reg = build_user_registry(UID + "_sing")
    assert reg.get("behavior_engine") is reg.get("behavior_engine")
    assert reg.get("why_engine") is reg.get("why_engine")
    assert reg.get("proactive_engine") is reg.get("proactive_engine")

    other = build_user_registry(UID + "_sing_b")
    assert reg.get("memory") is not other.get("memory"), "per-user isolation"
    assert reg.get("behavior_engine") is not other.get("behavior_engine")


def test_mock_replacement():
    reg = build_user_registry(UID + "_mock")
    stub = {"fake": "memory"}
    reg.replace("memory", stub)
    assert reg.get("memory") is stub

    try:
        reg.replace("never_registered", object())
        raise AssertionError("replacing unknown engine must raise")
    except UnknownEngineError:
        pass


def test_mock_context_manager_restores():
    reg = build_user_registry(UID + "_mockctx")
    real = reg.get("memory")
    stub = {"fake": "memory"}
    with reg.mock("memory", stub):
        assert reg.get("memory") is stub
        assert reg.health_check("memory") is True
    assert reg.get("memory") is real, "mock must restore the original singleton"

    with reg.mock("learning", stub):
        assert reg.get("learning") is stub
    assert reg.get("learning") is not stub, "lazy engine must rebuild after mock"


def test_health_checks():
    class _Unhealthy:
        def health_check(self):
            return False

    class _Healthy:
        def health_check(self):
            return True

    reg = EngineRegistry(user_id=UID + "_health")
    reg.register_instance("good", _Healthy())
    reg.register_instance("bad", _Unhealthy())
    reg.register_instance("plain", {"no": "health method"})
    assert reg.health_check("good") is True
    assert reg.health_check("bad") is False
    assert reg.health_check("plain") is True, "engines without health_check default to healthy"
    assert reg.health() == {"good": True, "bad": False, "plain": True}


def test_initialize_all_prevents_startup_on_failure():
    class _Boom:
        def initialize(self):
            raise RuntimeError("cannot start")

    reg = EngineRegistry(user_id=UID + "_life")
    reg.register_instance("ok", {"x": 1})
    reg.register_instance("boom", _Boom())
    try:
        reg.initialize_all()
        raise AssertionError("failing engine must prevent startup")
    except RuntimeError:
        pass
    reg.dispose_all()
    assert reg.initialized() == []


def test_circular_dependency_detected():
    reg = EngineRegistry(user_id=UID + "_circ")
    reg.register("a", lambda r: {"a": r.get("b")}, deps=("b",))
    reg.register("b", lambda r: {"b": r.get("a")}, deps=("a",))
    try:
        reg.get("a")
        raise AssertionError("circular dependency must raise")
    except CircularDependencyError:
        pass


def test_diagnostics():
    reg = build_user_registry(UID + "_diag")
    reg.get("memory_adapter")
    diag = reg.diagnostics()
    assert diag["user_id"] == UID + "_diag"
    assert diag["version"] == "1.0.0"
    assert len(diag["registered"]) == 29
    assert "memory" in diag["initialized"]
    assert "learning" not in diag["initialized"], "diagnostics keep laziness"
    adapters = [e for e in diag["engines"] if e["id"] == "memory_adapter"]
    assert adapters and adapters[0]["metadata"]["category"] == EngineCategory.KNOWLEDGE.value
    assert "dependency_graph" in diag and diag["dependency_graph"]["proactive_engine"]


def test_agent_registry_facade():
    agents = AgentRegistry(UID + "_facade")
    assert isinstance(agents.memory, MemorySystem)
    assert agents.memory is agents.registry.get("memory")
    assert agents.behavior_engine is agents.registry.get("behavior_engine")
    assert agents.planner is agents.registry.get("planner")
    assert agents.report_generator is agents.registry.get("report_generator")
    assert callable(agents.get_agent("emotion_detection"))
    assert callable(agents.get_agent("memory_manager"))
    try:
        agents.no_such_engine
        raise AssertionError("unknown attribute must raise AttributeError")
    except AttributeError:
        pass


def test_extract_and_store_unchanged():
    agents = AgentRegistry(UID + "_extract")
    stored = agents.extract_and_store("I get about 5 hours of sleep each night")
    assert isinstance(stored, list) and stored
    assert agents.reflection_response({"routine_created": True}).startswith("You've built")
    assert agents.reflection_response({}).startswith("We've covered")


def test_adapters_wrap_registry_engines():
    reg = build_user_registry(UID + "_adapt")
    adapter = reg.get("memory_adapter")
    assert adapter._engine is reg.get("memory"), "adapter must wrap the registry singleton"
    update = adapter.execute({"message": "I am exhausted"}, None)
    assert update.success and "facts" in update.data
    assert reg.get("emotion_adapter")._engine is reg.get("emotion_engine")
    assert reg.get("proactive_adapter")._engine is reg.get("proactive_engine")


def test_orchestrator_wiring_unchanged():
    from wellness_agent.orchestrator import Orchestrator

    orch = Orchestrator(user_id=UID + "_orch")
    assert isinstance(orch.agents, AgentRegistry)
    assert orch.agents.memory is orch.agents.registry.get("memory")
    result = orch.process_message("hello")
    assert isinstance(result, dict) and "response" in result
    assert "state" in result


def main():
    checks = [
        ("registration + lazy init", test_registration_and_lazy_init),
        ("every engine registered once", test_every_engine_registered_once),
        ("duplicate registration raises", test_duplicate_registration_raises),
        ("dependency resolution", test_dependency_resolution),
        ("singleton behavior", test_singleton_behavior),
        ("mock replacement", test_mock_replacement),
        ("mock context manager restores", test_mock_context_manager_restores),
        ("health checks", test_health_checks),
        ("initialize_all prevents startup on failure", test_initialize_all_prevents_startup_on_failure),
        ("circular dependency detected", test_circular_dependency_detected),
        ("registry diagnostics", test_diagnostics),
        ("AgentRegistry DI facade", test_agent_registry_facade),
        ("extract_and_store unchanged", test_extract_and_store_unchanged),
        ("adapters wrap registry engines", test_adapters_wrap_registry_engines),
        ("orchestrator wiring unchanged", test_orchestrator_wiring_unchanged),
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
