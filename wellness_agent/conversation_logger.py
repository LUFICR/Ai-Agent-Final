"""Conversation Logging & Replay — structured, async, privacy-safe.

Every conversation turn is recorded to two artifacts under
``data/conversation_logs/``:

- one JSON file per conversation
  (``conversation_2026-08-02T20-35-11_<user>.json``) with full metadata
  and per-turn records — the source of truth for replay and analysis;
- one Markdown transcript per day
  (``conversation_2026-08-02.md``) with the human-readable turn format.

Design rules (per the logging spec):

- never blocks response generation: file IO happens on a single daemon
  writer thread behind a queue (a full queue degrades to a synchronous
  write instead of dropping data);
- never overwrites: each conversation gets its own timestamped file;
  the day transcript is append-only;
- never stores secrets: values under sensitive keys are masked before
  any serialization (see ``_SECRET_KEY_RE``);
- never breaks the conversation: all public methods are wrapped by the
  caller in try/except and the logger itself never raises.

The Orchestrator owns the payload (it knows the planner, memory, pillar);
this module only formats and persists it. It imports nothing from the
runtime modules directly — payloads are built from plain dicts so the
logger stays reusable and untestable-free of the runtime graph.
"""

import atexit
import json
import os
import queue
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .utils.storage import now_iso, save_json

# ─── constants ─────────────────────────────────────────────────────────

DEFAULT_LOG_DIR = Path(__file__).resolve().parent.parent / "data" / "conversation_logs"

PLANNER_VERSION = "2.0"            # docs/specifications/CONVERSATION_PLANNER_V2.md.md (Version 2.0)
INTENT_RESOLVER_VERSION = "2.0.0"  # runtime/intent_resolver.py engine metadata
RUNTIME_VERSION = "1.0.0"          # runtime/conversation_runtime.py

# Real pipeline engines (infrastructure "runtime" merges are summarized
# in context_changes, not listed as engine executions).
_ENGINE_EXECUTION_IDS = ("intent_resolver", "conversation", "persistence")

_SECRET_KEY_RE = re.compile(
    r"(api[_-]?key|apikey|(?:access|auth|refresh)?[_-]?token\b|secret|"
    r"password|passwd|authorization|private[_-]?key|credential|bearer|"
    r"groq[_-]?key|openai[_-]?key)",
    re.IGNORECASE,
)

_JSON_INDENT = 2
_MD_SEPARATOR = "-----------------------------------"


def _json_default(o):
    """Serialize non-JSON-native values (enums, datetimes, dataclasses)."""
    if hasattr(o, "to_dict"):
        return o.to_dict()
    if hasattr(o, "value"):
        return o.value
    return str(o)


def mask_secrets(obj):
    """Recursively redact values under sensitive key names (privacy rule).

    Applied to the assembled payload before any file write, so API keys,
    tokens and credentials can never reach disk.
    """
    if isinstance(obj, dict):
        return {
            k: ("***" if _SECRET_KEY_RE.search(str(k)) else mask_secrets(v))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [mask_secrets(v) for v in obj]
    if isinstance(obj, tuple):
        return [mask_secrets(v) for v in obj]
    return obj


def _git_commit():
    """Current repo HEAD (cached); 'unknown' when git is unavailable."""
    if _git_commit.value is not None:
        return _git_commit.value
    try:
        root = Path(__file__).resolve().parent.parent
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(root), capture_output=True, text=True, timeout=5,
        )
        _git_commit.value = out.stdout.strip() or "unknown"
    except Exception:  # noqa: BLE001 — logging must never raise
        _git_commit.value = "unknown"
    return _git_commit.value


_git_commit.value = None  # type: ignore[attr-defined]


