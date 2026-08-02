"""Engine execution result states (RFC-002 Ch4, Engine Result States).

Every execution SHALL end in exactly one of these four states.
"""

from enum import Enum


class EngineResult(Enum):
    """Final state of one engine execution (RFC-002:1610-1622)."""

    SUCCESS = "success"
    """Execution completed."""

    PARTIAL = "partial"
    """Fallback used."""

    FAILED = "failed"
    """Execution failed."""

    SKIPPED = "skipped"
    """Engine intentionally bypassed."""

    @property
    def ok(self):
        """True when execution produced usable output."""
        return self in (EngineResult.SUCCESS, EngineResult.PARTIAL)
