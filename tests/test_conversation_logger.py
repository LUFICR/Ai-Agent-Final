"""Conversation Logging & Replay — acceptance tests.

Offline (GROQ_API_KEY popped) the orchestrator runs rule-based. Verifies:
- every turn is logged (JSON, one file per conversation)
- planner actions / modes / reasons are logged
- intent graph + confidence scores are logged
- runtime changes (engine order, engine updates, context before/after) are logged
- markdown transcript matches the JSON turns
- multiple conversations create multiple files
- no data loss (flush/close semantics, valid JSON, full turn counts)
- no overwrites (same conversation id after close creates a NEW file)
- buttons_shown / button_clicked capture
- secrets are masked (privacy rule)
"""

import glob
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.pop("GROQ_API_KEY", None)

from wellness_agent.conversation_logger import (  # noqa: E402
    ConversationLogger,
    build_turn_payload,
    get_conversation_logger,
    mask_secrets,
)
from wellness_agent.orchestrator import Orchestrator  # noqa: E402

FAILURES = []
UID = "convlog_test"
UID2 = "convlog_test2"

TMP_ROOT = Path(tempfile.gettempdir()) / "opencode" / "convlog_acceptance"
LOG_DIR = TMP_ROOT / "logs"

# Route the process-wide logger to the temp dir (set BEFORE any Orchestrator).
os.environ["WELLNESS_CONVERSATION_LOG_DIR"] = str(LOG_DIR)

REQUIRED_TURN_FIELDS = [
    "timestamp", "conversation_id", "turn_number",
    "user_message", "raw_user_input",
    "detected_intents", "intent_graph", "confidence_scores",
    "active_branch", "planner_mode", "planner_action", "planner_reason",
    "runtime_state", "engine_execution_order", "engine_updates",
    "slots_before", "slots_after", "memory_used",
    "recommendation_generated", "buttons_shown", "button_clicked",
    "ai_response", "response_time_ms", "diagnostics", "warnings",
]

REQUIRED_METADATA_FIELDS = [
    "conversation_id", "started_at", "ended_at", "user_id",
    "runtime_version", "planner_version", "intent_resolver_version",
    "branch_manager_version", "git_commit", "total_turns",
]


def check(name, fn):
    try:
        fn()
        print("  ok - %s" % name)
    except Exception as exc:  # noqa: BLE001
        FAILURES.append((name, exc))
        print("  FAIL - %s: %s: %s" % (name, type(exc).__name__, exc))


def cleanup():
    for pattern in ("sessions/%s*", "memory/%s*", "behaviors/%s*",
                    "beliefs/%s*", "hypotheses/%s*", "whys/%s*",
                    "learning/%s*", "reports/%s*", "routines/%s*"):
        for path in glob.glob(os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "data", pattern % UID)):
            try:
                os.remove(path)
            except OSError:
                pass
            try:
                os.remove(path.replace(UID, UID2))
            except OSError:
                pass
    shutil.rmtree(TMP_ROOT, ignore_errors=True)


def log_files():
    return sorted(LOG_DIR.glob("conversation_*.json")) if LOG_DIR.is_dir() else []


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def test_dir_auto_created_and_turn_logged():
    orch = Orchestrator(user_id=UID, enable_learning=False,
                        enable_auto_judge=False)
    orch.process_message("hello")
    orch.process_message("I've been feeling really burned out from work")
    orch.process_message("sleep is terrible, only about 4 hours a night")
    get_conversation_logger().flush()
    files = log_files()
    assert files, "no JSON log written"
    assert len(files) == 1, "one conversation must produce exactly one file"
    doc = read_json(files[0])
    assert len(doc["turns"]) == 3, "every turn must be logged"
    assert doc["turns"][0]["turn_number"] == 1
    assert doc["turns"][2]["turn_number"] == 3


def test_metadata_recorded_once():
    files = log_files()
    meta = read_json(files[-1])["metadata"]
    for key in REQUIRED_METADATA_FIELDS:
        assert key in meta, "missing metadata field %s" % key
    assert meta["conversation_id"] == UID
    assert meta["user_id"] == UID
    assert meta["total_turns"] == 3
    assert meta["started_at"] and meta["ended_at"]
    assert meta["started_at"] <= meta["ended_at"]
    assert meta["runtime_version"]
    assert meta["planner_version"] == "2.0"
    assert meta["intent_resolver_version"] == "2.0.0"
    assert meta["git_commit"], "git_commit must resolve (repo has git)"


def test_every_turn_has_all_required_fields():
    doc = read_json(log_files()[-1])
    for turn in doc["turns"]:
        for key in REQUIRED_TURN_FIELDS:
            assert key in turn, "turn %s missing field %s" % (
                turn["turn_number"], key)