def _compact(value):
    """Bound the size of before/after snapshots in context_changes.

    Values that are not JSON-native (dataclasses, enums, ...) are reduced
    to a summary so the writer can always serialize the document.
    """
    if isinstance(value, dict):
        return {"keys": sorted(value.keys()), "size": len(json.dumps(
            value, default=_json_default))}
    if isinstance(value, (list, tuple)):
        return {"count": len(value), "size": len(json.dumps(
            value, default=_json_default))}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "__dataclass_fields__"):
        return {"type": type(value).__name__, "value": str(value)}
    if hasattr(value, "value"):
        return {"type": type(value).__name__, "value": str(getattr(value, "value"))}
    return {"type": type(value).__name__, "value": str(value)}


def _diag_dict(diag):
    return {"level": getattr(diag, "level", "info"),
            "code": getattr(diag, "code", ""),
            "engine": getattr(diag, "engine", ""),
            "message": getattr(diag, "message", "")}


def _event_dict(ev):
    return {"type": getattr(ev, "event_type", ""),
            "engine": getattr(ev, "engine_id", ""),
            "at": getattr(ev, "timestamp", ""),
            "message": getattr(ev, "message", "")}


@dataclass
class _ConversationState:
    """Per-conversation writer state (mutated only by the writer thread)."""

    conversation_id: str
    json_path: Path
    md_path: Path
    started_at: str
    turns: List[dict] = field(default_factory=list)
    prev_slots: dict = field(default_factory=dict)
    prev_buttons: Optional[list] = None
    prev_mode: Optional[str] = None
    ended: bool = False


