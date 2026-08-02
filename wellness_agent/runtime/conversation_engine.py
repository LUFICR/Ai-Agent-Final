"""Runtime engines for the conversation pipeline (M8 spec Ch2/Ch3).

`ConversationEngine` wraps the existing deterministic conversation flow
(emotion analysis, memory extraction, state transitions, reasoning engines,
LLM-enhanced response generation — exactly the flow Orchestrator has always
run) as a single registered runtime engine. Behavior is byte-identical to
pre-M8; the engine returns one EngineUpdate whose data owns the `turn`
context field.

`PersistenceEngine` records runtime persistence completion after streaming
(M8 spec Ch2 Persist Changes). The actual durable writes (session turns,
memory facts, reports) continue to happen inside the conversation flow, so
this stage never duplicates writes.
"""

import inspect

from .diagnostics import Diagnostic
from .engine_update import EngineUpdate
from .runtime_engine import BaseEngine, EngineCategory, EngineMetadata


class ConversationEngine(BaseEngine):
    """Wraps the existing conversation flow as one reasoning engine."""

    category = EngineCategory.REASONING
    timeout_ms = 120000

    def __init__(self, process_turn):
        self._process_turn = process_turn

    @property
    def metadata(self):
        return EngineMetadata(
            id="conversation",
            name="Conversation Engine",
            version="1.0.0",
            owner="wellness_agent.orchestrator",
            description="Existing deterministic conversation flow "
                        "(emotion, memory, state, reasoning, response).",
        )

    def _invoke(self, engine_input, context):
        engine_input = engine_input or {}
        message = engine_input.get("message", "")
        intent_graph = engine_input.get("intent_graph") or {}
        if self._accepts_intent_graph():
            turn = self._process_turn(message, intent_graph=intent_graph)
        else:
            turn = self._process_turn(message)
        return EngineUpdate.success({"turn": turn if isinstance(turn, dict)
                                     else {"response": str(turn)}})

    def _accepts_intent_graph(self):
        """True when the wrapped flow accepts the optional `intent_graph`
        kwarg (AI Intelligence wiring); M8-style 1-arg wrappers keep their
        exact behavior."""
        try:
            return "intent_graph" in inspect.signature(
                self._process_turn).parameters
        except (ValueError, TypeError):
            return False


class PersistenceEngine(BaseEngine):
    """Records runtime persistence completion (M8 spec Ch2 Persistence)."""

    category = EngineCategory.INFRASTRUCTURE
    timeout_ms = 15000

    @property
    def metadata(self):
        return EngineMetadata(
            id="persistence",
            name="Persistence Engine",
            version="1.0.0",
            owner="wellness_agent.runtime",
            description="Runtime persistence phase marker; durable writes "
                        "stay inside the conversation flow.",
        )

    def _invoke(self, engine_input, context):
        return EngineUpdate.success(
            {},
            diagnostics=[Diagnostic(
                level="info",
                code="PersistenceCompleted",
                engine=self.id,
                message="runtime persistence phase completed",
            )],
        )


__all__ = ["ConversationEngine", "PersistenceEngine"]
