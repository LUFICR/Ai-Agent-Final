"""Dependency-injected engine wiring (RFC-002 Ch2, GAP_ANALYSIS M7).

`build_user_registry` registers every engine for one user exactly once in
an EngineRegistry; construction is lazy (first `get`) so building an
Orchestrator no longer triggers the ~10 per-user disk loads it did before.
`AgentRegistry` is a thin per-user facade that resolves engine attributes
through the registry — every engine is retrieved only through the registry,
and no engine ever instantiates another.
"""

from .belief_engine import BeliefEngine
from .behavior_engine import BehaviorEngine
from .conversation_judge import ConversationJudge
from .conversation_planner import ConversationPlanner
from .emotion_engine import EmotionEngine
from .hypothesis_engine import HypothesisEngine
from .intervention_ranking import InterventionRankingEngine
from .learning import LearningLayer
from .memory import MemorySystem
from .objective_engine import ObjectiveEngine
from .proactive_engine import ProactiveEngine
from .question_planner import QuestionPlanner
from .reports import ReportGenerator
from .root_cause import RootCauseAnalyzer
from .routine_generator import RoutineGenerator
from .self_evaluation import SelfEvaluator
from .why_engine import WhyEngine
from .runtime.adapters import (
    BehaviorAdapter,
    BeliefAdapter,
    EmotionAdapter,
    HypothesisAdapter,
    LearningAdapter,
    MemoryAdapter,
    ProactiveAdapter,
    ReportsAdapter,
    RootCauseAdapter,
    RoutineAdapter,
    SelfEvaluationAdapter,
    WhyAdapter,
)
from .runtime.registry import EngineRegistry


def build_user_registry(user_id="default", registry=None):
    """Register every engine for one user exactly once (RFC-002 Ch2).

    Engines are registered as factories so disk-backed stores (memory,
    learning, beliefs, ...) are constructed lazily on first use. The
    blueprint is idempotent: re-running it on a populated registry is a
    no-op, while true duplicate registration still raises.
    """
    reg = registry or EngineRegistry(user_id=user_id)

    def _register(engine_id, factory, deps=()):
        if reg.has(engine_id):
            return
        reg.register(engine_id, factory, deps=deps)

    # ─── raw engines (same constructions AgentRegistry used before M7) ───
    _register("memory", lambda r: MemorySystem(user_id))
    _register("emotion_engine", lambda r: EmotionEngine(r.get("memory")),
              deps=("memory",))
    _register("planner", lambda r: ConversationPlanner(r.get("memory")),
              deps=("memory",))
    _register("question_planner", lambda r: QuestionPlanner(r.get("memory")),
              deps=("memory",))
    _register("root_cause_analyzer", lambda r: RootCauseAnalyzer(r.get("memory")),
              deps=("memory",))
    _register("routine_generator", lambda r: RoutineGenerator(r.get("memory")),
              deps=("memory",))
    _register("objective_engine", lambda r: ObjectiveEngine(user_id))
    _register("behavior_engine", lambda r: BehaviorEngine(user_id))
    _register("hypothesis_engine", lambda r: HypothesisEngine(user_id))
    _register("why_engine", lambda r: WhyEngine(r.get("memory")),
              deps=("memory",))
    _register("proactive_engine",
              lambda r: ProactiveEngine(r.get("memory"), r.get("why_engine"),
                                        r.get("behavior_engine")),
              deps=("memory", "why_engine", "behavior_engine"))
    _register("intervention_rank",
              lambda r: InterventionRankingEngine(r.get("memory"),
                                                  r.get("hypothesis_engine"),
                                                  r.get("why_engine"),
                                                  r.get("behavior_engine")),
              deps=("memory", "hypothesis_engine", "why_engine", "behavior_engine"))
    _register("self_evaluator", lambda r: SelfEvaluator(user_id))
    _register("belief_engine", lambda r: BeliefEngine(user_id))
    _register("conversation_judge", lambda r: ConversationJudge(user_id))
    _register("learning", lambda r: LearningLayer(user_id))
    _register("report_generator",
              lambda r: ReportGenerator(r.get("memory"),
                                        behavior_engine=r.get("behavior_engine"),
                                        hypothesis_engine=r.get("hypothesis_engine"),
                                        why_engine=r.get("why_engine"),
                                        self_evaluator=r.get("self_evaluator"),
                                        belief_engine=r.get("belief_engine")),
              deps=("memory", "behavior_engine", "hypothesis_engine",
                    "why_engine", "self_evaluator", "belief_engine"))

    # ─── runtime contract adapters (M6) — resolve raw engines via DI ───
    _register("memory_adapter", lambda r: MemoryAdapter(r.get("memory")),
              deps=("memory",))
    _register("emotion_adapter", lambda r: EmotionAdapter(r.get("emotion_engine")),
              deps=("emotion_engine",))
    _register("learning_adapter", lambda r: LearningAdapter(r.get("learning")),
              deps=("learning",))
    _register("belief_adapter", lambda r: BeliefAdapter(r.get("belief_engine")),
              deps=("belief_engine",))
    _register("hypothesis_adapter",
              lambda r: HypothesisAdapter(r.get("hypothesis_engine")),
              deps=("hypothesis_engine",))
    _register("behavior_adapter",
              lambda r: BehaviorAdapter(r.get("behavior_engine")),
              deps=("behavior_engine",))
    _register("why_adapter", lambda r: WhyAdapter(r.get("why_engine")),
              deps=("why_engine",))
    _register("proactive_adapter",
              lambda r: ProactiveAdapter(r.get("proactive_engine")),
              deps=("proactive_engine",))
    _register("root_cause_adapter",
              lambda r: RootCauseAdapter(r.get("root_cause_analyzer")),
              deps=("root_cause_analyzer",))
    _register("routine_adapter",
              lambda r: RoutineAdapter(r.get("routine_generator")),
              deps=("routine_generator",))
    _register("reports_adapter",
              lambda r: ReportsAdapter(r.get("report_generator")),
              deps=("report_generator",))
    _register("self_evaluation_adapter",
              lambda r: SelfEvaluationAdapter(r.get("self_evaluator")),
              deps=("self_evaluator",))
    return reg