class ConversationLogger:
    """Asynchronous conversation logger: JSON per conversation + Markdown per day.

    One process-wide instance is shared by every Orchestrator (see
    ``get_conversation_logger()``), so all writes are serialized on a
    single writer thread. The logger is deliberately generic: it accepts
    already-built turn payloads and never imports the runtime modules.
    """

    def __init__(self, log_dir=None, queue_size=10000):
        self.log_dir = Path(log_dir or os.environ.get(
            "WELLNESS_CONVERSATION_LOG_DIR") or DEFAULT_LOG_DIR)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._queue: "queue.Queue" = queue.Queue(maxsize=queue_size)
        self._conversations: Dict[str, _ConversationState] = {}
        self._alive = True
        self._writer = threading.Thread(
            target=self._writer_loop, name="conversation-logger",
            daemon=True)
        self._writer.start()
        atexit.register(self.close)

    # ─── public API (callable from any thread) ────────────────────────

    def record_runtime_turn(self, context, orch=None, response_time_ms=0.0):
        """Record one turn from a RuntimeContext (+ the owning Orchestrator).

        Builds the payload, then hands it to ``record_turn``. Never raises:
        logging must never affect response generation.
        """
        try:
            payload = build_turn_payload(context, orch=orch,
                                         response_time_ms=response_time_ms)
            return self.record_turn(payload)
        except Exception:  # noqa: BLE001 — logging must never break a turn
            return False

    def record_turn(self, payload):
        """Record one already-built turn payload (async). Never raises."""
        try:
            self._enqueue(("turn", payload))
        except Exception:  # noqa: BLE001 — logging must never break a turn
            return False
        return True

    def end_conversation(self, conversation_id):
        """Mark a conversation ended (final ended_at, then close the file)."""
        try:
            self._enqueue(("end", str(conversation_id)))
        except Exception:  # noqa: BLE001
            return False
        return True

    def flush(self, timeout=30.0):
        """Wait until all queued turns are on disk (test/atexit hook)."""
        if not self._alive:
            return
        done = threading.Event()
        try:
            self._queue.put(("flush", done), timeout=10)
        except queue.Full:
            return
        done.wait(timeout)

    def close(self):
        """Flush remaining work and stop the writer thread."""
        if not self._alive:
            return
        try:
            self._queue.put(("close", None), timeout=10)
        except queue.Full:
            pass
        self._writer.join(timeout=30)
        self._alive = False
        try:
            atexit.unregister(self.close)
        except Exception:  # noqa: BLE001
            pass

    def _enqueue(self, item):
        try:
            self._queue.put_nowait(item)
        except queue.Full:
            # Never drop data: degrade to a synchronous write.
            if item[0] == "turn":
                self._write_turn(item[1])

    # ─── writer thread ─────────────────────────────────────────────────

    def _writer_loop(self):
        while True:
            item = self._queue.get()
            kind = item[0]
            if kind == "close":
                self._queue.task_done()
                return
            if kind == "flush":
                self._queue.task_done()
                item[1].set()
                continue
            try:
                if kind == "turn":
                    self._write_turn(item[1])
                elif kind == "end":
                    self._end_conversation(item[1])
            except Exception:  # noqa: BLE001 — one bad record never kills logging
                self._queue.task_done()
                continue
            self._queue.task_done()

    def _state_for(self, payload):
        cid = payload["conversation_id"]
        state = self._conversations.get(cid)
        if state is None or state.ended:
            started_at = payload.get("timestamp") or now_iso()
            state = _ConversationState(
                conversation_id=cid,
                json_path=self._json_path(cid, started_at),
                md_path=self._md_path(started_at),
                started_at=started_at,
            )
            self._conversations[cid] = state
        return state

    def _json_path(self, conversation_id, started_at):
        stamp = started_at[:19].replace(":", "-")
        path = self.log_dir / f"conversation_{stamp}_{conversation_id}.json"
        if not path.exists():
            return path
        n = 1
        while path.exists():
            path = self.log_dir / f"conversation_{stamp}_{conversation_id}_{n}.json"
            n += 1
        return path

    def _md_path(self, started_at):
        return self.log_dir / f"conversation_{started_at[:10]}.md"

    def _write_turn(self, payload):
        state = self._state_for(payload)
        turn = self._build_turn_record(state, payload)
        state.turns.append(turn)
        state.prev_slots = turn["slots_after"] or {}
        state.prev_buttons = turn["buttons_shown"]
        state.prev_mode = turn["planner_mode"]
        self._write_json(state)
        self._write_markdown(state, turn)

    def _end_conversation(self, conversation_id):
        state = self._conversations.get(conversation_id)
        if state is None or state.ended:
            return
        state.ended = True
        self._write_json(state)  # final ended_at
        self._conversations.pop(conversation_id, None)

    def _write_json(self, state):
        document = {
            "metadata": self._metadata(state),
            "turns": state.turns,
        }
        save_json(state.json_path, mask_secrets(document))

    def _write_markdown(self, state, turn):
        try:
            with open(state.md_path, "a", encoding="utf-8") as f:
                f.write(_render_markdown_turn(
                    state, turn, include_header=len(state.turns) == 1))
        except OSError:
            pass  # transcript is a convenience; JSON remains the source of truth

    def _metadata(self, state):
        return {
            "conversation_id": state.conversation_id,
            "started_at": state.started_at,
            "ended_at": state.turns[-1]["timestamp"] if state.turns
            else state.started_at,
            "user_id": state.conversation_id,
            "runtime_version": RUNTIME_VERSION,
            "planner_version": PLANNER_VERSION,
            "intent_resolver_version": INTENT_RESOLVER_VERSION,
            "branch_manager_version": "n/a",  # no branch_manager engine registered
            "git_commit": _git_commit(),
            "total_turns": len(state.turns),
        }

    # ─── record assembly ───────────────────────────────────────────────

    def _build_turn_record(self, state, payload):
        turn = payload["turn"]
        ig = payload.get("intent_graph") or {}
        decision = payload.get("planner_decision") or {}
        primary = ig.get("primary_intent") or {}
        secondaries = ig.get("secondary_intents") or []
        backgrounds = ig.get("background_intents") or []

        detected = [primary.get("intent")]
        detected += [i.get("intent") for i in secondaries]
        detected += [i.get("intent") for i in backgrounds]
        detected = [d for d in detected if d]

        conf_scores = {"primary": {"intent": primary.get("intent"),
                                   "confidence": primary.get("confidence")},
                       "overall_confidence": ig.get("overall_confidence")}
        for sec in secondaries:
            conf_scores.setdefault("secondary", {})[sec.get("intent")] = \
                sec.get("confidence")

        # Slots: prefer explicit intent slot_updates (the knowledge-engine
        # slot_graph is not registered in this pipeline); fall back to the
        # graph's slots field, then the runtime slot_graph.
        slot_updates = []
        for intent in ([primary] + list(secondaries) + list(backgrounds)):
            slot_updates += list(intent.get("slot_updates") or [])
        slots = {su.get("slot"): su.get("value") for su in slot_updates}
        if not slots:
            slots = (ig.get("slots") or payload.get("slot_graph") or {})
        if not isinstance(slots, dict):
            slots = {}

        mode_before = state.prev_mode
        mode_after = decision.get("mode")
        action = decision.get("action")
        buttons = payload.get("buttons_shown")
        # A click can only target buttons shown in the PREVIOUS turn.
        button_clicked = self._match_button(state.prev_buttons,
                                            payload.get("raw_user_input"))

        record = {
            "timestamp": payload.get("timestamp"),
            "conversation_id": state.conversation_id,
            "turn_number": len(state.turns) + 1,
            "user_message": turn.get("user_message"),
            "raw_user_input": payload.get("raw_user_input"),
            "detected_intents": detected,
            "intent_graph": ig,
            "confidence_scores": conf_scores,
            "intent": {
                "primary": primary.get("intent"),
                "secondary": [s.get("intent") for s in secondaries],
                "confidence": primary.get("confidence"),
            },
            "active_branch": payload.get("active_branch"),
            "planner": {
                "mode_before": mode_before,
                "mode_after": mode_after,
                "selected_action": action,
                "reason": decision.get("reason"),
                "confidence": decision.get("confidence"),
            },
            "planner_mode": mode_after,
            "planner_action": action,
            "planner_reason": decision.get("reason"),
            "runtime_state": payload.get("runtime_state"),
            "runtime_context": payload.get("runtime_context"),
            "engine_execution_order": payload.get("engine_execution_order"),
            "engine_updates": payload.get("engine_updates"),
            "context_changes": payload.get("context_changes"),
            "slots_before": state.prev_slots,
            "slots_after": slots,
            "memory_used": payload.get("memory_used"),
            "recommendation_generated": payload.get(
                "recommendation_generated", False),
            "top_recommendation": payload.get("top_recommendation"),
            "buttons_shown": buttons,
            "button_clicked": button_clicked,
            "ai_response": turn.get("response"),
            "response_time_ms": payload.get("response_time_ms"),
            "diagnostics": payload.get("diagnostics"),
            "warnings": payload.get("warnings"),
            # extra review context (record everything, never secrets):
            "emotion": turn.get("emotion"),
            "risk_detected": turn.get("risk_detected"),
            "state": turn.get("state"),
            "route": turn.get("route"),
            "objective": turn.get("objective"),
            "planner_decision": decision,
            "self_evaluation": turn.get("self_evaluation"),
            "confirmation": turn.get("confirmation"),
            "judge": turn.get("judge"),
            "reasoning_context": turn.get("reasoning_context"),
            "memory_updates": turn.get("memory_updates"),
            "behaviors": turn.get("behaviors"),
            "beliefs": turn.get("beliefs"),
            "hypotheses": turn.get("hypotheses"),
            "whys": turn.get("whys"),
            "llm_used": turn.get("llm_used"),
        }
        return mask_secrets(record)

    @staticmethod
    def _match_button(buttons, raw_input):
        if not buttons or not raw_input:
            return None
        msg = str(raw_input).strip().lower()
        for b in buttons:
            if str(b).strip().lower() == msg:
                return b
        return None


