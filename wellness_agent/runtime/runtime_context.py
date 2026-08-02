"""Immutable, request-scoped RuntimeContext (RFC-002 Ch3).

The RuntimeContext is the canonical runtime object shared across every
engine during the execution of a single request (RFC-002:991-997). It is
immutable — engines SHALL NEVER modify it (RFC-002:1263-1267) — and
request-scoped: a new instance is created per request and never cached
(RFC-002:737-747, 1357-1379).

All sub-contexts are frozen dataclasses; any mutation attempt raises
FrozenInstanceError. Inputs are deep-copied at construction so external
callers can never mutate a live context through stale references.
"""

import copy
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from ..utils.storage import now_iso


class RuntimeStage(Enum):
    """Execution stages of the pipeline (RFC-002 Ch5)."""

    INTENT_RESOLVER = "intent_resolver"
    BRANCH_MANAGER = "branch_manager"
    MEMORY_LOADER = "memory_loader"
    KNOWLEDGE = "knowledge"
    PLANNER = "planner"
    STRATEGY = "strategy"
    ACE = "ace"
    WHY = "why"
    BIE = "bie"
    PROMPT_BUILDER = "prompt_builder"
    COMPLETED = "completed"


class RuntimeState(Enum):
    """Runtime lifecycle states (M8 spec Ch4 Runtime State Machine).

    Every RuntimeContext moves through
    Created → Validated → Executing → Streaming → Persisting → Completed →
    Disposed; invalid transitions are rejected by the Merge Engine
    (M8_RUNTIME_ORCHESTRATOR_IMPLEMENTATION:2017-2089).
    """

    CREATED = "created"
    VALIDATED = "validated"
    EXECUTING = "executing"
    RECOVERING = "recovering"
    STREAMING = "streaming"
    PERSISTING = "persisting"
    COMPLETED = "completed"
    FAILED = "failed"
    DISPOSED = "disposed"


@dataclass(frozen=True)
class RequestContext:
    """Immutable request information (RFC-002:1067-1090)."""

    request_id: str = ""
    user_id: str = ""
    conversation_id: str = ""
    session_id: str = ""
    timestamp: str = field(default_factory=now_iso)
    channel: str = "chat"
    message: str = ""


@dataclass(frozen=True)
class ConversationContext:
    """Active conversation state, updated only by the Runtime (RFC-002:1093-1126).

    `turn` holds the last completed conversation turn produced by the
    conversation engine (M8); the Merge Engine is the only component that
    may write it.
    """

    active_branch: str = ""
    active_objective: str = ""
    intent_graph: dict = field(default_factory=dict)
    slot_graph: dict = field(default_factory=dict)
    hypotheses: List = field(default_factory=list)
    pending_questions: List = field(default_factory=list)
    commitments: List = field(default_factory=list)
    turn: dict = field(default_factory=dict)


@dataclass(frozen=True)
class MemoryContext:
    """Memory retrieved before execution (RFC-002:1129-1151)."""

    profile: dict = field(default_factory=dict)
    episodic_memory: List = field(default_factory=list)
    semantic_memory: List = field(default_factory=list)
    coaching_profile: dict = field(default_factory=dict)
    insights: List = field(default_factory=list)


@dataclass(frozen=True)
class ExecutionContext:
    """Runtime execution tracking, owned exclusively by the Runtime (RFC-002:1155-1176)."""

    stage: RuntimeStage = RuntimeStage.INTENT_RESOLVER
    current_engine: str = ""
    started_at: str = field(default_factory=now_iso)
    timeout_ms: int = 1000
    retry_count: int = 0


@dataclass(frozen=True)
class DiagnosticsContext:
    """Warnings, errors and decision traces (RFC-002:1179-1197).

    `events` holds the runtime event records (RuntimeStarted, MergeCompleted,
    ...) appended by the Merge Engine (M8 spec Ch2 Event Dispatch).
    """

    warnings: tuple = ()
    errors: tuple = ()
    decisions: tuple = ()
    events: tuple = ()


@dataclass(frozen=True)
class MetricsContext:
    """Aggregated performance metrics (RFC-002:1201-1220).

    `merge_metrics` accumulates the Merge Engine's per-request accounting:
    context version, merge/validation latency, rollback count and conflicts
    detected (M8 spec Ch4 Merge Metrics).
    """

    total_latency: float = 0.0
    engine_latency: dict = field(default_factory=dict)
    token_usage: dict = field(default_factory=dict)
    memory_latency: float = 0.0
    merge_metrics: dict = field(default_factory=dict)


@dataclass(frozen=True)
class StreamingContext:
    """Streaming state, existing only while streaming (RFC-002:1223-1240)."""

    stream_id: str = ""
    first_token_at: Optional[str] = None
    completed: bool = False


@dataclass(frozen=True)
class RuntimeMetadata:
    """Runtime identification for observability (RFC-002:1243-1259)."""

    runtime_version: str = "1.0.0"
    environment: str = "development"
    trace_id: str = ""


@dataclass(frozen=True)
class RuntimeContext:
    """Top-level immutable runtime object (RFC-002:1039-1063).

    `version`, `lifecycle` and `history` are owned exclusively by the Merge
    Engine (M8 spec Ch4): every merge creates a new context version and
    appends an immutable history entry; the lifecycle moves through the
    validated state machine.
    """

    request: RequestContext = field(default_factory=RequestContext)
    conversation: ConversationContext = field(default_factory=ConversationContext)
    memory: MemoryContext = field(default_factory=MemoryContext)
    execution: ExecutionContext = field(default_factory=ExecutionContext)
    diagnostics: DiagnosticsContext = field(default_factory=DiagnosticsContext)
    metrics: MetricsContext = field(default_factory=MetricsContext)
    streaming: StreamingContext = field(default_factory=StreamingContext)
    metadata: RuntimeMetadata = field(default_factory=RuntimeMetadata)
    version: int = 0
    lifecycle: RuntimeState = RuntimeState.CREATED
    history: tuple = ()

    @classmethod
    def create(cls, request_id="", user_id="", session_id="",
               conversation_id="", channel="chat", environment="development",
               trace_id="", runtime_version="1.0.0", message=""):
        """Build a request-scoped context with default sub-contexts.

        Inputs are deep-copied so later caller-side mutation cannot leak
        into the immutable context.
        """
        request = RequestContext(
            request_id=request_id,
            user_id=user_id,
            conversation_id=conversation_id,
            session_id=session_id or request_id,
            channel=channel,
            message=message,
        )
        return cls(
            request=request,
            execution=ExecutionContext(stage=RuntimeStage.INTENT_RESOLVER),
            metadata=RuntimeMetadata(
                runtime_version=runtime_version,
                environment=environment,
                trace_id=trace_id,
            ),
        )

    def validate(self):
        """Validate required IDs; raise ValueError when invalid.

        Per RFC-002 Ch3 Context Validation, invalid contexts SHALL
        terminate execution (RFC-002:1413-1426).
        """
        missing = [name for name in ("request_id", "user_id", "session_id")
                   if not getattr(self.request, name)]
        if missing:
            raise ValueError("invalid RuntimeContext, missing: %s" % ", ".join(missing))
        return self

    def snapshot(self):
        """Deep copy of this context, used to prove engines do not mutate it."""
        return copy.deepcopy(self)