def test_planner_actions_modes_reasons_logged():
    doc = read_json(log_files()[-1])
    for turn in doc["turns"]:
        assert turn["planner_action"], "planner_action empty"
        assert turn["planner_reason"], "planner_reason empty"
        assert isinstance(turn["planner_mode"], (str, type(None)))
    planner = doc["turns"][-1]["planner"]
    assert planner["selected_action"] == doc["turns"][-1]["planner_action"]
    assert planner["reason"] == doc["turns"][-1]["planner_reason"]
    assert planner["mode_after"] == doc["turns"][-1]["planner_mode"]
    # mode continuity: turn 2's mode_before must equal turn 1's mode_after
    assert doc["turns"][1]["planner"]["mode_before"] == \
        doc["turns"][0]["planner"]["mode_after"]


def test_intent_graph_logged():
    doc = read_json(log_files()[-1])
    for turn in doc["turns"]:
        ig = turn["intent_graph"]
        assert isinstance(ig, dict)
        assert "primary_intent" in ig
        assert ig["primary_intent"]["intent"], "primary intent missing"
        assert turn["intent"]["primary"] == ig["primary_intent"]["intent"]
        assert turn["detected_intents"], "detected_intents empty"
        assert "overall_confidence" in turn["confidence_scores"]
    # the topic turn must carry a sleep topic intent somewhere in the graph
    sleep_turn = doc["turns"][2]
    assert sleep_turn["active_branch"] or any(
        "sleep" in str(l) for l in sleep_turn["detected_intents"]), \
        "topic intents or active branch expected"


def test_runtime_changes_logged():
    doc = read_json(log_files()[-1])
    for turn in doc["turns"]:
        assert turn["runtime_state"] == "disposed"
        assert turn["engine_execution_order"] == [
            "intent_resolver", "conversation", "persistence"]
        assert turn["engine_updates"], "engine_updates empty"
        assert turn["context_changes"], "context_changes empty"
        last = turn["context_changes"][-1]
        assert "changed_fields" in last and "before" in last and "after" in last
        assert isinstance(turn["diagnostics"], dict)
        assert isinstance(turn["warnings"], list)
        assert isinstance(turn["response_time_ms"], (int, float))


def test_buttons_and_clicked():
    orch = Orchestrator(user_id=UID, enable_learning=False,
                        enable_auto_judge=False)
    r1 = orch.process_message("hello")
    options = r1.get("options")
    assert options, "greeting expected to offer options"
    orch.process_message(str(options[0]))
    get_conversation_logger().flush()
    doc = read_json(log_files()[-1])
    t1, t2 = doc["turns"][-2], doc["turns"][-1]  # the two turns just added
    assert t1["buttons_shown"] == options, \
        "buttons_shown must equal the greeting options"
    assert t1["button_clicked"] is None  # nothing shown before turn 1
    assert t2["button_clicked"] == str(options[0]), \
        "exact option reply must be recorded as a button click"


def test_markdown_transcript_matches_json():
    md_files = sorted(LOG_DIR.glob("conversation_*.md"))
    assert md_files, "markdown transcript missing"
    md_text = md_files[-1].read_text(encoding="utf-8")
    doc = read_json(log_files()[-1])
    turns = doc["turns"]
    assert "# Conversation" in md_text
    for t in turns:
        assert "## Turn %s" % t["turn_number"] in md_text
        assert (t.get("user_message") or "(empty)") in md_text
        assert (t.get("ai_response") or "(empty)") in md_text
        action = t.get("planner_action") or "(none)"
        assert action in md_text
        # markdown and JSON agree on the intent line content
        assert (t.get("intent") or {}).get("primary") in md_text or \
            "(none)" in md_text


def test_multiple_conversations_multiple_files():
    before = len(log_files())
    orch2 = Orchestrator(user_id=UID2, enable_learning=False,
                         enable_auto_judge=False)
    orch2.process_message("hello")
    orch2.process_message("hi")
    get_conversation_logger().flush()
    assert len(log_files()) == before + 1, "second conversation needs a new file"
    for f in log_files():
        doc = read_json(f)
        assert doc["metadata"]["total_turns"] == len(doc["turns"])


def test_no_data_loss_after_close():
    tmp = TMP_ROOT / "isolated"
    logger = ConversationLogger(log_dir=tmp)
    _record_synthetic(logger, "iso_user", 2)
    logger.close()
    files = sorted(tmp.glob("conversation_*.json"))
    assert files, "isolated logger wrote nothing"
    doc = read_json(files[0])
    assert doc["metadata"]["conversation_id"] == "iso_user", \
        "conversation_id mismatch: %s" % doc["metadata"].get("conversation_id")
    assert doc["metadata"]["total_turns"] == 2, \
        "total_turns=%s" % doc["metadata"].get("total_turns")
    assert len(doc["turns"]) == 2, "turns=%s" % len(doc["turns"])


def test_no_overwrite_after_close():
    tmp = TMP_ROOT / "no_overwrite"
    logger = ConversationLogger(log_dir=tmp)
    _record_synthetic(logger, "ow_user", 2)
    logger.flush()
    n1 = len(sorted(tmp.glob("conversation_*.json")))
    logger.close()
    logger2 = ConversationLogger(log_dir=tmp)
    _record_synthetic(logger2, "ow_user", 1)
    logger2.flush()
    n2 = len(sorted(tmp.glob("conversation_*.json")))
    logger2.close()
    assert n2 == n1 + 1, "same conversation after close must NOT overwrite"
    for f in sorted(tmp.glob("conversation_*.json")):
        doc = read_json(f)
        assert doc["metadata"]["total_turns"] == len(doc["turns"])