# ─── payload builder (Orchestrator-provided runtime context) ──────────

def build_turn_payload(context, orch=None, response_time_ms=0.0):
    """Assemble the raw turn payload from a RuntimeContext + Orchestrator.

    All reads are getattr-guarded so the logger works against any
    context-shaped object without importing the runtime graph.
    """
    request = getattr(context, "request", None)
    conversation = getattr(context, "conversation", None)
    metrics = getattr(context, "metrics", None)
    diagnostics = getattr(context, "diagnostics", None)

    turn = {}
    if conversation is not None:
        turn = dict(getattr(conversation, "turn", {}) or {})
    ig = {}
    if conversation is not None:
        ig = dict(getattr(conversation, "intent_graph", {}) or {})

    history = list(getattr(context, "history", ()) or ())

    # engine execution order (real pipeline engines only)
    exec_order = [getattr(h, "engine_id", "") for h in history
                  if getattr(h, "engine_id", "") in _ENGINE_EXECUTION_IDS]

    # compact engine updates
    engine_updates = []
    for h in history:
        eid = getattr(h, "engine_id", "")
        if eid not in _ENGINE_EXECUTION_IDS:
            continue
        update = getattr(h, "update", None)
        data = dict(getattr(update, "data", {}) or {}) if update else {}
        engine_updates.append({
            "engine": eid,
            "version": getattr(h, "version", 0),
            "changed_fields": sorted(data.keys()),
            "diagnostics": [_diag_dict(d) for d in
                            (getattr(h, "diagnostics", ()) or ())],
        })

    # every RuntimeContext change: before/after/changed_fields per merge
    context_changes = []
    for h in history:
        update = getattr(h, "update", None)
        data = dict(getattr(update, "data", {}) or {}) if update else {}
        before = {}
        after = {}
        for key, value in data.items():
            if key == "turn":  # full turn already logged per-turn
                before[key] = "(previous turn, see turn list)"
                after[key] = "(this turn, see above)"
                continue
            before[key] = _compact(_field_history(history, h, key))
            after[key] = _compact(value)
        context_changes.append({
            "version": getattr(h, "version", 0),
            "engine": getattr(h, "engine_id", ""),
            "timestamp": getattr(h, "timestamp", ""),
            "changed_fields": sorted(data.keys()),
            "before": before,
            "after": after,
        })

    runtime_events = []
    if diagnostics is not None:
        runtime_events = [_event_dict(e) for e in
                          (getattr(diagnostics, "events", ()) or ())]

    warnings = []
    if diagnostics is not None:
        warnings = [str(w) for w in
                    (getattr(diagnostics, "warnings", ()) or ())]

    memory_used = {}
    ranked = []
    if orch is not None:
        memory = getattr(getattr(orch, "agents", None), "memory", None)
        if memory is not None:
            try:
                facts = memory.get_all_facts() or []
                memory_used = {
                    "facts_total": len(facts),
                    "top_facts": [
                        {k: f.get(k) for k in
                         ("category", "key", "value", "confidence")}
                        for f in facts[-10:]
                    ],
                    "trust_score": memory.get_trust_score(),
                }
            except Exception:  # noqa: BLE001
                memory_used = {"facts_total": 0, "top_facts": [],
                               "trust_score": None}
        ranked = getattr(orch, "_ranked_interventions", None) or []

    top_rec = None
    if ranked and isinstance(ranked[0], dict):
        top_rec = {k: ranked[0].get(k) for k in
                   ("action", "confidence", "urgency", "category")}

    engine_latency = {}
    if metrics is not None:
        engine_latency = dict(getattr(metrics, "engine_latency", {}) or {})

    lifecycle = getattr(context, "lifecycle", None)
    runtime_version = getattr(getattr(context, "metadata", None),
                              "runtime_version", RUNTIME_VERSION)

    return {
        "conversation_id": getattr(request, "conversation_id", "") or
                           getattr(request, "user_id", ""),
        "timestamp": getattr(request, "timestamp", "") or now_iso(),
        "raw_user_input": getattr(request, "message", ""),
        "turn": turn,
        "intent_graph": ig,
        "slot_graph": dict(getattr(conversation, "slot_graph", {}) or {}),
        "active_branch": (getattr(orch, "current_pillar", None)
                          or (getattr(conversation, "active_branch", "") or "")),
        "planner_decision": (turn.get("planner_decision") or {}),
        "runtime_state": lifecycle.value if lifecycle is not None else "",
        "runtime_context": {
            "version": getattr(context, "version", 0),
            "request_id": getattr(request, "request_id", ""),
            "session_id": getattr(request, "session_id", ""),
            "trace_id": getattr(getattr(context, "metadata", None),
                                "trace_id", ""),
            "runtime_version": runtime_version,
        },
        "engine_execution_order": exec_order,
        "engine_updates": engine_updates,
        "context_changes": context_changes,
        "diagnostics": {"events": runtime_events,
                        "engine_latency_ms": engine_latency},
        "warnings": warnings,
        "memory_used": memory_used,
        "recommendation_generated": bool(ranked),
        "top_recommendation": top_rec,
        "buttons_shown": turn.get("options"),
        "response_time_ms": round(float(response_time_ms or 0.0), 2),
    }


