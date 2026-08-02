"""RuntimeOrchestrator (M8 spec Ch2, ADR-M8-002).

The RuntimeOrchestrator is the central execution coordinator: it owns the
complete internal lifecycle of one request — state transitions, the
deterministic engine pipeline, update merging, streaming and persistence
coordination, events and metrics — while never performing AI reasoning
itself.

Per-request isolation (M8 spec Ch2 Thread Safety): every execution runs on
fresh dispatcher/collector instances against an immutable RuntimeContext,
so a single orchestrator instance can coordinate concurrent requests.
"""

import time
from dataclasses import dataclass, field, replace

from ..utils.storage import now_iso
from .engine_update import EngineUpdate
from .merge_engine import (
    ContextMergeEngine,
    MergeError,
    RuntimeEvent,
)
from .pipeline_executor import (
    PipelineError,
    PipelineExecutor,
    PipelineStage,
)
from .runtime_context import (
    ExecutionContext,
    MetricsContext,
    RuntimeContext,
    RuntimeStage,
    RuntimeState,
    StreamingContext,
)
from .runtime_engine import RetryPolicy

# Default reasoning pipeline (M8 spec Ch2 Engine Scheduling). The existing
# M8 contract (unchanged): the deterministic conversation flow is wrapped
# as ONE registered engine ("conversation") so behavior stays byte-identical.
# The AI Intelligence phase adds the Intent Resolver 2.0 stage through the
# Orchestrator's own pipeline definition (see Orchestrator._runtime_stages),
# keeping the runtime default identical to M8.
_DEFAULT_STAGES = (
    PipelineStage(
        id="conversation",
        engine_id="conversation",
        enabled=True,
        optional=False,
        timeout_ms=120000,
        retry_policy=RetryPolicy(enabled=False, max_retries=0),
        input_builder=lambda ctx: {"message": ctx.request.message},
    ),
)

_DEFAULT_PERSISTENCE_STAGE = PipelineStage(
    id="persistence",
    engine_id="persistence",
    enabled=True,
    optional=True,  # persistence failures never kill the conversation
    timeout_ms=15000,
    retry_policy=RetryPolicy(enabled=False, max_retries=2),
)


class RuntimeExecutionError(RuntimeError):
    """Raised when runtime execution cannot complete."""


@dataclass(frozen=True)
class RuntimeResult:
    """Immutable result of a runtime execution (M8 spec Ch2 Runtime Result)."""

    context: RuntimeContext
    response: object  # ConversationResponse (built by the response factory)
    metrics: MetricsContext
    diagnostics: object  # DiagnosticsContext


class EventDispatcher:
    """Per-request event collector (M8 spec Ch2 Event Dispatch).

    Events are emitted asynchronously (recorded, never blocking) and flushed
    into the context by the Merge Engine on the next merge.
    """

    def __init__(self):
        self._pending = []

    def emit(self, event_type, engine_id="", message=""):
        self._pending.append(RuntimeEvent(event_type, engine_id,
                                          message=message))

    def take(self):
        pending, self._pending = self._pending, []
        return pending


class MetricsCollector:
    """Per-request engine latency aggregation (M8 spec Ch2 Metrics Collection)."""

    def __init__(self):
        self._latencies = {}

    def record(self, engine_id, latency_ms):
        self._latencies[engine_id] = self._latencies.get(engine_id, 0.0) + latency_ms

    def update(self, context: RuntimeContext) -> MetricsContext:
        latencies = dict(context.metrics.engine_latency)
        latencies.update(self._latencies)
        total = round(sum(v for v in latencies.values()
                          if isinstance(v, (int, float))), 3)
        return MetricsContext(
            total_latency=total,
            engine_latency=latencies,
            token_usage=context.metrics.token_usage,
            memory_latency=context.metrics.memory_latency,
            merge_metrics=dict(context.metrics.merge_metrics),
        )


class StreamCoordinator:
    """Streaming state coordination (M8 spec Ch2 Stream Coordinator).

    Streaming improvements are out of scope for this migration; the
    coordinator records the streaming window markers on the context.
    """

    @staticmethod
    def complete(context: RuntimeContext) -> StreamingContext:
        return StreamingContext(
            stream_id=context.request.request_id,
            first_token_at=now_iso(),
            completed=True,
        )


class PersistenceCoordinator:
    """Persistence scheduling (M8 spec Ch2 Persistence Coordinator).

    Runs the registered persistence engine after streaming completes. The
    existing durable writes (turn/session/memory saves) happen inside the
    conversation engine exactly as before — this stage records runtime
    persistence completion without duplicating writes.
    """

    def __init__(self, executor, stage=None):
        self._executor = executor
        self._stage = stage or _DEFAULT_PERSISTENCE_STAGE

    def persist(self, context):
        if not self._stage.enabled:
            return []
        return self._executor.execute({}, context, stages=[self._stage])


