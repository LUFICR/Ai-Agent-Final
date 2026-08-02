"""Diagnostics records for runtime execution (RFC-002 Ch3 DiagnosticsContext).

Diagnostics SHALL never affect runtime execution; they exist for debugging
and observability (RFC-002:1195-1197).
"""

from dataclasses import dataclass, field

from ..utils.storage import now_iso


@dataclass(frozen=True)
class Diagnostic:
    """A single warning or error produced by an engine execution."""

    level: str = "warning"
    message: str = ""
    code: str = ""
    engine: str = ""
    at: str = field(default_factory=now_iso)

    def __post_init__(self):
        if self.level not in ("info", "warning", "error"):
            raise ValueError("level must be 'info', 'warning' or 'error'")


@dataclass(frozen=True)
class DecisionTrace:
    """A recorded runtime decision for traceability."""

    engine: str = ""
    decision: str = ""
    rationale: str = ""
    at: str = field(default_factory=now_iso)
