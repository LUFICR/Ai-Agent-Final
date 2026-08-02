"""Contract wrappers for the existing deterministic engines (GAP M6).

Each adapter injects the existing engine instance (dependency injection per
RFC-002 Ch2 — no engine instantiates another) and exposes it through the
RuntimeEngine contract: execute(input, context) -> EngineUpdate.

Business logic lives exclusively in the wrapped engines; adapters only map
inputs and outputs. RuntimeContext is read-only — adapters never write to it.
"""

from .engine_update import EngineUpdate
from .runtime_context import RuntimeContext
from .runtime_engine import (
    BaseEngine,
    EngineCategory,
    EngineMetadata,
)


class MemoryAdapter(BaseEngine):
    """Wraps MemorySystem: extract memory facts from a user message.

    Input: {"message": str}
    Output: {"facts": [...]}
    """

    category = EngineCategory.KNOWLEDGE

    def __init__(self, engine):
        self._engine = engine

    @property
    def metadata(self):
        return EngineMetadata(
            id="memory",
            name="Memory System",
            version="1.0.0",
            owner="wellness_agent.memory",
            description="Extracts and manages memory facts (RFC-001 Ch4).",
        )

    def _invoke(self, engine_input, context):
        message = (engine_input or {}).get("message", "")
        facts = self._engine.extract_facts_from_message(message)
        return EngineUpdate.success({"facts": facts})


class LearningAdapter(BaseEngine):
    """Wraps LearningLayer: learn from one completed conversation.

    Input: {"turns": [...], "memory_facts": [...], "traits": {...},
            "hypotheses": {...}, "objective_track": {...},
            "judge_result": {...}, "reasoning_context": {...}}
    Output: {"updates": {...}}
    """

    category = EngineCategory.COACHING

    def __init__(self, engine):
        self._engine = engine

    @property
    def metadata(self):
        return EngineMetadata(
            id="learning",
            name="Learning Layer",
            version="1.0.0",
            owner="wellness_agent.learning",
            description="Per-user learning from conversation outcomes (RFC-001 Ch8).",
        )

    def _invoke(self, engine_input, context):
        inp = engine_input or {}
        updates = self._engine.record_conversation(
            turns=inp.get("turns"),
            memory_facts=inp.get("memory_facts"),
            traits=inp.get("traits"),
            hypotheses=inp.get("hypotheses"),
            objective_track=inp.get("objective_track"),
            judge_result=inp.get("judge_result"),
            reasoning_context=inp.get("reasoning_context"),
        )
        return EngineUpdate.success({"updates": updates or {}})


class BeliefAdapter(BaseEngine):
    """Wraps BeliefEngine: derive beliefs from memory facts.

    Input: {"facts": [...]}
    Output: {"beliefs": [...]}
    """

    category = EngineCategory.KNOWLEDGE

    def __init__(self, engine):
        self._engine = engine

    @property
    def metadata(self):
        return EngineMetadata(
            id="belief",
            name="Belief Engine",
            version="1.0.0",
            owner="wellness_agent.belief_engine",
            description="Derives beliefs from memory facts.",
        )

    def _invoke(self, engine_input, context):
        beliefs = self._engine.update((engine_input or {}).get("facts"))
        return EngineUpdate.success({"beliefs": beliefs or []})


class HypothesisAdapter(BaseEngine):
    """Wraps HypothesisEngine: update hypotheses from a user message.

    Input: {"message": str, "emotion": {...}, "current_pillar": str,
            "memory_facts": [...]}
    Output: {"hypotheses": [...]}
    """

    category = EngineCategory.KNOWLEDGE

    def __init__(self, engine):
        self._engine = engine

    @property
    def metadata(self):
        return EngineMetadata(
            id="hypothesis",
            name="Hypothesis Engine",
            version="1.0.0",
            owner="wellness_agent.hypothesis_engine",
            description="Maintains ranked root-cause hypotheses.",
        )

    def _invoke(self, engine_input, context):
        inp = engine_input or {}
        hypotheses = self._engine.update(
            message=inp.get("message", ""),
            emotion=inp.get("emotion"),
            current_pillar=inp.get("current_pillar"),
            memory_facts=inp.get("memory_facts"),
        )
        return EngineUpdate.success({"hypotheses": hypotheses or []})


class BehaviorAdapter(BaseEngine):
    """Wraps BehaviorEngine: update behavior traits from a message.

    Input: {"message": str, "emotion": {...}}
    Output: {"traits": {...}}
    """

    category = EngineCategory.COACHING

    def __init__(self, engine):
        self._engine = engine

    @property
    def metadata(self):
        return EngineMetadata(
            id="behavior",
            name="Behavior Engine",
            version="1.0.0",
            owner="wellness_agent.behavior_engine",
            description="Evidence-based behavior trait learning.",
        )

    def _invoke(self, engine_input, context):
        inp = engine_input or {}
        traits = self._engine.update(
            message=inp.get("message", ""),
            emotion=inp.get("emotion"),
        )
        return EngineUpdate.success({"traits": traits or {}})


class WhyAdapter(BaseEngine):
    """Wraps WhyEngine: detect co-deviating signal patterns.

    Input: {}
    Output: {"patterns": [...]}
    """

    category = EngineCategory.COACHING

    def __init__(self, engine):
        self._engine = engine

    @property
    def metadata(self):
        return EngineMetadata(
            id="why",
            name="Why Engine",
            version="1.0.0",
            owner="wellness_agent.why_engine",
            description="Pattern and root-cause insight detection (RFC-001 Ch9).",
        )

    def _invoke(self, engine_input, context):
        patterns = self._engine.update()
        return EngineUpdate.success({"patterns": patterns or []})


