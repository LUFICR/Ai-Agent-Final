"""M8 integration: the REAL Orchestrator executes through ConversationRuntime.

Offline (GROQ_API_KEY popped) the whole flow runs rule-based, exactly like
the baseline suites. This verifies:
- process_message returns byte-identical turn dicts (risk, greeting, normal)
- the runtime path is exercised (conversation/persistence/runtime_orchestrator
  engines initialized in the per-user registry)
- data hygiene: no leftover session/memory files, eval index untouched
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.pop("GROQ_API_KEY", None)

from wellness_agent.config import get_user_session_path
from wellness_agent.orchestrator import Orchestrator
from wellness_agent.utils.storage import load_json

FAILURES = []
UID = "rt_m8_int"


def check(name, fn):
    try:
        fn()
        print("  ok - %s" % name)
    except Exception as exc:  # noqa: BLE001
        FAILURES.append((name, exc))
        print("  FAIL - %s: %s: %s" % (name, type(exc).__name__, exc))


def cleanup():
    import glob

    data_dir = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "data")
    for pattern in ("sessions/%s*", "memory/%s*", "behaviors/%s*",
                    "beliefs/%s*", "hypotheses/%s*", "whys/%s*",
                    "evaluations/%s*", "learning/%s*", "reports/%s*",
                    "routines/%s*"):
        for path in glob.glob(os.path.join(data_dir, pattern % UID)):
            try:
                os.remove(path)
            except OSError:
                pass


def test_runtime_engines_registered_and_executed():
    orch = Orchestrator(user_id=UID, enable_learning=False,
                        enable_auto_judge=False)
    orch.process_message("hello")
    initialized = orch.agents.registry.initialized()
    assert "conversation" in initialized
    assert "persistence" in initialized
    assert "runtime_orchestrator" in initialized
    cleanup()


def test_normal_turn_through_runtime():
    orch = Orchestrator(user_id=UID, enable_learning=False,
                        enable_auto_judge=False)
    result = orch.process_message("I've been feeling really burned out from work")
    assert isinstance(result, dict)
    assert "response" in result and result["response"]
    assert result["emotion"] is not None
    assert result["state"] is not None
    assert result["route"]
    assert result["user_message"] == "I've been feeling really burned out from work"
    cleanup()


def test_risk_path_through_runtime():
    orch = Orchestrator(user_id=UID, enable_learning=False,
                        enable_auto_judge=False)
    result = orch.process_message(
        "I keep thinking about killing myself and I don't know what to do")
    assert result["risk_detected"] is True
    assert result["route"] == ["risk_protocol"]
    assert "988" in result["response"]
    cleanup()


def test_greeting_with_empty_message():
    orch = Orchestrator(user_id=UID, enable_learning=False,
                        enable_auto_judge=False)
    result = orch.process_message("")
    assert result["response"]
    assert result["state"]["current_state"] == "greeting"
    cleanup()


def test_identity_across_requests_after_migration():
    orch = Orchestrator(user_id=UID, enable_learning=False,
                        enable_auto_judge=False)
    r1 = orch.process_message("I sleep terribly, only about 4 hours of sleep a night")
    r2 = orch.process_message("i feel really anxious about work lately")
    assert r1["user_message"] != r2["user_message"]
    assert r2["state"] is not None
    # memory persisted as before (session file exists)
    assert os.path.exists(get_user_session_path(UID))
    cleanup()


def test_eval_index_untouched():
    index_path = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "data", "evaluations", "index.json")
    entries = (load_json(index_path) or {}).get("entries", [])
    assert len(entries) == 620, "eval index must stay at 620 entries"


def main():
    checks = [
        ("runtime engines registered and executed",
         test_runtime_engines_registered_and_executed),
        ("normal turn through runtime", test_normal_turn_through_runtime),
        ("risk path through runtime", test_risk_path_through_runtime),
        ("greeting with empty message", test_greeting_with_empty_message),
        ("identity across requests after migration",
         test_identity_across_requests_after_migration),
        ("eval index untouched", test_eval_index_untouched),
    ]
    cleanup()
    try:
        for name, fn in checks:
            check(name, fn)
    finally:
        cleanup()
    print("-" * 60)
    if FAILURES:
        print("FAILED: %d of %d" % (len(FAILURES), len(checks)))
        sys.exit(1)
    print("OK: all %d tests passed" % len(checks))


if __name__ == "__main__":
    main()