class RuntimeOrchestrator:
    """Central coordinator of one conversation request's internal lifecycle."""

    def __init__(self, registry, merge_engine=None, pipeline=None,
                 persistence_stage=None, response_factory=None):
        self._registry = registry
        self._merge = merge_engine or ContextMergeEngine()
        self._pipeline = list(pipeline if pipeline is not None
                              else _DEFAULT_STAGES)
        self._persistence_stage = (persistence_stage
                                   if persistence_stage is not None
                                   else _DEFAULT_PERSISTENCE_STAGE)
        self._response_factory = response_factory or _build_response

    def execute(self, context: RuntimeContext) -> RuntimeResult:
        """Execute the full runtime lifecycle for one request."""
        dispatcher = EventDispatcher()
        metrics = MetricsCollector()
        try:
            context = context.validate()
            dispatcher.emit("RuntimeStarted", message="user=%s"
                            % context.request.user_id)
            context = self._merge.transition(context, RuntimeState.VALIDATED)
            context = self._merge.transition(context, RuntimeState.EXECUTING)

            executor = PipelineExecutor(
                self._registry, self._pipeline,
                on_event=lambda event: dispatcher.emit(
                    event.event_type, event.engine_id, event.message))
            # Run stages one at a time and merge each stage's update before
            # the next stage's input_builder runs — later stages must see
            # earlier stages' context writes (e.g. the intent_resolver's
            # IntentGraph when the conversation stage builds its input).
            for stage in executor.stages:
                for stage_result in executor.execute(
                        {"message": context.request.message}, context,
                        stages=[stage]):
                    context = self._merge_stage(context, stage_result,
                                                dispatcher, metrics)
                    context = self._merge_runtime_metrics(context, dispatcher,
                                                          metrics)

            # Streaming window (M8 spec Ch2 execution pipeline).
            context = self._merge.transition(context, RuntimeState.STREAMING)
            context = self._merge_update(
                context, EngineUpdate.success(
                    {"streaming": StreamCoordinator.complete(context)}),
                "runtime", dispatcher)

            # Persist changes (M8 spec Ch2 execution pipeline).
            context = self._merge.transition(context, RuntimeState.PERSISTING)
            for stage_result in PersistenceCoordinator(
                    executor, self._persistence_stage).persist(context):
                context = self._merge_stage(context, stage_result, dispatcher,
                                            metrics)
            context = self._merge_runtime_metrics(context, dispatcher, metrics)

            # Finalize while still in Persisting: flush runtime events and
            # execution metadata, then complete.
            context = self._merge_update(
                context, self._finalize_update(context), "runtime", dispatcher)
            dispatcher.emit("RuntimeCompleted", message="request=%s"
                            % context.request.request_id)
            context = self._merge_update(context, EngineUpdate.success(),
                                         "runtime", dispatcher)

            context = self._merge.transition(context, RuntimeState.COMPLETED)
            context = self._merge.transition(context, RuntimeState.DISPOSED)
            return RuntimeResult(context=context,
                                 response=self._response_factory(context),
                                 metrics=context.metrics,
                                 diagnostics=context.diagnostics)
        except (MergeError, PipelineError, ValueError) as exc:
            context = self._fail(context, dispatcher)
            raise RuntimeExecutionError(
                "runtime execution failed: %s" % exc) from exc
        except Exception as exc:  # noqa: BLE001 — runtime must not leak state
            context = self._fail(context, dispatcher)
            raise RuntimeExecutionError(
                "runtime execution failed: %s: %s"
                % (type(exc).__name__, exc)) from exc

    # ─── internals ──────────────────────────────────────────────

    def _merge_stage(self, context, stage_result, dispatcher, metrics):
        context = self._merge_update(context, stage_result.update,
                                     stage_result.stage_id, dispatcher)
        metrics.record(stage_result.stage_id, stage_result.latency_ms)
        return context

    def _merge_update(self, context, update, engine_id, dispatcher):
        result = self._merge.merge(context, update, engine_id,
                                   events=dispatcher.take())
        if not result.ok:
            raise MergeError(
                "merge rejected for engine '%s' (conflicts/rollback)"
                % engine_id)
        return result.context

    def _merge_runtime_metrics(self, context, dispatcher, metrics):
        updated = metrics.update(context)
        if updated == context.metrics:
            return context
        result = self._merge.merge(context, EngineUpdate.success(
            {"metrics": updated}), "runtime", events=dispatcher.take())
        if not result.ok:
            raise MergeError("metrics merge rejected")
        return result.context

    def _finalize_update(self, context):
        execution = context.execution
        return EngineUpdate.success({
            "execution": ExecutionContext(
                stage=RuntimeStage.COMPLETED,
                current_engine="",
                started_at=execution.started_at,
                timeout_ms=execution.timeout_ms,
                retry_count=execution.retry_count,
            ),
        })

    def _fail(self, context, dispatcher):
        dispatcher.emit("RuntimeFailed")
        try:
            if context.lifecycle not in (RuntimeState.FAILED,
                                         RuntimeState.COMPLETED,
                                         RuntimeState.DISPOSED):
                context = self._merge.transition(context, RuntimeState.FAILED)
                context = self._merge_update(context, EngineUpdate.success(),
                                             "runtime", dispatcher)
        except (MergeError, ValueError):
            pass
        try:
            context = self._merge.transition(context, RuntimeState.DISPOSED)
        except MergeError:
            pass
        return context


def _build_response(context):
    """Build the ConversationResponse for a completed runtime (M8 spec Ch1).

    Imported lazily to keep the runtime module graph acyclic.
    """
    from .conversation_runtime import ConversationResponse

    turn = context.conversation.turn or {}
    return ConversationResponse(
        response_id=context.request.request_id,
        message=turn.get("response", ""),
        data=turn,
        diagnostics=context.diagnostics,
        metrics=context.metrics,
    )


__all__ = [
    "EventDispatcher",
    "MetricsCollector",
    "PersistenceCoordinator",
    "RuntimeExecutionError",
    "RuntimeOrchestrator",
    "RuntimeResult",
    "StreamCoordinator",
    "RuntimeContext",
    "RuntimeState",
]
