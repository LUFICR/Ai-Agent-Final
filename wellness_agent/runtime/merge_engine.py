"""RuntimeContext Merge Engine (M8 spec Ch4, ADR-M8-004).

The Merge Engine is the ONLY component permitted to modify a RuntimeContext.
Every reasoning engine produces an immutable EngineUpdate; this engine
combines those updates into a NEW immutable RuntimeContext while:

- enforcing field ownership (each context field has exactly one owner)
- detecting conflicts and rejecting unauthorized writes
- validating the new context before adoption (invalid contexts never continue)
- preserving an immutable merge history with snapshots for replay
- supporting rollback (snapshots are immutable, so rollback never restores a
  partially merged state — a failed merge simply is never adopted)
- enforcing the runtime state machine
  (Created → Validated → Executing → Streaming → Persisting → Completed →
  Disposed; invalid transitions are rejected)

The Merge Engine contains no shared mutable state: every merge is a pure
function of (context, update), so concurrent conversations stay isolated
(M8 spec Ch4 Thread Safety).
"""

import copy
import time
from dataclasses import dataclass, field, replace

from ..utils.storage import now_iso
from .diagnostics import Diagnostic
from .engine_update import EngineUpdate
from .runtime_context import (
    ConversationContext,
    DiagnosticsContext,
    ExecutionContext,
    MetricsContext,
    RequestContext,
    RuntimeContext,
    RuntimeState,
    StreamingContext,
)


class MergeError(RuntimeError):
    """Raised for invalid merges, unauthorized writes and invalid transitions."""


@dataclass(frozen=True)
class RuntimeEvent:
    """A runtime event record for observability (M8 spec Ch2 Event Dispatch)."""

    event_type: str
    engine_id: str = ""
    timestamp: str = field(default_factory=now_iso)
    message: str = ""


@dataclass(frozen=True)
class MergeHistoryEntry:
    """One immutable entry of the merge history (M8 spec Ch4 Context History).

    Preserves version, timestamp, originating engine, the applied update,
    diagnostics and a post-merge snapshot for replay and debugging.
    """

    version: int
    timestamp: str
    engine_id: str
    update: EngineUpdate
    snapshot: RuntimeContext
    diagnostics: tuple = ()


@dataclass(frozen=True)
class MergeSummary:
    """Per-merge accounting (M8 spec Ch4 Merge Metrics)."""

    version: int
    merge_latency_ms: float
    validation_latency_ms: float
    rollback_count: int = 0
    conflicts_detected: int = 0


@dataclass(frozen=True)
class MergeResult:
    """Outcome of a single merge.

    A rejected merge (conflict or failed validation) returns the previous
    context untouched with `ok=False` and `rolled_back=True` — a rollback
    can never expose partially merged state because the previous context is
    immutable and simply remains in effect.
    """

    context: RuntimeContext
    summary: MergeSummary
    ok: bool = True
    rolled_back: bool = False


# Context Ownership (M8 spec Ch4): each runtime field has exactly one owner.
# Updates carrying fields outside the engine's ownership are rejected as
# conflicts.
_DEFAULT_OWNERSHIP = {
    "conversation": frozenset({"turn", "hypotheses", "pending_questions",
                               "commitments"}),
    "intent_resolver": frozenset({"intent_graph"}),
    "branch_manager": frozenset({"active_branch", "active_objective"}),
    "knowledge": frozenset({"slot_graph"}),
    "runtime": frozenset({"streaming", "execution", "metrics"}),
    "persistence": frozenset(),
}

_CONVERSATION_FIELD_TYPES = {
    "turn": dict,
    "hypotheses": list,
    "pending_questions": list,
    "commitments": list,
    "intent_graph": dict,
    "slot_graph": dict,
}

# Runtime State Machine (M8 spec Ch4 State Transition Rules).
_TRANSITIONS = {
    RuntimeState.CREATED: {RuntimeState.VALIDATED},
    RuntimeState.VALIDATED: {RuntimeState.EXECUTING, RuntimeState.FAILED},
    RuntimeState.EXECUTING: {RuntimeState.STREAMING, RuntimeState.RECOVERING,
                             RuntimeState.FAILED},
    RuntimeState.RECOVERING: {RuntimeState.EXECUTING, RuntimeState.COMPLETED,
                              RuntimeState.FAILED},
    RuntimeState.STREAMING: {RuntimeState.PERSISTING, RuntimeState.FAILED},
    RuntimeState.PERSISTING: {RuntimeState.COMPLETED, RuntimeState.FAILED},
    RuntimeState.COMPLETED: {RuntimeState.DISPOSED},
    RuntimeState.FAILED: {RuntimeState.DISPOSED},
    RuntimeState.DISPOSED: frozenset(),
}

