"""Per-execution engine metrics (RFC-002 Ch4, Engine Metrics).

Metrics SHALL be collected automatically by the runtime; engines never
construct them by hand (RFC-002:1606-1607).
"""

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class EngineMetrics:
    """Timing metrics for a single engine execution."""

    latency_ms: float = 0.0
    started_at: str = ""
    finished_at: str = ""
    retry_count: int = 0

    def with_retries(self, retry_count):
        """Return a copy carrying the given retry count."""
        return replace(self, retry_count=retry_count)