def test_end_conversation_opens_new_file():
    tmp = TMP_ROOT / "ended"
    logger = ConversationLogger(log_dir=tmp)
    _record_synthetic(logger, "end_user", 1)
    logger.flush()
    logger.end_conversation("end_user")
    _record_synthetic(logger, "end_user", 1)
    logger.flush()
    logger.close()
    files = sorted(tmp.glob("conversation_*.json"))
    assert len(files) == 2, "conversation after end_conversation needs a new file"


def test_secrets_masked():
    sample = {
        "api_key": "sk-123456",
        "nested": {"token": "abc", "GROQ_API_KEY": "gsk-zzz", "ok": "fine"},
        "safe": "nothing sensitive",
    }
    masked = mask_secrets(sample)
    assert masked["api_key"] == "***"
    assert masked["nested"]["token"] == "***"
    assert masked["nested"]["GROQ_API_KEY"] == "***"
    assert masked["nested"]["ok"] == "fine"
    assert masked["safe"] == "nothing sensitive"


def _record_synthetic(logger, cid, turns):
    for n in range(1, turns + 1):
        logger.record_turn(_synthetic_payload(cid, n))
    logger.flush()


def _synthetic_payload(conversation_id, turn_no):
    """Minimal context-shaped payload (mirrors build_turn_payload output)."""
    return {
        "conversation_id": conversation_id,
        "timestamp": "2026-08-02T10:%02d:%02d" % (turn_no, turn_no * 2),
        "raw_user_input": "hello",
        "turn": {
            "user_message": "hello",
            "response": "Hi there",
            "options": ["My mood", "My habits"],
            "planner_decision": {
                "action": "ask_question", "mode": "discovery",
                "reason": "synthetic", "confidence": 0.8,
                "next_state": None, "metadata": {}},
        },
        "intent_graph": {"primary_intent": {"intent": "greeting",
                                            "confidence": 0.9},
                         "secondary_intents": [], "background_intents": [],
                         "slots": {}, "overall_confidence": 0.9},
        "slot_graph": {},
        "active_branch": "",
        "runtime_state": "disposed",
        "runtime_context": {"version": turn_no, "request_id": "r%d" % turn_no,
                            "session_id": "s", "trace_id": "",
                            "runtime_version": "1.0.0"},
        "engine_execution_order": ["intent_resolver", "conversation",
                                   "persistence"],
        "engine_updates": [{"engine": "intent_resolver", "version": turn_no,
                            "changed_fields": ["intent_graph"],
                            "diagnostics": []}],
        "context_changes": [{"version": turn_no, "engine": "intent_resolver",
                             "timestamp": "", "changed_fields": ["intent_graph"],
                             "before": {}, "after": {"keys": ["primary_intent"],
                                                     "size": 40}}],
        "diagnostics": {"events": [], "engine_latency_ms": {}},
        "warnings": [],
        "memory_used": {"facts_total": 0, "top_facts": [], "trust_score": 70},
        "recommendation_generated": False,
        "top_recommendation": None,
        "buttons_shown": ["My mood", "My habits"],
        "response_time_ms": 12.5,
    }


def main():
    checks = [
        ("log dir auto-created; every turn logged in one file",
         test_dir_auto_created_and_turn_logged),
        ("conversation metadata recorded once",
         test_metadata_recorded_once),
        ("every turn has all required fields",
         test_every_turn_has_all_required_fields),
        ("planner actions/modes/reasons logged",
         test_planner_actions_modes_reasons_logged),
        ("intent graph + confidence logged",
         test_intent_graph_logged),
        ("runtime changes logged (engine order/updates/context)",
         test_runtime_changes_logged),
        ("buttons_shown / button_clicked captured",
         test_buttons_and_clicked),
        ("markdown transcript matches JSON",
         test_markdown_transcript_matches_json),
        ("multiple conversations create multiple files",
         test_multiple_conversations_multiple_files),
        ("no data loss after close",
         test_no_data_loss_after_close),
        ("no overwrite after close",
         test_no_overwrite_after_close),
        ("end_conversation opens a new file",
         test_end_conversation_opens_new_file),
        ("secrets masked",
         test_secrets_masked),
    ]
    cleanup()
    try:
        for name, fn in checks:
            check(name, fn)
    finally:
        try:
            get_conversation_logger().close()
        except Exception:  # noqa: BLE001
            pass
        cleanup()
    print("-" * 60)
    if FAILURES:
        print("FAILED: %d of %d" % (len(FAILURES), len(checks)))
        sys.exit(1)
    print("ALL PASS: %d checks" % len(checks))


if __name__ == "__main__":
    main()
