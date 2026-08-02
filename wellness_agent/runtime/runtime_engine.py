"""RuntimeEngine contract (RFC-002 Ch4, Runtime Engine Contract).

Every runtime engine SHALL implement this interface (RFC-002:1492-1516)
and SHALL NOT mutate RuntimeContext, call other engines, or access
persistence directly (RFC-002:1760-1770).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from .diagnostics import Diagnostic
from .engine_metrics import EngineMetrics
from .engine_update import EngineUpdate


class EngineCategory(Enum):
    """Engine categories for diagnostics (RFC-002:1744-1757)."""

    REASONING = "reasoning"
    KNOWLEDGE = "knowledge"
    PLANNING = "planning"
    COACHING = "coaching"
    INFRASTRUCTURE = "infrastructure"


@dataclass(frozen=True)
class EngineMetadata:
    """Engine identification for diagnostics (RFC-002:1520-1541)."""

    id: str = ""
    name: str = ""
    version: str = ""
    owner: str = ""
    description: str = ""


@dataclass(frozen=True)
class RetryPolicy:
    """Declared retry behavior (RFC-002:1695-1712)."""

    enabled: bool = False
    max_retries: int = 0
    timeout_ms: int = 0


class RuntimeEngine(ABC):
    """Mandatory contract for every runtime engine."""

    category: EngineCategory = EngineCategory.INFRASTRUCTURE
    timeout_ms: int = 1000
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)

    @property
    @abstractmethod
    def metadata(self) -> EngineMetadata:
        """Engine metadata (id, name, version, owner, description)."""

    @property
    def id(self):
        return self.metadata.id

    @property
    def name(self):
        return self.metadata.name

    @property
    def version(self):
        return self.metadata.version

    @abstractmethod
    def execute(self, engine_input, context) -> EngineUpdate:
        """Execute the engine and return an EngineUpdate (RFC-002:1497-1511)."""

    def initialize(self):
        """Optional lifecycle hook; SHALL NOT contain business logic."""

    def dispose(self):
        """Optional lifecycle hook; SHALL NOT contain business logic."""

    def health_check(self) -> bool:
        """Report engine health (RFC-002:1645-1656)."""
        return True


class BaseEngine(RuntimeEngine):
    """Shared execution wrapper: timing, metrics, error capture.

    Subclasses implement `_invoke(engine_input, context)` with the actual
    business call. `execute` guarantees:

    - the engine NEVER throws (RFC-002:1673-1693) — exceptions become
      EngineUpdate.failed
    - metrics are collected automatically (RFC-002:1606-1607)
    - result/success flags stay consistent
    - RuntimeContext is never written to
    """

    @abstractmethod
    def _invoke(self, engine_input, context) -> EngineUpdate:
        """Run the underlying business logic and return an update."""

    def execute(self, engine_input, context) -> EngineUpdate:
        started = datetime.now()
        try:
            update = self._invoke(engine_input, context)
        except Exception as exc:  # noqa: BLE001 — engines never throw
            update = EngineUpdate.failed(
                diagnostics=[Diagnostic(
                    level="error",
                    code="ENGINE_EXCEPTION",
                    engine=self.id,
                    message="%s: %s" % (type(exc).__name__, exc),
                )],
            )
        finished = datetime.now()
        metrics = EngineMetrics(
            latency_ms=round((finished - started).total_seconds() * 1000, 3),
            started_at=started.isoformat(),
            finished_at=finished.isoformat(),
            retry_count=0,
        )
        return EngineUpdate(
            result=update.result,
            data=update.data,
            diagnostics=update.diagnostics,
            warnings=update.warnings,
            metrics=metrics,
        )

    def with_retry_count(self, update: EngineUpdate, retries: int) -> EngineUpdate:
        """Attach a retry count to an update's metrics."""
        return EngineUpdate(
            result=update.result,
            data=update.data,
            diagnostics=update.diagnostics,
            warnings=update.warnings,
            metrics=update.metrics.with_retries(retries),
        )