# Contexts that must never accept further merges.
_TERMINAL_LIFECYCLES = frozenset({RuntimeState.CREATED, RuntimeState.COMPLETED,
                                  RuntimeState.DISPOSED})

_TOP_LEVEL_FIELDS = {"streaming": StreamingContext, "execution": ExecutionContext,
                     "metrics": MetricsContext}


class ContextMergeEngine:
    """Centralized RuntimeContext mutation and state transition authority.

    Stateless by construction: all mutable state lives inside the immutable
    RuntimeContext (version, lifecycle, history, diagnostics, metrics), so a
    single engine instance may serve many concurrent runtime instances
    (M8 spec Ch4 Thread Safety).
    """

    def __init__(self, ownership=None):
        self._ownership = dict(ownership if ownership is not None
                               else _DEFAULT_OWNERSHIP)

    # ─── ownership ──────────────────────────────────────────────

    def owned_fields(self, engine_id) -> frozenset:
        return self._ownership.get(engine_id, frozenset())

    # ─── state machine (M8 spec Ch4) ────────────────────────────

    def transition(self, context: RuntimeContext,
                   target: RuntimeState) -> RuntimeContext:
        """Move the context to `target`; reject invalid transitions."""
        allowed = _TRANSITIONS.get(context.lifecycle, frozenset())
        if target not in allowed:
            raise MergeError(
                "invalid state transition %s -> %s"
                % (context.lifecycle.value, target.value))
        return replace(context, lifecycle=target)

    # ─── merge (M8 spec Ch4 Merge Process) ──────────────────────

    def merge(self, context: RuntimeContext, update: EngineUpdate,
              engine_id: str, events=()) -> MergeResult:
        """Apply an EngineUpdate, producing a new immutable context version.

        Sequence (M8 spec Ch4): validate update → validate current context →
        apply merge → validate new context → store snapshot → return.
        """
        started = time.perf_counter()
        events = list(events)
        events.append(RuntimeEvent("MergeStarted", engine_id,
                                   message="engine '%s' update" % engine_id))

        if not isinstance(update, EngineUpdate):
            raise MergeError("merge received a non-EngineUpdate: %r"
                             % type(update).__name__)
        if context.lifecycle in _TERMINAL_LIFECYCLES:
            raise MergeError("context %s cannot accept merges"
                             % context.lifecycle.value)
        try:
            context.validate()
        except ValueError as exc:
            raise MergeError("cannot merge into invalid context: %s" % exc) from exc

        data = update.data if update.data is not None else {}
        if not isinstance(data, dict):
            raise MergeError("engine '%s' update data must be a dict" % engine_id)

        validation_latency = round(
            (time.perf_counter() - started) * 1000, 3)

        # Ownership check: reject writes to fields owned by other engines.
        owned = self.owned_fields(engine_id)
        unowned = [key for key in data if key not in owned]
        if unowned:
            return self._reject(
                context, engine_id, events, started, validation_latency,
                conflict="engine '%s' wrote unowned fields: %s"
                         % (engine_id, ", ".join(sorted(unowned))))

        # Type validation of owned fields.
        bad = [key for key in data
               if key in _CONVERSATION_FIELD_TYPES
               and not isinstance(data[key], _CONVERSATION_FIELD_TYPES[key])]
        if bad:
            return self._reject(
                context, engine_id, events, started, validation_latency,
                conflict="engine '%s' produced invalid field types: %s"
                         % (engine_id, ", ".join(sorted(bad))))

        # Apply: build a brand-new context (the old one stays immutable).
        merge_latency = round((time.perf_counter() - started) * 1000, 3)
        events.append(RuntimeEvent("MergeCompleted", engine_id,
                                   message="context v%d created"
                                           % (context.version + 1)))
        new_context = self._apply(context, update, engine_id, merge_latency,
                                  events)
        # Validate the new context; an invalid context never continues.
        try:
            new_context.validate()
        except ValueError as exc:
            return self._reject(
                context, engine_id, events, started, validation_latency,
                conflict="merged context failed validation: %s" % exc)

        rollbacks = new_context.metrics.merge_metrics.get("rollback_count", 0)
        conflicts = new_context.metrics.merge_metrics.get("conflicts_detected", 0)
        summary = MergeSummary(version=new_context.version,
                               merge_latency_ms=merge_latency,
                               validation_latency_ms=validation_latency,
                               rollback_count=rollbacks,
                               conflicts_detected=conflicts)
        return MergeResult(context=new_context, summary=summary, ok=True)

    # ─── internals ──────────────────────────────────────────────

    def _apply(self, context, update, engine_id, merge_latency, events) -> RuntimeContext:
        """Construct the merged context and record history/snapshot/metrics."""
        data = update.data or {}

        conversation = context.conversation
        conversation_keys = [k for k in data if k in _CONVERSATION_FIELD_TYPES]
        if conversation_keys:
            conversation = replace(
                context.conversation,
                **{k: data[k] for k in conversation_keys})

        top_level = {}
        for key, expected in _TOP_LEVEL_FIELDS.items():
            if key in data and isinstance(data[key], expected):
                top_level[key] = data[key]
        # `metrics` is always rebuilt by the merge; keep the others from data.
        top_level.pop("metrics", None)

        new_diagnostics = self._extend_diagnostics(context, update, events)
        merge_metrics = dict(context.metrics.merge_metrics)
        merge_metrics["merges"] = merge_metrics.get("merges", 0) + 1
        merge_metrics["version"] = context.version + 1
        merge_metrics["merge_latency_ms"] = merge_latency

        new_metrics = MetricsContext(
            total_latency=context.metrics.total_latency,
            engine_latency=dict(context.metrics.engine_latency),
            token_usage=dict(context.metrics.token_usage),
            memory_latency=context.metrics.memory_latency,
            merge_metrics=merge_metrics,
        )
        entry = MergeHistoryEntry(
            version=context.version + 1,
            timestamp=now_iso(),
            engine_id=engine_id,
            update=update,
            snapshot=None,  # replaced after constructing the new context
            diagnostics=tuple(update.diagnostics or ()),
        )
        new_context = replace(
            context,
            version=context.version + 1,
            conversation=conversation,
            diagnostics=new_diagnostics,
            metrics=new_metrics,
            history=context.history + (entry,),
            **top_level,
        )
        # Snapshot of the completed merge (replay/debug), stored immutable.
        entry = replace(entry, snapshot=copy.deepcopy(new_context))
        return replace(new_context, history=context.history + (entry,))

    def _extend_diagnostics(self, context, update, events):
        """Append update diagnostics/warnings and runtime events (merge rules:
        "append diagnostics" is always allowed)."""
        warnings = list(context.diagnostics.warnings)
        errors = list(context.diagnostics.errors)
        for diag in update.diagnostics or ():
            if diag.level == "error":
                errors.append(diag)
            else:
                warnings.append(diag)
        warnings.extend(update.warnings or ())
        return DiagnosticsContext(
            warnings=tuple(warnings),
            errors=tuple(errors),
            decisions=tuple(context.diagnostics.decisions),
            events=tuple(context.diagnostics.events) + tuple(events or ()),
        )

    def _reject(self, context, engine_id, events, started, validation_latency,
                conflict):
        """Conflict/validation failure: rollback and record diagnostics."""
        events.append(RuntimeEvent("ConflictDetected", engine_id,
                                   message=conflict))
        events.append(RuntimeEvent("MergeFailed", engine_id,
                                   message=conflict))
        events.append(RuntimeEvent("RollbackExecuted", engine_id,
                                   message="previous context restored"))
        merge_metrics = dict(context.metrics.merge_metrics)
        merge_metrics["rollback_count"] = merge_metrics.get("rollback_count", 0) + 1
        merge_metrics["conflicts_detected"] = (
            merge_metrics.get("conflicts_detected", 0) + 1)
        merge_metrics["version"] = context.version
        merge_latency = round((time.perf_counter() - started) * 1000, 3)
        merged_metrics = MetricsContext(
            total_latency=context.metrics.total_latency,
            engine_latency=dict(context.metrics.engine_latency),
            token_usage=dict(context.metrics.token_usage),
            memory_latency=context.metrics.memory_latency,
            merge_metrics=merge_metrics,
        )
        diag = DiagnosticsContext(
            warnings=tuple(context.diagnostics.warnings),
            errors=tuple(context.diagnostics.errors),
            decisions=tuple(context.diagnostics.decisions),
            events=tuple(context.diagnostics.events) + tuple(events),
        )
        summary = MergeSummary(version=context.version,
                               merge_latency_ms=merge_latency,
                               validation_latency_ms=validation_latency,
                               rollback_count=merge_metrics["rollback_count"],
                               conflicts_detected=merge_metrics["conflicts_detected"])
        rolled_back = replace(context, diagnostics=diag, metrics=merged_metrics)
        return MergeResult(context=rolled_back, summary=summary, ok=False,
                           rolled_back=True)


__all__ = [
    "ContextMergeEngine",
    "MergeError",
    "MergeHistoryEntry",
    "MergeResult",
    "MergeSummary",
    "RuntimeEvent",
    "Diagnostic",
    "RuntimeContext",
    "RuntimeState",
]
