"""ConversationRuntime — public entry point into the AI runtime (M8 spec Ch1).

Every conversation request — chat, voice, mobile, API — enters through
ConversationRuntime.execute(). The runtime:

1. validates the request (invalid requests terminate before orchestration)
2. creates a unique request-scoped RuntimeContext
3. resolves the RuntimeOrchestrator from the Engine Registry
4. invokes it and returns the final ConversationResponse
5. releases all request-scoped resources (the context ends Disposed)

ConversationRuntime SHALL remain completely stateless and SHALL never
contain business logic (M8 spec Ch1: it must not classify intents, update
memory, call engines directly, build prompts, retry or merge updates).
"""

from dataclasses import dataclass, field
from uuid import uuid4

from .runtime_context import RuntimeContext
from .runtime_orchestrator import RuntimeOrchestrator


@dataclass(frozen=True)
class ConversationRequest:
    """Validated conversation request (M8 spec Ch1 Request Validation)."""

    user_id: str
    message: str = ""
    conversation_id: str = ""
    session_id: str = ""
    channel: str = "chat"
    trace_id: str = ""


@dataclass(frozen=True)
class ConversationResponse:
    """Stable response contract (M8 spec Ch1 Response Contract).

    `data` carries the full turn result (the same dict the Orchestrator has
    always returned); `message` is the assistant text; diagnostics and
    metrics are attached for observability. `context` exposes the final
    request-scoped RuntimeContext (lifecycle, history, diagnostics) for
    logging/replay purposes — read-only, never cached.
    """

    response_id: str
    message: str
    data: dict = field(default_factory=dict)
    diagnostics: object = None
    metrics: object = None
    context: object = None


class ConversationRuntime:
    """Stateless public entry point; delegates orchestration.

    Dependencies (RuntimeOrchestrator) are resolved through the Engine
    Registry — direct construction of runtime services is prohibited
    (M8 spec Ch1 Dependency Resolution).
    """

    def __init__(self, registry, runtime_version="1.0.0"):
        self._registry = registry
        self._runtime_version = runtime_version

    def execute(self, request) -> ConversationResponse:
        """The single public execution method (M8 spec Ch1 Public Interface).

        Raises ValueError for invalid requests (critical failures terminate
        before orchestration begins) and RuntimeExecutionError when the
        runtime cannot complete the request.
        """
        if not isinstance(request, ConversationRequest):
            raise ValueError("request must be a ConversationRequest")
        if not request.user_id:
            raise ValueError("request.user_id is required")

        context = RuntimeContext.create(
            request_id=uuid4().hex[:16],
            user_id=request.user_id,
            session_id=request.session_id or request.user_id,
            conversation_id=request.conversation_id or request.user_id,
            channel=request.channel,
            trace_id=request.trace_id,
            runtime_version=self._runtime_version,
            message=request.message,
        )
        # Invalid contexts terminate before orchestration begins.
        context.validate()

        orchestrator = self._registry.get("runtime_orchestrator")
        result = orchestrator.execute(context)

        # The orchestrator disposes the context (ends DISPOSED); nothing
        # request-scoped survives here. The context itself is exposed
        # read-only on the response for the conversation logger.
        return ConversationResponse(
            response_id=result.context.request.request_id,
            message=(result.context.conversation.turn or {}).get("response", ""),
            data=result.context.conversation.turn or {},
            diagnostics=result.context.diagnostics,
            metrics=result.context.metrics,
            context=result.context,
        )


__all__ = [
    "ConversationRequest",
    "ConversationResponse",
    "ConversationRuntime",
    "RuntimeContext",
    "RuntimeOrchestrator",
]