def _field_history(history, entry, key):
    """Value of `key` as of the entry BEFORE `entry` (or None)."""
    for h in reversed(history):
        if h is entry:
            continue
        data = getattr(getattr(h, "update", None), "data", None)
        if data and key in data:
            return data[key]
    return None


# ─── markdown rendering ────────────────────────────────────────────────

def _render_markdown_turn(state, turn, include_header=False):
    lines = []
    if include_header:
        lines += ["# Conversation", "", ""]
    lines += [
        f"## Turn {turn['turn_number']}",
        "",
        "User:",
        turn.get("user_message") or "(empty)",
        "",
        "Intent:",
        _md_intent_line(turn),
        "",
        "Planner Mode:",
        turn.get("planner_mode") or "(none)",
        "",
        "Planner Action:",
        turn.get("planner_action") or "(none)",
        "",
        "Reason:",
        turn.get("planner_reason") or "(none)",
        "",
        "Buttons:",
    ]
    buttons = turn.get("buttons_shown")
    if buttons:
        lines += [f"- {b}" for b in buttons]
    else:
        lines.append("(none)")
    if turn.get("button_clicked"):
        lines += ["", f"Clicked: {turn['button_clicked']}"]
    lines += [
        "",
        "Assistant:",
        turn.get("ai_response") or "(empty)",
        "",
        _MD_SEPARATOR,
        "",
        "",
    ]
    return "\n".join(lines)


def _md_intent_line(turn):
    parts = []
    primary = (turn.get("intent") or {}).get("primary")
    conf = (turn.get("intent") or {}).get("confidence")
    if primary:
        parts.append(f"{primary} ({conf})" if conf is not None else primary)
    secondary = (turn.get("intent") or {}).get("secondary") or []
    if secondary:
        parts.append("secondary: " + ", ".join(str(s) for s in secondary))
    if not parts:
        return "(none)"
    return " | ".join(parts)


# ─── singleton ─────────────────────────────────────────────────────────

_LOGGER_INSTANCE = None
_LOGGER_LOCK = threading.Lock()


def get_conversation_logger():
    """Process-wide logger shared by every Orchestrator (single writer)."""
    global _LOGGER_INSTANCE
    if _LOGGER_INSTANCE is None or not _LOGGER_INSTANCE._alive:
        with _LOGGER_LOCK:
            if _LOGGER_INSTANCE is None or not _LOGGER_INSTANCE._alive:
                _LOGGER_INSTANCE = ConversationLogger()
    return _LOGGER_INSTANCE


__all__ = [
    "ConversationLogger",
    "DEFAULT_LOG_DIR",
    "build_turn_payload",
    "get_conversation_logger",
    "mask_secrets",
]
