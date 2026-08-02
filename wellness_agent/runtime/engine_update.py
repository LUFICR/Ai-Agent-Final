"""EngineUpdate contract (RFC-002 Ch4, Engine Output).

Every engine SHALL return an EngineUpdate wrapping its output, diagnostics,
warnings and metrics (RFC-002:1564-1586). EngineUpdate is immutable; the
Runtime Orchestrator merges updates into a new RuntimeContext.
"""

from dataclasses import dataclass, field
from typing import Any

from .engine_metrics import EngineMetrics
from .engine_result import EngineResult


@dataclass(frozen=True)
class EngineUpdate:
    """Output of a single engine execution.

    Attributes:
        result: one of the four EngineResult states (RFC-002:1610-1622).
        success: True when the result is SUCCESS or PARTIAL.
        data: engine output (immutable by convention; use dicts of scalars).
        diagnostics: Diagnostic records for observability.
        warnings: short human-readable warning strings.
        metrics: EngineMetrics collected automatically by the runtime.
    """

    result: EngineResult
    data: Any = field(default_factory=dict)
    diagnostics: tuple = ()
    warnings: tuple = ()
    metrics: EngineMetrics = field(default_factory=EngineMetrics)
    success: bool = False

    def __post_init__(self):
        object.__setattr__(self, "success", self.result.ok)

    @classmethod
    def success(cls, data=None, warnings=(), diagnostics=(), metrics=None):
        """Execution completed (RFC-002:1616)."""
        return cls(EngineResult.SUCCESS, data if data is not None else {},
                   tuple(diagnostics), tuple(warnings),
                   metrics or EngineMetrics())

    @classmethod
    def partial(cls, data=None, warnings=(), diagnostics=(), metrics=None):
        """Fallback used (RFC-002:1617)."""
        return cls(EngineResult.PARTIAL, data if data is not None else {},
                   tuple(diagnostics), tuple(warnings),
                   metrics or EngineMetrics())

    @classmethod
    def failed(cls, data=None, warnings=(), diagnostics=(), metrics=None):
        """Execution failed (RFC-002:1618)."""
        return cls(EngineResult.FAILED, data if data is not None else {},
                   tuple(diagnostics), tuple(warnings),
                   metrics or EngineMetrics())

    @classmethod
    def skipped(cls, data=None, warnings=(), diagnostics=(), metrics=None):
        """Engine intentionally bypassed (RFC-002:1619)."""
        return cls(EngineResult.SKIPPED, data if data is not None else {},
                   tuple(diagnostics), tuple(warnings),
                   metrics or EngineMetrics())