class ProactiveAdapter(BaseEngine):
    """Wraps ProactiveEngine: decide whether a proactive check-in is due.

    Input: {}
    Output: {"checkin": {...}}
    """

    category = EngineCategory.PLANNING

    def __init__(self, engine):
        self._engine = engine

    @property
    def metadata(self):
        return EngineMetadata(
            id="proactive",
            name="Proactive Engine",
            version="1.0.0",
            owner="wellness_agent.proactive_engine",
            description="Deterministic proactive check-in decisions.",
        )

    def _invoke(self, engine_input, context):
        checkin = self._engine.checkin()
        return EngineUpdate.success({"checkin": checkin or {}})


class RootCauseAdapter(BaseEngine):
    """Wraps RootCauseAnalyzer: build a root-cause chain for a pillar.

    Input: {"pillar": str, "memory_facts": [...], "emotion_history": [...],
            "habit_trends": [...]}
    Output: {"root_cause": {...}}
    """

    category = EngineCategory.PLANNING

    def __init__(self, engine):
        self._engine = engine

    @property
    def metadata(self):
        return EngineMetadata(
            id="root_cause",
            name="Root Cause Analyzer",
            version="1.0.0",
            owner="wellness_agent.root_cause",
            description="Root-cause chains per pillar (RFC-001 Ch10 pipeline).",
        )

    def _invoke(self, engine_input, context):
        inp = engine_input or {}
        root_cause = self._engine.analyze(
            pillar=inp.get("pillar", ""),
            memory_facts=inp.get("memory_facts"),
            emotion_history=inp.get("emotion_history"),
            habit_trends=inp.get("habit_trends"),
        )
        return EngineUpdate.success({"root_cause": root_cause or {}})


class RoutineAdapter(BaseEngine):
    """Wraps RoutineGenerator: generate a routine for a goal.

    Input: {"goal": str, "memory_facts": [...], "past_adherence": [...],
            "constraints": [...]}
    Output: {"routine": {...}}
    """

    category = EngineCategory.PLANNING

    def __init__(self, engine):
        self._engine = engine

    @property
    def metadata(self):
        return EngineMetadata(
            id="routine",
            name="Routine Generator",
            version="1.0.0",
            owner="wellness_agent.routine_generator",
            description="Deterministic routine/intervention generation.",
        )

    def _invoke(self, engine_input, context):
        inp = engine_input or {}
        routine = self._engine.generate(
            root_cause_or_goal=inp.get("goal", ""),
            memory_facts=inp.get("memory_facts"),
            past_adherence=inp.get("past_adherence"),
            constraints=inp.get("constraints"),
        )
        return EngineUpdate.success({"routine": routine or {}})


class ReportsAdapter(BaseEngine):
    """Wraps ReportGenerator: generate a progress report.

    Input: {"period": str, "metrics": {...}, "prior_period_metrics": {...},
            "achievements": [...]}
    Output: {"report": {...}}
    """

    category = EngineCategory.INFRASTRUCTURE

    def __init__(self, engine):
        self._engine = engine

    @property
    def metadata(self):
        return EngineMetadata(
            id="reports",
            name="Report Generator",
            version="1.0.0",
            owner="wellness_agent.reports",
            description="Periodic progress report generation.",
        )

    def _invoke(self, engine_input, context):
        inp = engine_input or {}
        report = self._engine.generate(
            period=inp.get("period", "daily"),
            metrics=inp.get("metrics"),
            prior_period_metrics=inp.get("prior_period_metrics"),
            achievements=inp.get("achievements"),
        )
        return EngineUpdate.success({"report": report or {}})


class SelfEvaluationAdapter(BaseEngine):
    """Wraps SelfEvaluator: evaluate the quality of a user reply.

    Input: {"reply": str, "state": str, "emotion": {...},
            "objective": {...}, "traits": [...]}
    Output: {"result": {...}}
    """

    category = EngineCategory.COACHING

    def __init__(self, engine):
        self._engine = engine

    @property
    def metadata(self):
        return EngineMetadata(
            id="self_evaluation",
            name="Self Evaluator",
            version="1.0.0",
            owner="wellness_agent.self_evaluation",
            description="Deterministic per-turn conversation evaluation.",
        )

    def _invoke(self, engine_input, context):
        inp = engine_input or {}
        result = self._engine.evaluate(
            reply=inp.get("reply", ""),
            state=inp.get("state"),
            emotion=inp.get("emotion"),
            objective=inp.get("objective"),
            traits=inp.get("traits"),
        )
        return EngineUpdate.success({"result": result or {}})


class EmotionAdapter(BaseEngine):
    """Wraps EmotionEngine: analyze emotion from a user message.

    Input: {"message": str, "recent_context": [...]}
    Output: {"emotion": {...}}
    """

    category = EngineCategory.KNOWLEDGE

    def __init__(self, engine):
        self._engine = engine

    @property
    def metadata(self):
        return EngineMetadata(
            id="emotion",
            name="Emotion Engine",
            version="1.0.0",
            owner="wellness_agent.emotion_engine",
            description="Rule-based emotion analysis from text.",
        )

    def _invoke(self, engine_input, context):
        inp = engine_input or {}
        emotion = self._engine.analyze(
            message=inp.get("message", ""),
            recent_context=inp.get("recent_context"),
        )
        return EngineUpdate.success({"emotion": emotion or {}})
