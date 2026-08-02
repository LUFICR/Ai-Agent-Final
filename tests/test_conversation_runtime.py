"""M8 ConversationRuntime tests (spec Ch1): single entry point, request
validation, statelessness, registry-based orchestration resolution and the
ConversationResponse contract."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wellness_agent.runtime.conversation_engine import (
    ConversationEngine,
    PersistenceEngine,
)
from wellness_agent.runtime.conversation_runtime import (
    ConversationRequest,
    ConversationResponse,
    ConversationRuntime,
)
from wellness_agent.runtime.registry import EngineRegistry
from wellness_agent.runtime.runtime_orchestrator import RuntimeOrchestrator

FAILURES = []


def check(name, fn):
    try:
        fn()
        print("  ok - %s" % name)
    except Exception as exc:  # noqa: BLE001
        FAILURES.append((name, exc))
        print("  FAIL - %s: %s: %s" % (name, type(exc).__name__, exc))


def make_registry(turn=None):
    reg = EngineRegistry(user_id="conv_t")
    reg.register("conversation",
                 lambda r: ConversationEngine(
                     lambda message: turn if turn is not None
                     else {"response": "echo: %s" % message,
                           "user_message": message}))
    reg.register("persistence", lambda r: PersistenceEngine())
    reg.register("runtime_orchestrator",
                 lambda r: RuntimeOrchestrator(registry=r))
    return reg


def test_single_public_execution_method():
    runtime = ConversationRuntime(make_registry())
    assert callable(runtime.execute)
    public = [n for n in dir(runtime) if not n.startswith("_")]
    assert "execute" in public


def test_invalid_requests_rejected_before_orchestration():
    runtime = ConversationRuntime(make_registry())
    for bad in (None, "not a request",
                ConversationRequest(user_id="")):
        raised = False
        try:
            runtime.execute(bad)
        except ValueError:
            raised = True
        assert raised, "invalid request must raise ValueError"


def test_execute_returns_response_contract():
    runtime = ConversationRuntime(make_registry())
    response = runtime.execute(ConversationRequest(
        user_id="conv_t", message="i feel tired"))
    assert isinstance(response, ConversationResponse)
    assert response.response_id
    assert response.message == "echo: i feel tired"
    assert response.data["user_message"] == "i feel tired"
    assert response.diagnostics is not None
    assert response.metrics is not None


def test_orchestrator_resolved_from_registry():
    reg = make_registry()
    runtime = ConversationRuntime(reg)
    runtime.execute(ConversationRequest(user_id="conv_t", message="hi"))
    assert "runtime_orchestrator" in reg.initialized(), \
        "orchestrator must be resolved through the registry"


def test_runtime_is_stateless_across_requests():
    reg = make_registry()
    runtime = ConversationRuntime(reg)
    first = runtime.execute(ConversationRequest(user_id="conv_t",
                                                message="first"))
    second = runtime.execute(ConversationRequest(user_id="conv_t",
                                                 message="second"))
    assert first.response_id != second.response_id
    assert first.data["user_message"] == "first"
    assert second.data["user_message"] == "second"


def test_empty_message_is_a_valid_request():
    runtime = ConversationRuntime(make_registry())
    response = runtime.execute(ConversationRequest(user_id="conv_t"))
    assert response.message == "echo: "


def test_turn_flows_through_runtime_into_response():
    turn = {"response": "hello there", "state": {"current_state": "greeting"}}
    runtime = ConversationRuntime(make_registry(turn=turn))
    response = runtime.execute(ConversationRequest(user_id="conv_t",
                                                   message="hello"))
    assert response.message == "hello there"
    assert response.data is not None and response.data["state"] == turn["state"]


def main():
    checks = [
        ("single public execution method", test_single_public_execution_method),
        ("invalid requests rejected before orchestration",
         test_invalid_requests_rejected_before_orchestration),
        ("execute returns response contract", test_execute_returns_response_contract),
        ("orchestrator resolved from registry",
         test_orchestrator_resolved_from_registry),
        ("runtime is stateless across requests", test_runtime_is_stateless_across_requests),
        ("empty message is a valid request", test_empty_message_is_a_valid_request),
        ("turn flows through runtime into response",
         test_turn_flows_through_runtime_into_response),
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