class AgentRegistry:
    """Per-user engine facade backed by EngineRegistry (RFC-002 Ch2).

    Keeps the exact attribute surface the Orchestrator uses
    (self.agents.memory, self.agents.behavior_engine, ...) while every
    engine is constructed and retrieved through the registry.
    """

    _ENGINE_ATTRS = {
        "memory": "memory",
        "emotion_engine": "emotion_engine",
        "planner": "planner",
        "question_planner": "question_planner",
        "root_cause_analyzer": "root_cause_analyzer",
        "routine_generator": "routine_generator",
        "objective_engine": "objective_engine",
        "behavior_engine": "behavior_engine",
        "hypothesis_engine": "hypothesis_engine",
        "why_engine": "why_engine",
        "proactive_engine": "proactive_engine",
        "intervention_rank": "intervention_rank",
        "self_evaluator": "self_evaluator",
        "belief_engine": "belief_engine",
        "conversation_judge": "conversation_judge",
        "learning": "learning",
        "report_generator": "report_generator",
    }

    def __init__(self, user_id="default", registry=None):
        self.user_id = user_id
        self.registry = registry or build_user_registry(user_id)

    def __getattr__(self, name):
        engine_id = self._ENGINE_ATTRS.get(name)
        if engine_id is None:
            raise AttributeError(
                "%s has no attribute %r" % (type(self).__name__, name))
        return self.registry.get(engine_id)

    def get_agent(self, name):
        registry = {
            "emotion_detection": self.emotion_engine.analyze,
            "memory_manager": self.extract_and_store,
            "root_cause_engine": self.root_cause_analyzer.analyze,
            "question_planner": self.question_planner.generate_question,
            "routine_generator": self.routine_generator.generate,
            "report_generator": self.report_generator.generate,
            "conversation_planner": self.planner.select_target_pillar,
            "reflection_agent": self.reflection_response,
        }
        return registry.get(name)

    def extract_and_store(self, message, emotion_result=None):
        if not message:
            return []

        facts = self.memory.extract_facts_from_message(message)

        if emotion_result and emotion_result.get("primary_emotion") != "neutral":
            facts.append({
                "action": "add",
                "category": "emotional_history",
                "key": f"emotion_{emotion_result['primary_emotion']}",
                "value": emotion_result["primary_emotion"],
                "confidence": emotion_result.get("confidence", 60),
                "source": "conversation"
            })

        stored = []
        for fact in facts:
            if isinstance(fact, dict):
                stored.append(self.memory.add_fact(
                    fact.get("category", "identity"),
                    fact.get("key", "unknown"),
                    fact.get("value", "mentioned"),
                    fact.get("confidence", 50),
                    fact.get("source", "conversation"),
                    message
                ))
            elif len(fact) >= 4:
                category, key, value, confidence = fact[0], fact[1], fact[2], fact[3]
                source = fact[4] if len(fact) > 4 else "conversation"
                result = self.memory.add_fact(category, key, value, confidence, source, message)
                stored.append(result)

        return stored

    def reflection_response(self, state_info=None):
        state_info = state_info or {}
        if state_info.get("routine_created"):
            return "You've built a solid plan today. How do you feel about the steps you've set up?"
        if state_info.get("insight_delivered"):
            return "It sounds like today brought some useful clarity. Anything you want to hold onto from this conversation?"
        return "We've covered a lot today. How are you feeling about what came up?"
