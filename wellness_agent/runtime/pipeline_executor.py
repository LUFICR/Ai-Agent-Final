"""PipelineExecutor & engine scheduling (M8 spec Ch3, ADR-M8-003).

The PipelineExecutor is the execution engine of the RuntimeOrchestrator: it
loads engines exclusively from the Engine Registry, executes every stage in
the declared deterministic order, applies centralized retry and timeout
policies, and reports StageResults back to the orchestrator.

The PipelineExecutor SHALL never perform reasoning, merge RuntimeContext,
build prompts or persist anything — it only executes engines (M8 spec Ch3
Responsibilities).
"""

import time
from dataclasses import dataclass, field

from .diagnostics import Diagnostic
from .engine_result import EngineResult
from .engine_update import EngineUpdate
from .merge_engine import RuntimeEvent
from .runtime_engine import RetryPolicy
from .registry import UnknownEngineError


@dataclass(frozen=True)
class PipelineStage:
    """One pipeline stage (M8 spec Ch3 PipelineStage)."""

    id: str
    engine_id: str
    enabled: bool = True
    optional: bool = False
    timeout_ms: int = 1000
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    input_builder: object = None  # callable(context) -> dict; None -> engine_input


@dataclass(frozen=True)
class StageResult:
    """Outcome of one executed stage (M8 spec Ch3 StageResult)."""

    stage_id: str
    status: EngineResult
    update: EngineUpdate
    latency_ms: float


class PipelineError(RuntimeError):
    """Raised when a required pipeline stage cannot complete."""


class RetryManager:
    """Centralized retry application (M8 spec Ch2 Retry Coordination).

    Retries SHALL respect the stage's RetryPolicy and SHALL be coordinated
    here, never inside engines.
    """

    def __init__(self, backoff_ms=25):
        self._backoff_ms = backoff_ms

    def execute(self, engine, engine_input, context, policy):
        """Run the engine, retrying failed executions per the policy."""
        update = engine.execute(engine_input, context)
        if not (policy and policy.enabled and policy.max_retries > 0):
            return update, 0
        attempts = 0
        while (update.result == EngineResult.FAILED
               and attempts < policy.max_retries):
            if self._backoff_ms > 0:
                time.sleep(self._backoff_ms / 1000.0)
            attempts += 1
            update = engine.execute(engine_input, context)
        if attempts:
            update = engine.with_retry_count(update, attempts)
        return update, attempts


class TimeoutManager:
    """Centralized timeout enforcement (M8 spec Ch2 Timeout Coordination).

    Stages execute within their configured timeout; a stage that exceeds it
    is cancelled into a FAILED update with an ENGINE_TIMEOUT diagnostic.
    """

    @staticmethod
    def enforce(stage, engine, update, latency_ms):
        timeout = stage.timeout_ms or getattr(engine, "timeout_ms", 0) or 0
        if timeout and latency_ms > timeout:
            return EngineUpdate.failed(
                data=update.data,
                warnings=update.warnings,
                diagnostics=tuple(update.diagnostics) + (
                    Diagnostic(level="error", code="ENGINE_TIMEOUT",
                               engine=engine.id,
                               message="stage '%s' exceeded %d ms"
                                       % (stage.id, timeout)),),
                metrics=update.metrics,
            )
        return update


class PipelineExecutor:
    """Executes engines from the registry in the declared order."""

    def __init__(self, registry, stages, on_event=None):
        self._registry = registry
        self._stages = list(stages)
        self._on_event = on_event or (lambda event: None)
        self._retries = RetryManager()
        self._timeouts = TimeoutManager()

    @property
    def stages(self):
        return list(self._stages)

    def execute(self, engine_input, context, stages=None):
        """Run each stage sequentially; return the collected StageResults.

        Raises PipelineError when a required stage fails after its retry
        policy is exhausted.
        """
        stages = list(stages if stages is not None else self._stages)
        results = []
        self._emit("PipelineStarted")
        try:
            for stage in stages:
                if not stage.enabled:
                    continue
                if not self._registry.has(stage.engine_id):
                    raise PipelineError(
                        "stage '%s': engine '%s' is not registered"
                        % (stage.id, stage.engine_id))
                self._emit("EngineStarted", stage)
                engine = self._registry.get(stage.engine_id)
                stage_input = (stage.input_builder(context)
                               if stage.input_builder else engine_input)
                started = time.perf_counter()
                update, attempts = self._retries.execute(
                    engine, stage_input, context, stage.retry_policy)
                latency = round((time.perf_counter() - started) * 1000, 3)
                update = self._timeouts.enforce(stage, engine, update, latency)

                if update.result == EngineResult.FAILED:
                    self._emit("EngineFailed", stage)
                    if stage.optional:
                        # Fallback policy: skip the optional stage and continue.
                        update = EngineUpdate.skipped(
                            data=update.data,
                            warnings=update.warnings,
                            diagnostics=tuple(update.diagnostics) + (
                                Diagnostic(level="warning", code="STAGE_SKIPPED",
                                           engine=engine.id,
                                           message="optional stage '%s' skipped"
                                                   % stage.id),),
                            metrics=update.metrics,
                        )
                        results.append(StageResult(stage.id, update.result,
                                                   update, latency))
                        self._emit("StageCompleted", stage)
                        continue
                    self._emit("PipelineFailed")
                    raise PipelineError(
                        "stage '%s' (%s) failed%s: %s"
                        % (stage.id, engine.id,
                           " after %d retries" % attempts if attempts else "",
                           update.diagnostics[-1].message
                           if update.diagnostics else "unknown error"))

                self._emit("EngineCompleted", stage)
                results.append(StageResult(stage.id, update.result, update,
                                           latency))
                self._emit("StageCompleted", stage)
            self._emit("PipelineCompleted")
            return results
        except PipelineError:
            raise
        except UnknownEngineError as exc:
            self._emit("PipelineFailed")
            raise PipelineError("pipeline failure: %s" % exc) from exc
        except Exception as exc:  # noqa: BLE001 — any executor fault fails the pipeline
            self._emit("PipelineFailed")
            raise PipelineError("pipeline failure: %s: %s"
                                % (type(exc).__name__, exc)) from exc

    def _emit(self, event_type, stage=None):
        event = RuntimeEvent(
            event_type=event_type,
            engine_id=stage.engine_id if stage else "",
            message=("stage '%s'" % stage.id) if stage else "",
        )
        self._on_event(event)


__all__ = [
    "PipelineError",
    "PipelineExecutor",
    "PipelineStage",
    "RetryManager",
    "StageResult",
    "TimeoutManager",
]
