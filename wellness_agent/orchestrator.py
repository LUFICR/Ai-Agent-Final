from .agents import AgentRegistry
from .state_machine import ConversationStateMachine
from .config import PRODUCT_CONTEXT, APP_NAME, PILLARS
from .utils.storage import load_json, save_json, now_iso
from .config import get_user_session_path
from .llm_service import GroqLLM
from .memory import _CONFIRM_ACCEPT, _CONFIRM_REJECT
from .reasoning_context import build_reasoning_context
from .runtime.conversation_engine import ConversationEngine, PersistenceEngine
from .runtime.conversation_runtime import ConversationRequest, ConversationRuntime
from .runtime.intent_resolver import IntentResolverEngine
from .runtime.runtime_orchestrator import RuntimeOrchestrator
from .conversation_logger import get_conversation_logger
import itertools
import logging
import os
import time
from difflib import SequenceMatcher

SHORT_DEFLECTIONS = frozenset([
    "no", "idk", "nah", "nope", "not sure", "i don't know",
    "i dunno", "i don't think so", "not really", "maybe",
    "i guess", "whatever", "fine", "okay", "ok",
])

# Message variants per state — cycles through these to avoid verbatim repeats
_MESSAGE_VARIANTS = {
    "free_conversation": [
        "I'm here to listen. Tell me more about that.",
        "I'm listening — what's on your mind?",
        "Go on, I'm right here with you.",
        "Thanks for sharing. What else comes to mind?",
    ],
    "rapport_building": [
        "I appreciate you sharing. How's your day been, genuinely?",
        "Thanks for telling me that. How are you doing right now?",
        "I'm glad you're here. How's your day going so far?",
    ],
    "avoidance_detection": [
        "No pressure — want to keep talking, switch topics, or just check in later?",
        "We can go at whatever pace works for you. What feels best right now?",
        "Whenever you're ready — we can explore something, take a break, or just chat.",
    ],
    "soft_exploration": [
        "Sometimes it's hard to put into words. Want to start anywhere?",
        "No need to have the perfect answer. What comes to mind first?",
        "We don't need a big topic — a small thing works too. What's one thought?",
    ],
    "insight_generation": [
        "Does that resonate with you? We can explore it more or think about what might help.",
        "What do you make of that? Does it feel true to your experience?",
        "How does that land with you? We can sit with it or move toward next steps.",
    ],
    "follow_up": [
        "It's good to talk with you again. How has your week been since our last conversation?",
        "Welcome back. How have things been since we last checked in?",
        "Great to see you again. What's been happening since we talked?",
    ],
    "quick_path": [
        "Quick path: which area matters most right now?",
        "Let's keep it simple — which area matters most right now?",
        "To help point us the right way: which area is heaviest on you today?",
    ],
    "casual": [
        "Happy to just chat. What's on your mind?",
        "Nice — I'm here for that too. Anything else going on with you?",
        "I'm enjoying this. What else is on your mind?",
        "Whenever you want to dive into something, I'm here for that too. How's your day going?",
    ],
    "default": [
        "I hear you. Can you tell me a bit more about that?",
        "Thanks for saying that. Want to unpack it a little more?",
        "I'm following. What else is on your mind about this?",
    ],
}


class Orchestrator:
    def __init__(self, user_id="default", enable_auto_judge=True, enable_learning=True):
        self.user_id = user_id
        self.enable_auto_judge = enable_auto_judge
        self.enable_learning = enable_learning
        self.agents = AgentRegistry(user_id)
        self.state_machine = ConversationStateMachine(self.agents.memory)
        self.context = PRODUCT_CONTEXT.format(APP_NAME=APP_NAME)
        self.last_turns = []
        self._judged_objective = None
        self.current_pillar = None
        self.current_insight = None
        self.current_routine = None
        self.last_question = None
        self.avoidance_count = 0
        self._exit_offered = False
        self._exit_consumed = False  # one-shot: never re-trigger exit after handling
        self._last_user_message = ""
        self._last_response_text = None
        self._last_response_state = None
        self._repeat_count = 0
        self._response_cyclers = {k: itertools.cycle(v) for k, v in _MESSAGE_VARIANTS.items()}
        self.session_path = get_user_session_path(user_id)
        self.llm = GroqLLM()
        self.current_objective = None
        self.last_checkin = None
        self._proactive_asked = False
        self._ranked_interventions = []
        self._intervention_index = 0
        self.reasoning_ctx = None
        self._last_turn = None
        self._last_eval = None
        self._register_runtime_engines()
        self.runtime = ConversationRuntime(registry=self.agents.registry)
        self.conversation_logger = get_conversation_logger()
        self._load_session()

    def _register_runtime_engines(self):
        """Register the runtime engines once into this user's registry.

        The Intent Resolver 2.0 runs first in the pipeline (RFC-001 Ch2.1)
        and produces the IntentGraph; the conversation engine wraps this
        Orchestrator's business flow and consumes the graph; the
        RuntimeOrchestrator executes the pipeline. The pipeline stages are
        built here with Orchestrator-aware input builders (memory facts,
        last turns, active branch) that the generic runtime cannot see.
        """
        registry = self.agents.registry

        def _register(engine_id, factory):
            if registry.has(engine_id):
                return
            registry.register(engine_id, factory)

        _register("intent_resolver", lambda r: IntentResolverEngine())
        _register("conversation", lambda r: ConversationEngine(self._process_turn))
        _register("persistence", lambda r: PersistenceEngine())
        _register("runtime_orchestrator", lambda r: RuntimeOrchestrator(
            registry=r, pipeline=self._runtime_stages()))

    def _runtime_stages(self):
        """Pipeline stage definitions for this Orchestrator's conversation.

        `intent_resolver` runs before `conversation` (RFC-001 Ch2.1
        execution order); its IntentGraph is merged into the runtime
        context and passed into the conversation stage input.
        """
        from .runtime.pipeline_executor import PipelineStage
        from .runtime.runtime_engine import RetryPolicy

        def _intent_input(ctx):
            last_turns = [t for t in (self.last_turns or []) if isinstance(t, dict)]
            previous = last_turns[-1] if last_turns else {}
            return {
                "message": ctx.request.message,
                "active_branch": ctx.conversation.active_branch
                or self.current_pillar or "",
                "previous_question": previous.get("assistant") or "",
                "last_turns": last_turns[-5:],
                "memory_facts": self.agents.memory.get_all_facts(),
                "current_state": self.state_machine.current_state,
            }

        def _conversation_input(ctx):
            return {
                "message": ctx.request.message,
                "intent_graph": ctx.conversation.intent_graph or {},
            }

        return [
            PipelineStage(
                id="intent_resolver",
                engine_id="intent_resolver",
                enabled=True,
                optional=False,
                timeout_ms=5000,
                retry_policy=RetryPolicy(enabled=False, max_retries=0),
                input_builder=_intent_input,
            ),
            PipelineStage(
                id="conversation",
                engine_id="conversation",
                enabled=True,
                optional=False,
                timeout_ms=120000,
                retry_policy=RetryPolicy(enabled=False, max_retries=0),
                input_builder=_conversation_input,
            ),
        ]

    def process_message(self, user_message):
        """Public entry point: execute the turn through the ConversationRuntime.

        Returns the exact same turn dict the Orchestrator has always
        returned — the runtime owns execution, this method owns nothing.
        Every turn is recorded to the conversation log asynchronously
        (logging never affects response generation).
        """
        request = ConversationRequest(
            user_id=self.user_id,
            session_id=self.user_id,
            conversation_id=self.user_id,
            message=user_message,
        )
        t0 = time.perf_counter()
        result = self.runtime.execute(request)
        response_time_ms = (time.perf_counter() - t0) * 1000.0
        self._log_conversation_turn(request, result, response_time_ms)
        return result.data

    def _log_conversation_turn(self, request, result, response_time_ms):
        """Record the turn to the conversation log; never breaks the chat."""
        try:
            self.conversation_logger.record_runtime_turn(
                context=result.context, orch=self,
                response_time_ms=response_time_ms)
        except Exception:  # noqa: BLE001 — logging must never affect the turn
            logging.getLogger("wellness_agent").warning(
                "conversation logging failed", exc_info=True)

    def _process_turn(self, user_message, intent_graph=None):
        self._last_user_message = user_message
        turn_result = {
            "user_message": user_message,
            "intent_graph": intent_graph or {},
            "risk_detected": False,
            "emotion": None,
            "state": None,
            "response": None,
            "options": None,
            "insight": None,
            "routine": None,
            "route": [],
            "memory_updates": [],
            "llm_used": self.llm.is_available()
        }

        # Phase 5: Emotion extraction (LLM + rule hybrid)
        emotion = self._analyze_emotion(user_message)
        turn_result["emotion"] = emotion

        if emotion.get("risk_flag"):
            turn_result["risk_detected"] = True
            turn_result["route"] = ["risk_protocol"]
            turn_result["response"] = self._risk_response(emotion.get("risk_reason", ""))
            turn_result["state"] = self.state_machine.get_state_info()
            turn_result["reasoning_context"] = self._build_reasoning_context(emotion, risk_flag=True)
            turn_result["planner_decision"] = self.agents.planner.decide(
                self._planner_context(["risk_protocol"], emotion,
                                      turn_result.get("intent_graph", {}))).to_dict()
            self._save_turn(user_message, turn_result)
            self._maybe_debug(turn_result)
            return turn_result

        # ─── Self evaluation (deterministic): did the PREVIOUS response achieve its objective? ───
        self._evaluate_previous_turn(user_message, emotion)
        turn_result["self_evaluation"] = self._last_eval

        # ─── Hard Avoidance Counter (deterministic, not LLM) ───
        if user_message.strip():
            msg_lower = user_message.strip().lower()
            words = msg_lower.split()
            # Anger is engagement, not deflection
            primary_emo = (emotion or {}).get("primary_emotion")
            frustration = (emotion or {}).get("frustration", 0)
            is_angry = primary_emo == "angry" or frustration > 50
            # Never classify topic-relevant keywords as deflecting
            topic_keywords = set(["work", "sleep", "stress", "anxiety", "sad", "lonely", "mental",
                                  "health", "focus", "energy", "mood", "tired", "motivation",
                                  "productivity", "physical", "overwhelm", "burnout", "sleep",
                                  "exercise", "nutrition", "procrastination", "routine"])
            has_topic = any(t in msg_lower for t in topic_keywords)
            is_deflecting = (
                not has_topic
                and not is_angry
                and (len(words) < 3
                     or msg_lower in SHORT_DEFLECTIONS)
            )
            if is_deflecting:
                self.avoidance_count += 1
            else:
                self.avoidance_count = 0

        if self.avoidance_count == 2 and self.state_machine.current_state in (
            "guided_discovery", "pillar_selection", "deep_investigation"
        ):
            self.state_machine.set_state("rapport_building")

        # ─── Handle reply to exit-offer message ───
        if self._exit_offered and user_message.strip():
            msg_lower = user_message.strip().lower()
            # If user mentions any wellness topic, treat as engagement, not exit reply
            topic_keywords = ["work", "sleep", "stress", "anxiety", "sad", "lonely", "mental",
                              "health", "focus", "energy", "mood", "tired", "motivation",
                              "productivity", "physical", "overwhelm", "burnout"]
            if any(t in msg_lower for t in topic_keywords):
                self._exit_offered = False
                self._exit_consumed = False
                self.avoidance_count = 0
                # Fall through to normal pipeline
            else:
                self._exit_offered = False
                self._exit_consumed = True
                self.avoidance_count = 0
                if msg_lower in ("yes", "yep", "sure", "ok", "okay"):
                    turn_result["response"] = "Sounds good — I'll check in tomorrow. Take care."
                    turn_result["state"] = self.state_machine.get_state_info()
                    turn_result["reasoning_context"] = self._build_reasoning_context(emotion)
                    turn_result["planner_decision"] = {
                        "action": "close_conversation", "mode": "closure",
                        "reason": "user accepted the exit offer", "confidence": 0.9,
                        "next_state": None, "metadata": {}}
                    self._save_turn(user_message, turn_result)
                    self._maybe_debug(turn_result)
                    return turn_result
                else:
                    turn_result["response"] = "No worries — want to talk about something else instead, or just chat casually for now?"
                    turn_result["options"] = ["Talk about something", "Just chat", "Maybe later"]
                    turn_result["state"] = self.state_machine.get_state_info()
                    turn_result["reasoning_context"] = self._build_reasoning_context(emotion)
                    turn_result["planner_decision"] = {
                        "action": "casual_chat", "mode": "casual_chat",
                        "reason": "user declined the exit offer", "confidence": 0.8,
                        "next_state": None, "metadata": {}}
                    self._save_turn(user_message, turn_result)
                    self._maybe_debug(turn_result)
                    return turn_result

        # Phase 4: Memory extraction (LLM-powered)
        memory_updates = self._extract_memory(user_message, emotion)
        turn_result["memory_updates"] = memory_updates

        # ─── Memory confirmation (deterministic, zero LLM) ───
        pending = self.agents.memory.get_pending_confirmation()
        if pending:
            accept = self._is_confirmation_accept(user_message)
            reject = None if accept else self._is_confirmation_reject(user_message)
            if accept or reject:
                resolved = self.agents.memory.resolve_pending_confirmation(accept=bool(accept))
                turn_result["confirmation"] = {
                    "resolved": True,
                    "accepted": bool(accept),
                    "result": resolved,
                }
                if self._is_bare_confirmation(user_message):
                    ack = ("Got it — I'll remember that going forward." if accept
                           else "No problem — I'll keep what you said earlier in mind.")
                    turn_result["response"] = ack
                    turn_result["options"] = None
                    turn_result["state"] = self.state_machine.get_state_info()
                    turn_result["reasoning_context"] = self._build_reasoning_context(emotion)
                    turn_result["planner_decision"] = {
                        "action": "confirm_understanding", "mode": None,
                        "reason": "memory confirmation resolved", "confidence": 0.9,
                        "next_state": None, "metadata": {}}
                    self._save_turn(user_message, turn_result)
                    self._maybe_debug(turn_result)
                    return turn_result

        if emotion.get("avoidance", 0) > 60:
            self.agents.memory.adjust_trust_score(-3)
        elif emotion.get("engagement", 0) > 60:
            self.agents.memory.adjust_trust_score(2)

        # Phase 3: State transition
        prev_state = self.state_machine.current_state
        next_state = self.state_machine.transition(emotion, user_message)
        if prev_state == "greeting" and next_state != "greeting":
            self.agents.memory.increment_session()
        turn_result["state"] = self.state_machine.get_state_info()

        # Phase 2: LLM-powered routing
        route = self._decide_route(emotion, user_message)
        turn_result["route"] = route

        # ─── Reasoning pipeline (deterministic, fixed order) ───
        # 1. memory  — updated above (Phase 4), before any reasoning
        # 2. behavior — update the learned behavior profile
        turn_result["behaviors"] = self.agents.behavior_engine.update(user_message, emotion)

        # 2b. beliefs — inferred from memory facts (facts never change; beliefs evolve)
        turn_result["beliefs"] = self.agents.belief_engine.update(self.agents.memory.get_all_facts())

        # 3. hypotheses — update active hypotheses
        turn_result["hypotheses"] = self.agents.hypothesis_engine.update(
            user_message, emotion, self.current_pillar, self.agents.memory.get_all_facts())

        # 4. why — refresh recurring patterns
        turn_result["whys"] = self.agents.why_engine.update()

        # 5. objective — select ONE coaching objective (deterministic)
        self.current_objective = self.agents.objective_engine.determine(
            state_info=self.state_machine.get_state_info(),
            user_message=user_message,
            emotion=emotion,
            memory_facts=self.agents.memory.get_all_facts(),
            previous_objective=self.current_objective,
            current_pillar=self.current_pillar,
            avoidance_count=self.avoidance_count,
            exit_offered=self._exit_offered,
            active_traits=self.agents.behavior_engine.active_traits(),
            objective_history=self.agents.self_evaluator.get_track(),
            learning_boosts=self.agents.learning.objective_boosts() if self.enable_learning else None,
        )
        turn_result["objective"] = self.current_objective

        # 6. intervention — highest-ranked recommendation (ranked list if one exists)
        # 7. reasoning context — fused engine state, assembled before prompting
        self._build_reasoning_context(emotion)

        # 7b. Conversation Planner V2 — the single decision engine:
        #     every response originates from exactly one PlannerAction
        decision = self.agents.planner.decide(
            self._planner_context(route, emotion, turn_result.get("intent_graph", {})))
        turn_result["planner_decision"] = decision.to_dict()

        # 8. LLM generates natural language only, given the context
        resp_data = self._generate_response(route, emotion, user_message, self.reasoning_ctx, decision)

        # ─── Memory confirmation: append question or ack (deterministic) ───
        conf = turn_result.get("confirmation")
        if conf is None:
            pending = self.agents.memory.get_pending_confirmation()
            if pending and not pending.get("asked") and pending.get("question"):
                self.agents.memory.mark_confirmation_asked()
                conf = turn_result["confirmation"] = {"resolved": False, "question": pending["question"]}
        if conf:
            if conf.get("resolved") and conf.get("accepted") is not None:
                ack = ("Got it — I'll remember that going forward." if conf.get("accepted")
                       else "No problem — I'll keep what you said earlier in mind.")
                resp_data["text"] = f"{ack} {resp_data['text']}"
            elif conf.get("question"):
                resp_data["text"] = f"{resp_data['text']}\n\n{conf['question']}"

        turn_result["response"] = resp_data["text"]
        turn_result["options"] = resp_data["options"]
        turn_result["ranked_interventions"] = self._ranked_interventions[:5]
        turn_result["reasoning_context"] = self.reasoning_ctx
        # State may have changed inside response generation (category tree,
        # repeat-break): refresh so the API/judge see the real current state
        turn_result["state"] = self.state_machine.get_state_info()

        self._save_turn(user_message, turn_result)
        if self.enable_auto_judge:
            self._maybe_judge_conversation(turn_result)
        self.last_turns.append({            "user": user_message,
            "assistant": resp_data["text"],
            "state": next_state,
            "emotion": {k: v for k, v in emotion.items() if k in ("primary_emotion", "emotional_intensity", "risk_flag")}
        })
        if len(self.last_turns) > 10:
            self.last_turns = self.last_turns[-10:]

        self._maybe_debug(turn_result)
        return turn_result

    # ─── DEBUG=true terminal diagnostics (never in responses) ─

    def _maybe_debug(self, turn_result):
        if os.environ.get("DEBUG", "").strip().lower() not in ("true", "1", "yes"):
            return
        state = turn_result.get("state")
        if isinstance(state, dict):
            state = state.get("current_state")
        obj = self.current_objective or {}
        rctx = self.reasoning_ctx or {}
        facts = self.agents.memory.get_all_facts()
        top_facts = "; ".join(f"{f['key']}={f['value']}" for f in facts[-5:]) or "(none)"
        inter = self._ranked_interventions[0] if self._ranked_interventions else {}
        hyp = self.agents.hypothesis_engine.get_active(min_confidence=40)[:5]
        print("\n── DEBUG ──────────────────────────────────────────────")
        print(f"user        : {(turn_result.get('user_message') or '')[:80]}")
        print(f"emotion     : {(turn_result.get('emotion') or {}).get('primary_emotion')} "
              f"intensity={(turn_result.get('emotion') or {}).get('emotional_intensity')} "
              f"risk={bool(turn_result.get('risk_detected'))}")
        print(f"state       : {state}")
        print(f"objective   : {obj.get('objective')} (priority={obj.get('priority')}) "
              f"reason={obj.get('reason')}")
        print(f"traits      : {self.agents.behavior_engine.active_traits()}")
        print(f"hypotheses  : {[(h['hypothesis'], h['confidence']) for h in hyp]}")
        print(f"why         : {[(p.get('pattern'), p.get('repeats'), p.get('confidence')) for p in self.agents.why_engine.get_patterns()[:3]]}")
        print(f"intervention: {inter.get('action', '(none)')} "
              f"confidence={inter.get('confidence')} urgency={inter.get('urgency')}")
        print(f"rctx        : objective={rctx.get('conversation_objective')} "
              f"mode={rctx.get('conversation_mode')} style={rctx.get('response_style')} "
              f"hyp={len(rctx.get('active_hypotheses') or [])} "
              f"learning={'on' if rctx.get('learning_summary') else 'off'}")
        print(f"memory      : {len(facts)} facts | {top_facts}")
        eval_ = self._last_eval or {}
        print(f"evaluation  : {eval_.get('objective')} completed={eval_.get('objective_completed')} "
              f"confidence={eval_.get('confidence')} ({eval_.get('reason')})")
        print("──────────────────────────────────────────────────────")

    # ─── AI Conversation Judge: score when a conversation ends ─

    _END_OBJECTIVES = ("close_conversation", "encourage_reflection")

    def _maybe_judge_conversation(self, turn_result):
        objective = turn_result.get("objective")
        name = objective.get("objective") if isinstance(objective, dict) else objective
        state = turn_result.get("state")
        if isinstance(state, dict):
            state = state.get("current_state")
        is_end = name in self._END_OBJECTIVES or state == "reflection"
        if not is_end:
            self._judged_objective = None
            return
        if self._judged_objective == "reflection" and state == "reflection":
            return
        if self._judged_objective and self._judged_objective == name:
            return
        self._judged_objective = "reflection" if state == "reflection" else name
        session = load_json(self.session_path) or {}
        payload = {
            "turns": session.get("turns", []),
            "memory": self.agents.memory.get_all_facts(),
            "trust_score": self.agents.memory.get_trust_score(),
            "reasoning_context": self.reasoning_ctx,
        }
        conv_id = f"{self.user_id}_{(session.get('created') or now_iso())[:19].replace(':', '')}"
        meta = {"source": "live", "session_id": self.user_id}
        turn_result["judge"] = self.agents.conversation_judge.evaluate(
            payload, meta=meta, conversation_id=conv_id)

        if self.enable_learning:
            try:
                self._learn_from_conversation(payload, turn_result["judge"])
            except Exception:
                pass  # learning must never break the conversation

    def _learn_from_conversation(self, payload, judge_result):
        """Per-user learning pass at conversation end (never cross-user).

        Updates behavior confidence, hypotheses, intervention success,
        conversation style, coaching style, and objective success; then applies
        the improved behavior profile and hypothesis confidence for next time.
        """
        summary = self.agents.learning.record_conversation(
            turns=payload.get("turns", []),
            memory_facts=payload.get("memory", []),
            traits=self.agents.behavior_engine.get_traits(),
            hypotheses=self.agents.hypothesis_engine.get_hypotheses(),
            objective_track=self.agents.self_evaluator.get_track(),
            judge_result=judge_result,
            reasoning_context=self.reasoning_ctx,
        )
        for trait, confidence in self.agents.learning.behavior_confidences().items():
            self.agents.behavior_engine.calibrate(trait, confidence)
        for hypothesis in self.agents.learning.confirmed_hypotheses():
            self.agents.hypothesis_engine.support_hypothesis(
                hypothesis, snippet="validated over multiple conversations")
        return summary

    # ─── LLM-Integrated Phase 5: Emotion ──────────────────────

    def _analyze_emotion(self, user_message):
        llm_result = self.llm.extract_emotion(user_message, self.last_turns)
        if llm_result and llm_result.get("primary_emotion"):
            return llm_result
        return self.agents.emotion_engine.analyze(user_message, self.last_turns[-3:])

    # ─── LLM-Integrated Phase 4: Memory ───────────────────────

    def _extract_memory(self, user_message, emotion):
        existing = self.agents.memory.get_session_summary()
        llm_facts = self.llm.extract_memory(user_message, existing)

        if llm_facts:
            stored = []
            for fact in llm_facts:
                if isinstance(fact, dict) and fact.get("key") and fact.get("value"):
                    result = self.agents.memory.add_fact(
                        category=fact.get("category", "identity"),
                        key=fact["key"],
                        value=fact["value"],
                        confidence=min(95, fact.get("confidence", 70)),
                        source=fact.get("source", "conversation"),
                        message=user_message
                    )
                    stored.append(result)
            if stored:
                return stored

        return self.agents.extract_and_store(user_message, emotion)

    # ─── Phase 2: LLM-Powered Routing ─────────────────────────

    def _decide_route(self, emotion, user_message):
        state = self.state_machine.current_state
        state_info = self.state_machine.get_state_info()

        # Base: always run these
        route = ["emotion_detection", "memory_manager"]

        # State-based routing rules (always applied)
        if state in ("guided_discovery", "pillar_selection", "deep_investigation"):
            route.append("question_planner")
            if state == "deep_investigation" and self.current_pillar:
                route.append("root_cause_engine")
        if state == "routine_planning" and self.current_insight:
            route.append("routine_generator")
        if state == "insight_generation" and not state_info.get("insight_delivered"):
            if self.current_pillar:
                route.append("root_cause_engine")

        # LLM can supplement but not override state-based routing
        if self.llm.is_available() and user_message.strip():
            mem_snapshot = {
                "state": state,
                "pillar": self.current_pillar,
                "trust_score": self.agents.memory.get_trust_score(),
                "insight_delivered": state_info.get("insight_delivered"),
                "routine_created": state_info.get("routine_created"),
            }
            llm_result = self.llm.route_turn(user_message, state, mem_snapshot, self.last_turns)
            if llm_result and "route" in llm_result:
                extra = [a for a in llm_result["route"] if a not in route and a != "risk_protocol"]
                route.extend(extra)

        return route

    # ─── Conversation Planner V2: deterministic decision context ───

    def _planner_context(self, route, emotion, intent_graph):
        msg = self._last_user_message or ""
        msg_lower = msg.strip().lower()
        emotion_words = set(["sad", "lonely", "down", "tired", "anxious",
                             "stressed", "overwhelm", "burnout"])
        return {
            "message": msg,
            "intent_graph": intent_graph or {},
            "emotion": emotion or {},
            "state": self.state_machine.current_state,
            "state_info": self.state_machine.get_state_info(),
            "route": list(route),
            "current_pillar": self.current_pillar,
            "objective": (self.current_objective or {}).get("objective"),
            "avoidance_count": self.avoidance_count,
            "exit_offered": self._exit_offered,
            "exit_consumed": self._exit_consumed,
            "minimal_input": not msg.strip() or len(msg.strip().split()) < 3,
            "has_emotion_keyword": any(w in msg_lower for w in emotion_words),
        }

    # ─── Response Generation (LLM-enhanced) ───────────────────

    def _generate_response(self, route, emotion, user_message, reasoning_ctx=None, decision=None):
        """Execute the planner's decision — every response originates from one PlannerAction."""
        state = self.state_machine.current_state
        action = (decision.action.value if decision else None) or "ask_question"
        meta = (decision.metadata or {}) if decision else {}

        # ─── Ranked interventions: user asked for more (deterministic rail) ───
        more = self._next_intervention_response(user_message)
        if more:
            resp = more
        elif action == "escalate":
            resp = {"text": self._risk_response(meta.get("risk_reason", "")), "options": None}
        elif action == "answer_capability":
            resp = self._capability_response()
        elif action == "answer_direct_question":
            resp = self._answer_direct_question(user_message)
        elif action == "switch_topic":
            resp = self._switch_topic_response(decision)
        elif action == "resume_topic":
            resp = self._resume_topic_response(decision, emotion, reasoning_ctx)
        elif action == "create_commitment":
            resp = self._commitment_response()
        elif action == "schedule_action":
            resp = self._scheduling_response()
        elif action == "close_conversation":
            resp = self._close_response(meta)
        elif action == "summarize":
            resp = self._summarize_response()
        elif action == "check_progress":
            resp = self._follow_up_response()
        elif action == "reflect":
            resp = self._reflection_response()
        elif action == "casual_chat":
            resp = self._casual_chat_response(meta, state)
        elif action == "wait":
            resp = self._wait_response(meta)
        elif action == "clarify":
            if meta.get("force_choice"):
                resp = self._force_choice_response()
            elif meta.get("quick_tree"):
                resp = self._quick_tree_response(user_message)
            else:
                resp = self._question_response(emotion, reasoning_ctx)
        elif action == "confirm_understanding":
            resp = self._confirm_response(decision, user_message)
        elif action == "provide_insight":
            if meta.get("insight"):
                resp = self._insight_response()
            else:
                resp = self._insight_variant_response()
        elif action == "provide_recommendation":
            resp = self._routine_response()
        elif action == "ask_question":
            if meta.get("greeting"):
                resp = self._greeting_response()
            elif meta.get("soft"):
                resp = self._soft_response()
            elif meta.get("default"):
                resp = self._default_response()
            else:
                resp = self._question_response(emotion, reasoning_ctx)
        elif action == "explore_topic":
            resp = self._question_response(emotion, reasoning_ctx)
        else:
            import logging
            logging.warning(
                f"[UNHANDLED ACTION] No response handler for action={action} "
                f"state={state} user={user_message!r}"
            )
            resp = self._default_response()

        resp["action"] = action
        text = resp.get("text", "")
        options = resp.get("options")

        # ─── Repetition safeguard ───
        if text == self._last_response_text and state == self._last_response_state:
            self._repeat_count += 1
            if self._repeat_count >= 3:
                import logging
                logging.critical(
                    f"[LOOP DETECTED] State '{state}' repeated {self._repeat_count}x "
                    f"(user: {user_message!r}) — forcing state break to free_conversation"
                )
                self.state_machine.set_state("free_conversation")
                text = "Let's try a different angle. What's one thing you'd like help with today?"
                options = ["My mood", "My habits", "My thoughts", "Not sure"]
                self._repeat_count = 0
                self._last_response_text = text
                self._last_response_state = "free_conversation"
            else:
                import logging
                logging.warning(
                    f"[REPEAT] State '{state}' produced verbatim repeat #{self._repeat_count} "
                    f"(user: {user_message!r}) — route was {route}"
                )
                # Force a variant from a different tone to break the loop
                forced = next(self._response_cyclers.get(state, self._response_cyclers["default"]))
                if forced != text:
                    text = forced
                else:
                    text = next(self._response_cyclers["default"])
        else:
            self._repeat_count = 0
            self._last_response_text = text
            self._last_response_state = state

        resp["text"] = text
        resp["options"] = options
        return resp

    # ─── Decision executors (each maps one PlannerAction to a response) ───

    def _greeting_response(self):
        session_num = self.agents.memory.memory.get("session_count", 1)
        known = self.agents.memory.get_known_pillars()
        opts = self.agents.question_planner.generate_question(
            "mood", "greeting", memory_context={})
        options = opts.get("options") or opts.get("response_options")
        proactive = self._proactive_checkin()
        if proactive and session_num > 1:
            text = proactive["question"]
        elif session_num <= 1:
            text = "Hey there. I'm your wellness companion. I'm here to help you understand yourself better — no judgment, no agenda. How are you feeling today?"
        else:
            pillars_known = list(known.keys())
            if pillars_known:
                text = f"Welcome back. Last time we touched on {pillars_known[0]}. How have things been since we talked?"
            else:
                text = "Welcome back. I'm glad you're here. What's on your mind today?"
        return {"text": text, "options": options}

    def _force_choice_response(self):
        text = "Which of these areas feels most relevant right now?"
        base = ["😴 Sleep", "💼 Work", "💛 Relationships", "😰 Stress"]
        if self.current_pillar:
            highlighted = [p.title() for p in [self.current_pillar] if p]
            others = [b for b in base if b.split()[1].lower() != (self.current_pillar or "").lower()][:2]
            options = highlighted + others + ["Something else", "Let me explain"]
        else:
            options = base + ["Something else", "Let me explain"]
        return {"text": text, "options": options}

    def _exit_offer_response(self):
        text = "Totally okay — I'm here whenever you want to dig into something. Want me to just check in tomorrow instead?"
        options = ["Yes", "No"]
        self._exit_offered = True
        return {"text": text, "options": options}

    def _casual_offer_response(self):
        text = "No pressure at all. Want to just chat about your day instead?"
        options = ["Sure", "Not really", "Maybe later"]
        return {"text": text, "options": options}

    def _quick_tree_response(self, user_message):
        state = self.state_machine.current_state
        # Hierarchical category tree (minimal talk, high-level choices)
        msg_lower = user_message.strip().lower()
        sub_categories = {
            "mental": ["sadness / low mood", "loneliness", "anxiety / worry", "motivation gap"],
            "productivity": ["overwhelm", "procrastination", "focus / distraction", "work-life balance"],
            "physical": ["sleep", "energy / fatigue", "movement / exercise", "nutrition"],
        }
        selected_sub = None
        selected_category = None

        def _fuzzy_match(word, targets, threshold=0.6):
            word = word.strip().lower()
            for t in targets:
                t_clean = t.strip().lower()
                if word == t_clean:
                    return t
                if len(word) > 2 and word[0] == t_clean[:1]:
                    ratio = SequenceMatcher(None, word, t_clean).ratio()
                    if ratio >= threshold:
                        return t
            return None

        for cat, subs in sub_categories.items():
            for sub in subs:
                if sub in msg_lower:
                    selected_sub = sub
                    selected_category = cat
                    break
                for word in msg_lower.split():
                    matched = _fuzzy_match(word, [sub.split(" / ")[0], sub], threshold=0.55)
                    if matched:
                        selected_sub = sub
                        selected_category = cat
                        break
                if selected_sub:
                    break
            if selected_sub:
                break
        # If user just selected a sub-category, treat as engagement, not avoidance
        if selected_sub:
            self.avoidance_count = 0
            self._exit_offered = False
            self.current_pillar = selected_sub
            self.state_machine.current_state = "deep_investigation"
            text = f"Got it — let's focus on {selected_sub}. What's been showing up for you around that?"
            options = ["Every day", "A few times a week", "Rarely", "Not sure yet"]
            return {"text": text, "options": options}
        # Otherwise show top-level categories (with fuzzy matching)
        productivity_keywords = ["productivity", "focus", "procrastination", "work", "overwhelm", "work-life"]
        physical_keywords = ["physical", "sleep", "energy", "exercise", "movement", "nutrition"]
        mental_keywords = ["mental", "sad", "lonely", "anxiety", "motivation", "gap", "sadness", "loneliness"]

        def _any_match(words, keywords):
            for w in words:
                if _fuzzy_match(w, keywords, threshold=0.55):
                    return True
            return False

        msg_words = msg_lower.split()
        if _any_match(msg_words, productivity_keywords):
            text = "Within productivity, which fits best?"
            options = ["Overwhelm", "Procrastination", "Focus / Distraction", "Work-life balance"]
        elif _any_match(msg_words, physical_keywords):
            text = "Within physical health, which fits best?"
            options = ["Sleep", "Energy / Fatigue", "Movement / Exercise", "Nutrition"]
        elif _any_match(msg_words, mental_keywords):
            text = "Within mental wellness, which fits best?"
            options = ["Sadness / Low mood", "Loneliness", "Anxiety / Worry", "Motivation gap"]
        else:
            text = next(self._response_cyclers["quick_path"])
            options = ["Productivity", "Physical health", "Mental wellness"]
        return {"text": text, "options": options}

    def _question_response(self, emotion, reasoning_ctx):
        q_data = self._generate_question(emotion, reasoning_ctx)
        return {"text": q_data["question_text"], "options": q_data.get("response_options")}

    def _insight_response(self):
        return {"text": self._generate_insight(), "options": ["Yes, that's it", "Partly", "Not quite"]}

    def _insight_variant_response(self):
        return {"text": next(self._response_cyclers["insight_generation"]),
                "options": ["Yes, that's it", "Partly", "Not quite"]}

    def _routine_response(self):
        return {"text": self._generate_routine_suggestion(), "options": self._intervention_options()}

    def _close_response(self, meta=None):
        meta = meta or {}
        if meta.get("commitment_done"):
            return {"text": "Perfect — that's a plan. I'll check in on how it goes. Take care until then.",
                    "options": None}
        if meta.get("graceful"):
            return {"text": "No worries at all — I'll be here whenever you're ready. Take care.",
                    "options": None}
        text = "I'm glad you checked in. Let's leave it here for today — I'll be here whenever you need me. Anything you want to take with you from this conversation?"
        return {"text": text, "options": ["Good for today", "One more thing"]}

    def _reflection_response(self):
        llm_close = self.llm.generate_reflection(
            self.state_machine.get_state_info(), self.last_turns)
        text = llm_close or self.agents.reflection_response(self.state_machine.get_state_info())
        return {"text": text, "options": ["Good for today", "One more thing"]}

    def _follow_up_response(self):
        return {"text": next(self._response_cyclers["follow_up"]), "options": ["Better", "Same", "Rougher"]}

    def _free_conversation_response(self):
        return {"text": next(self._response_cyclers["free_conversation"]), "options": None}

    def _rapport_response(self):
        return {"text": next(self._response_cyclers["rapport_building"]),
                "options": ["🙂 Good", "😑 Meh", "Rough one"]}

    def _avoidance_response(self):
        return {"text": next(self._response_cyclers["avoidance_detection"]),
                "options": ["Keep talking", "Switch topics", "Check in later"]}

    def _soft_response(self):
        return {"text": next(self._response_cyclers["soft_exploration"]),
                "options": ["A specific thing", "Just talking helps", "Not sure yet"]}

    def _default_response(self):
        return {"text": next(self._response_cyclers["default"]), "options": None}

    def _casual_chat_response(self, meta, state):
        if meta.get("casual_offer"):
            return self._casual_offer_response()
        if meta.get("rapport"):
            return self._rapport_response()
        if state == "free_conversation":
            return self._free_conversation_response()
        return {"text": next(self._response_cyclers["casual"]), "options": None}

    def _wait_response(self, meta):
        if meta.get("exit_offer"):
            return self._exit_offer_response()
        if meta.get("avoidance"):
            return self._avoidance_response()
        if meta.get("commitment_pause"):
            return {"text": "No rush at all — just let me know whenever you've decided.", "options": None}
        if meta.get("loop_break"):
            return {"text": "Let's try a different angle. What's one thing you'd like help with today?",
                    "options": ["My mood", "My habits", "My thoughts", "Not sure"]}
        return {"text": "I'm here. Take your time — whenever you're ready, we can pick this back up.",
                "options": None}

    def _confirm_response(self, decision, user_message):
        text = f"So to make sure I've got it right — {user_message.strip()}. Is that the gist?"
        return {"text": text, "options": ["Yes", "Partly", "Not quite"]}

    def _capability_response(self):
        text = ("Here's what I can help with: sleep, stress, work and life balance, "
                "relationships, mood, motivation, exercise, routines, nutrition, and finances. "
                "We can explore what's going on, spot patterns across your habits, and take "
                "small next steps together. What would be most helpful right now?")
        return {"text": text, "options": None}

    def _answer_direct_question(self, user_message):
        llm_answer = self.llm.generate_answer(user_message, self._answer_context()) \
            if self.llm.is_available() else ""
        if llm_answer:
            return {"text": llm_answer, "options": None}
        return {"text": self._rule_answer(), "options": None}

    def _answer_context(self):
        why = self.agents.why_engine.get_top()
        hyps = self.agents.hypothesis_engine.get_active(min_confidence=50)[:3]
        return {
            "pillar": self.current_pillar,
            "state": self.state_machine.current_state,
            "facts": self.agents.memory.get_all_facts()[-8:],
            "pattern": why.get("human") if why else None,
            "pattern_repeats": why.get("repeats", 1) if why else None,
            "hypotheses": [h.get("hypothesis") for h in hyps],
            "trust_score": self.agents.memory.get_trust_score(),
        }

    def _rule_answer(self):
        why = self.agents.why_engine.get_top()
        if why and why.get("human"):
            return (f"Here's what stands out from what you've shared: {why['human']}. "
                    f"It looks like this has shown up {why.get('repeats', 1)} times now — "
                    f"want to look at what's driving it together?")
        hyps = self.agents.hypothesis_engine.get_active(min_confidence=50)
        if hyps:
            hypothesis = hyps[0]["hypothesis"]
            return (f"Based on what you've told me, the pattern I'm noticing most is around "
                    f"{hypothesis.lower()}. It's not a diagnosis — just a thread worth pulling. "
                    f"Want to explore it together?")
        facts = self.agents.memory.get_all_facts()
        if facts:
            top = "; ".join(f"{f.get('key')}={f.get('value')}" for f in facts[-3:])
            return (f"From what you've shared so far — {top} — these things usually feed each "
                    f"other. Want to look at which one is heaviest for you right now?")
        return ("That's a fair question, and I don't want to guess. The honest answer is that "
                "these feelings usually come from a mix of sleep, stress, and routine — but yours "
                "could be different. Want to look at what's most relevant for you?")

    def _switch_topic_response(self, decision):
        meta = decision.metadata or {}
        target = meta.get("target_topic")
        if target in PILLARS and target != self.current_pillar:
            self.current_pillar = target
            self.state_machine.select_pillar(target)
            self.agents.question_planner.reset_deep_count()
        if target:
            text = f"Happy to switch gears. What's been going on with {target}?"
        else:
            text = "Happy to switch gears. What's on your mind now?"
        return {"text": text, "options": None}

    def _resume_topic_response(self, decision, emotion, reasoning_ctx):
        target = (decision.metadata or {}).get("target_topic")
        if target in PILLARS and target != self.current_pillar:
            self.current_pillar = target
            self.state_machine.select_pillar(target)
            self.agents.question_planner.reset_deep_count()
        q_data = self._generate_question(emotion, reasoning_ctx)
        if self.current_pillar:
            q_data = dict(q_data)
            q_data["question_text"] = f"Back to what we were exploring — {q_data['question_text']}"
        return {"text": q_data["question_text"], "options": q_data.get("response_options")}

    def _commitment_response(self):
        rec = self._ranked_interventions[0] if self._ranked_interventions else {}
        action_text = rec.get("action", "that step")
        text = (f"That's a great choice. To make it stick, one small commitment is enough: "
                f"{action_text}. Would tomorrow morning be a good time to try this?")
        return {"text": text, "options": ["Tomorrow morning", "Tonight", "This weekend", "Not right now"]}

    def _scheduling_response(self):
        return {"text": "Great — what time of day would work best for you to actually do it?",
                "options": ["Morning", "Midday", "Evening", "Anytime"]}

    def _summarize_response(self):
        pillar = self.current_pillar or "what we explored"
        facts = self.agents.memory.get_facts_by_pillar(self.current_pillar)[-3:] \
            if self.current_pillar else []
        summary = ""
        if facts:
            summary = " " + "; ".join(f"{f.get('key')}={f.get('value')}" for f in facts)
        text = (f"Today we explored {pillar}{summary}. "
                f"Whenever you're ready, we can pick this back up — or close here for now. "
                f"Want to keep going?")
        return {"text": text, "options": ["Good for today", "One more thing"]}

    # ─── LLM-Integrated Phase 7: Questions ────────────────────

    def _generate_question(self, emotion, reasoning_ctx=None):
        ctx = reasoning_ctx or self.reasoning_ctx or {}
        if self.state_machine.current_state == "deep_investigation" and self.current_pillar:
            pillar = self.current_pillar
        else:
            known = self.agents.memory.get_known_pillars()
            unknown = self.agents.memory.get_unknown_pillars()
            hinted_pillar = self.agents.objective_engine.pillar_hint(
                (self.current_objective or {}).get("objective"))
            if hinted_pillar:
                pillar = hinted_pillar
            else:
                planner_result = self.agents.planner.select_target_pillar(
                    known_pillars=known,
                    unknown_pillars=unknown,
                    current_state=self.state_machine.current_state,
                    latest_emotion_scores=emotion,
                    user_message=self._last_user_message
                )
                pillar = planner_result["target_pillar"]
            if self.state_machine.current_state in ("guided_discovery", "pillar_selection"):
                self.state_machine.select_pillar(pillar)
                self.current_pillar = pillar
                # Reset deep count on new pillar
                self.agents.question_planner.reset_deep_count()

        # Try LLM-generated question first
        type_hint = self.agents.objective_engine.question_type_hint(
            (self.current_objective or {}).get("objective"))
        behavior_hint = self._behavior_question_hint()
        if behavior_hint:
            type_hint = behavior_hint
        llm_q = self.llm.generate_question(
            target_pillar=pillar,
            current_state=self.state_machine.current_state,
            question_type_hint=type_hint,
            memory_context={"beliefs": [f"{b['belief']} ({b['confidence']}%)"
                                        for b in self.agents.belief_engine.get_top(3) or []],
                            "trust_score": self.agents.memory.get_trust_score(),
                            "pillar": pillar,
                            "recent_topic": self._last_user_message,
                            "leading_hypothesis": (self.agents.hypothesis_engine.get_leading() or {}).get("hypothesis"),
                            "recurring_pattern": self._recurring_pattern_text(),
                            "conversation_objective": ctx.get("conversation_objective") or "",
                            "objective_reason": ctx.get("objective_reason") or "",
                            "behavior_traits": ctx.get("behavior_traits") or [],
                            "conversation_mode": ctx.get("conversation_mode") or "",
                            "response_style": ctx.get("response_style") or ""}
        )
        if llm_q and llm_q.get("question_text"):
            result = {
                "question_text": llm_q["question_text"],
                "response_options": llm_q.get("response_options") or self._fallback_options_for_state()
            }
            self.last_question = result
            return result

        # Fallback to template
        q_data = self.agents.question_planner.generate_question(
            target_pillar=pillar,
            current_state=self.state_machine.current_state,
            preferred_type_hint=type_hint,
            memory_context={"trust_score": self.agents.memory.get_trust_score()}
        )
        result = {
            "question_text": q_data.get("question_text") or q_data.get("text", ""),
            "response_options": q_data.get("response_options") or q_data.get("options") or self._fallback_options_for_state()
        }
        self.last_question = result
        return result

    def _fallback_options_for_state(self):
        state = self.state_machine.current_state
        opts = {
            "guided_discovery": ["Yes, that's it", "Also something else", "Not really that"],
            "pillar_selection": ["This one", "Something else", "Let me explain"],
            "deep_investigation": ["Tell me more", "Something else", "Let me explain"],
            "routine_planning": ["All of them", "Just one", "Not right now"],
        }
        return opts.get(state, ["Yes", "No", "Let me explain"])

    def _recurring_pattern_text(self):
        top = self.agents.why_engine.get_top()
        if not top:
            return None
        human = top.get("human")
        if human:
            return f"{human} (repeated {top['repeats']}x, {top['confidence']}% confidence)"
        return f"{top['pattern']} (repeated {top['repeats']}x, {top['confidence']}%)"

    def _proactive_checkin(self):
        if self._proactive_asked:
            return None
        checkin = self.agents.proactive_engine.checkin()
        if checkin:
            self._proactive_asked = True
            self.last_checkin = checkin
            return checkin
        return None

    # ─── Reasoning Context (deterministic, assembled before prompting) ───

    def _build_reasoning_context(self, emotion=None, risk_flag=False):
        """Fuse engine outputs into the ReasoningContext object (no LLM calls)."""
        objective = self.current_objective or {}
        hypotheses = self.agents.hypothesis_engine.get_active(min_confidence=50)[:3]
        traits = self.agents.behavior_engine.get_traits()
        active_traits = [name for name, entry in traits.items()
                         if entry.get("status") == "active"]
        patterns = sorted(self.agents.why_engine.get_patterns(),
                          key=lambda p: p.get("confidence", 0), reverse=True)[:3]
        intervention = self._ranked_interventions[0] if self._ranked_interventions else {}

        facts = self.agents.memory.get_all_facts()
        fact_confidences = [f.get("confidence", 0) for f in facts if isinstance(f, dict)]
        confidence_summary = {
            "trust_score": self.agents.memory.get_trust_score(),
            "fact_count": len(facts),
            "avg_fact_confidence": int(sum(fact_confidences) / len(fact_confidences)) if fact_confidences else 0,
            "active_hypotheses": len(hypotheses),
            "top_pattern_confidence": patterns[0].get("confidence", 0) if patterns else 0,
            "objective_confidence": objective.get("confidence", 0) or 0,
            "behavior_trait_count": len(active_traits),
            "intervention_confidence": intervention.get("confidence", 0),
        }
        # Beliefs first, facts second: memory facts stay untouched, beliefs are the
        # conversation-facing interpretation of them.
        memory_summary = {
            "beliefs": self.agents.belief_engine.get_top(3),
            "session_summary": self.agents.memory.get_session_summary(),
        }

        self.reasoning_ctx = build_reasoning_context(
            objective=objective,
            active_hypotheses=hypotheses,
            behavior_traits=active_traits,
            top_patterns=patterns,
            recommended_intervention=intervention,
            state=self.state_machine.current_state,
            risk_flag=risk_flag,
            confidence_summary=confidence_summary,
            memory_summary=memory_summary,
            learning_summary=self._learning_summary() if self.enable_learning else None,
        )
        return self.reasoning_ctx

    def _learning_summary(self):
        """Per-user learning signals for the response prompt (privacy-safe).

        Only shown once this user has completed a conversation; empty profile
        returns None so prompts are byte-identical for new/offline users.
        """
        if not self.agents.learning.learning_active():
            return None
        return {
            "conversations_learned": self.agents.learning.profile().get("conversations_learned", 0),
            "conversation_style": self.agents.learning.conversation_style(),
            "coaching_style": self.agents.learning.coaching_style(),
            "pattern_confidence": self.agents.learning.pattern_confidence(),
        }

    # ─── Memory confirmation reply detection ──────────────────

    def _is_confirmation_accept(self, message):
        msg = (message or "").strip().lower()
        if not msg:
            return False
        if msg in _CONFIRM_ACCEPT:
            return True
        return any(msg.startswith(t) for t in _CONFIRM_ACCEPT
                   if t not in ("right", "true", "sure"))

    def _is_confirmation_reject(self, message):
        msg = (message or "").strip().lower()
        if not msg:
            return False
        if msg in _CONFIRM_REJECT:
            return True
        return any(msg.startswith(t) for t in _CONFIRM_REJECT
                   if t not in ("nah",))

    def _is_bare_confirmation(self, message):
        return (message or "").strip().lower() in {
            "yes", "yeah", "yep", "yup", "sure", "correct",
            "no", "nope", "nah",
        }

    # ─── Behavior-aware question styling ─────────────────────

    def _behavior_question_hint(self):
        active = set(self.agents.behavior_engine.active_traits())
        if "overwhelmed_by_choices" in active:
            return "scaling"
        if "prefers_short_answers" in active:
            return "choice"
        if "analytical" in active:
            return "scaling"
        if "reflective_thinker" in active:
            return "reflective"
        if "avoids_discussing_emotions" in active:
            return "future"
        return ""

    # ─── LLM-Integrated Phase 8: Root Cause ───────────────────

    def _generate_insight(self):
        MIN_CONFIDENCE = 60
        facts = [f for f in self.agents.memory.get_facts_by_pillar(self.current_pillar)
                 if f.get("confidence", 0) >= MIN_CONFIDENCE]
        if self.enable_learning:
            facts = self.agents.learning.reorder_facts(facts)
        emotions = [e for e in self.agents.memory.get_emotional_history()
                    if e.get("confidence", 0) >= MIN_CONFIDENCE]
        habits = self.agents.memory.get_habit_trends()

        llm_result = self.llm.analyze_root_cause(self.current_pillar, facts, emotions, habits)
        if llm_result and llm_result.get("likely_root_cause"):
            result = llm_result
        else:
            result = self.agents.root_cause_analyzer.analyze(
                pillar=self.current_pillar,
                memory_facts=facts,
                emotion_history=emotions,
                habit_trends=habits
            )

        self.current_insight = result
        # Only strengthen hypotheses the engine already tracks — never let an
        # LLM string mint a brand-new hypothesis name (hypotheses are engine-owned)
        from .hypothesis_engine import canonical
        if canonical(result["likely_root_cause"]) in self.agents.hypothesis_engine.get_hypotheses():
            self.agents.hypothesis_engine.support_hypothesis(result["likely_root_cause"])
        active_hyps = self.agents.hypothesis_engine.get_active(min_confidence=50)

        if len(active_hyps) >= 2:
            top = active_hyps[:3]
            lines = "; ".join(f"{h['hypothesis']} ({h['confidence']}%)" for h in top)
            response = ("Based on what you've shared, a few patterns stand out and I'm still weighing them: "
                        + lines + ". "
                        + "Which one resonates most with you? That'll help me narrow it down before we plan next steps.")
        else:
            chain_summary = "; ".join(
                f"{o['observation']} ({o['confidence']}% confidence)"
                for o in result.get("chain", [])
            )
            response = f"Based on what you've shared, here's what I'm noticing: {chain_summary}. "
            response += f"The pattern that stands out most is: {result['likely_root_cause']}. "
            response += "This is based on what you've told me — it's not a diagnosis, just a way of connecting the dots."

        # Evidence-backed historical pattern, retrieved before responding
        if self.current_pillar:
            historical = self.agents.why_engine.get_relevant(self.current_pillar, min_confidence=70)
            if historical:
                human = historical.get("human")
                action = historical.get("action") or historical.get("recommendation", "")
                if human:
                    response += f"\n\n{human} {action}"
                else:
                    response += (f"\n\nOne pattern I've noticed across your history: {historical['pattern']} "
                                 f"— it's shown up {historical['repeats']} times. {action}")

        self.state_machine.mark_insight_delivered()
        return response

    # ─── LLM-Integrated Phase 9: Routines ─────────────────────

    def _generate_routine_suggestion(self):
        if not self.current_insight:
            self.current_insight = {"likely_root_cause": "building on what we've discussed", "probability": 50}

        facts = self.agents.memory.get_all_facts()
        ctx = self.reasoning_ctx or {}
        llm_routine = self.llm.generate_routine(
            root_cause_or_goal=self.current_insight["likely_root_cause"],
            memory_facts=facts,
            past_adherence={},
            constraints={"reasoning_context": {
                "conversation_objective": ctx.get("conversation_objective", ""),
                "objective_reason": ctx.get("objective_reason", ""),
                "behavior_traits": ctx.get("behavior_traits", []),
                "conversation_mode": ctx.get("conversation_mode", ""),
                "response_style": ctx.get("response_style", ""),
            }}
        )

        if llm_routine and llm_routine.get("actions"):
            routine = llm_routine
        else:
            routine = self.agents.routine_generator.generate(
                root_cause_or_goal=self.current_insight["likely_root_cause"],
                memory_facts=facts
            )

        self.current_routine = routine
        self.state_machine.mark_routine_created()

        # Learned retrieval: put facts about what works for this user first
        if self.enable_learning:
            facts = self.agents.learning.reorder_facts(facts)

        # Rank every recommendation (LLM or template) — deterministic, no LLM
        self._ranked_interventions = self.agents.intervention_rank.rank(
            actions=routine.get("actions", []),
            pillar=self.current_pillar,
            root_cause=self.current_insight.get("likely_root_cause", ""),
            facts=facts,
            emotions=self.agents.memory.get_emotional_history(),
            learning_weights=(self.agents.learning.intervention_weights()
                              if self.enable_learning else None),
        )
        self._intervention_index = 0
        if self.reasoning_ctx is not None:
            self.reasoning_ctx["recommended_intervention"] = (
                self._ranked_interventions[0] if self._ranked_interventions else {})

        if not self._ranked_interventions:
            actions_text = "\n".join(
                f"• {a['action']} ({a['time_of_day']}) — {a['why']}"
                for a in routine.get("actions", [])
            )
            return f"Here's a small plan based on what we've explored:\n{actions_text}\n\nWe can check in on how it's going. Sound good?"

        return self._intervention_response(0)["text"]

    # ─── Intervention Ranking presentation (deterministic) ────

    def _intervention_response(self, idx):
        items = self._ranked_interventions
        item = items[idx]
        if idx == 0:
            header = "Let's start with the one step I think matters most right now:\n"
        else:
            header = "Here's another option to consider:\n"
        text = (f"{header}\u2022 {item['action']} ({item['time_of_day']}) — {item['why']}\n\n"
                f"{item['reason']}.")
        if idx + 1 < len(items):
            text += "\n\nWant me to share more options, or does this feel right to start?"
        return {"text": text, "options": self._intervention_options()}

    def _intervention_options(self):
        remaining = len(self._ranked_interventions) - self._intervention_index - 1
        if remaining > 0:
            return ["Sounds good", "Show me more", "Not right now"]
        return ["Sounds good", "Not right now"]

    def _is_more_request(self, message):
        msg = (message or "").strip().lower()
        if not msg:
            return False
        if len(msg.split()) > 6:
            return False
        topic_guard = ["work", "sleep", "stress", "anxiety", "sad", "lonely", "mental",
                       "health", "focus", "energy", "mood", "tired", "motivation",
                       "productivity", "physical", "overwhelm", "burnout", "exercise",
                       "nutrition", "procrastination", "routine"]
        if any(t in msg for t in topic_guard):
            return False
        phrases = ["show me more", "show me another", "show me the rest", "more options",
                   "another one", "another", "one more", "what else", "anything else",
                   "any other", "more", "next one", "the rest", "others", "all of them",
                   "all of it", "give me more", "tell me more"]
        return any(p in msg for p in phrases)

    def _next_intervention_response(self, user_message):
        if not self._ranked_interventions or self._intervention_index < 0:
            return None
        if not self._is_more_request(user_message):
            return None
        if self._intervention_index + 1 < len(self._ranked_interventions):
            self._intervention_index += 1
            return self._intervention_response(self._intervention_index)
        return {"text": "That's everything I have for now. Which one feels doable to start with?",
                "options": ["This one", "Not right now"]}

    # ─── Crisis Response (LLM-enhanced) ───────────────────────

    def _risk_response(self, reason):
        llm_response = self.llm.generate_crisis_response(self._last_user_message, reason)
        if llm_response:
            return llm_response
        return ("I'm really glad you told me this. What you're feeling matters, and you're not alone. "
                "Please reach out to a crisis service — they're trained to help right now. "
                "In the US, you can call or text 988 for immediate support. You matter, and help is available.")

    # ─── Persistence ──────────────────────────────────────────

    def _save_turn(self, user_message, turn_result):
        session = load_json(self.session_path)
        if not session:
            session = {"user_id": self.user_id, "turns": [], "created": now_iso()}
        turn = {
            "timestamp": now_iso(),
            "user_message": user_message,
            "response": turn_result.get("response"),
            "state": turn_result.get("state"),
            "objective": turn_result.get("objective"),
            "emotion_summary": {
                "primary": turn_result.get("emotion", {}).get("primary_emotion"),
                "intensity": turn_result.get("emotion", {}).get("emotional_intensity"),
                "risk": turn_result.get("risk_detected")
            }
        }
        session["turns"].append(turn)
        session["last_updated"] = now_iso()
        save_json(self.session_path, session)

        self._last_turn = {
            "state": (turn_result.get("state") or {}).get("current_state"),
            "objective": dict(self.current_objective) if self.current_objective else None,
            "traits": self.agents.behavior_engine.active_traits(),
            "risk": bool(turn_result.get("risk_detected")),
            "at": now_iso(),
        }

    def _evaluate_previous_turn(self, reply, emotion):
        self._last_eval = None
        snapshot = self._last_turn
        if not snapshot or snapshot.get("risk") or not snapshot.get("objective"):
            return
        result = self.agents.self_evaluator.evaluate(
            reply=reply,
            state=snapshot["state"],
            emotion=emotion,
            objective=snapshot["objective"],
            traits=snapshot["traits"],
        )
        self.agents.self_evaluator.record(result)
        self._last_eval = result

    def _load_session(self):
        data = load_json(self.session_path)
        if data and "turns" in data:
            last_turns = data["turns"][-10:]
            self.last_turns = [
                {"user": t.get("user_message"), "assistant": t.get("response"),
                 "state": t.get("state"), "emotion": t.get("emotion_summary", {})}
                for t in last_turns
            ]
            last_turn = data["turns"][-1] if data["turns"] else {}
            if last_turn.get("objective"):
                self.current_objective = last_turn["objective"]

    def get_summary(self):
        return {
            "user": self.user_id,
            "state": self.state_machine.get_state_info(),
            "memory": self.agents.memory.get_session_summary(),
            "current_pillar": self.current_pillar,
            "objective": self.current_objective,
            "behaviors": self.agents.behavior_engine.get_traits(),
            "hypotheses": self.agents.hypothesis_engine.get_hypotheses(),
            "whys": self.agents.why_engine.get_patterns()[:5],
            "beliefs": self.agents.belief_engine.get_beliefs()[:5],
            "pending_confirmation": self.agents.memory.get_pending_confirmation(),
            "last_checkin": self.last_checkin,
            "ranked_interventions": self._ranked_interventions,
            "reasoning_context": self.reasoning_ctx,
            "self_evaluation": self._last_eval,
            "evaluation_track": self.agents.self_evaluator.get_track(),
            "trust_score": self.agents.memory.get_trust_score(),
            "last_turns_count": len(self.last_turns),
            "llm_available": self.llm.is_available()
        }

    def reset_state(self):
        self.state_machine = ConversationStateMachine(self.agents.memory)
        self.current_pillar = None
        self.current_insight = None
        self.current_routine = None
        self.last_question = None
        self.current_objective = None
        self.last_checkin = None
        self._proactive_asked = False
        self._ranked_interventions = []
        self._intervention_index = 0
        self.reasoning_ctx = None
        self.avoidance_count = 0
        self._exit_offered = False
        self._exit_consumed = False
        self._last_response_text = None
        self._last_response_state = None
        self._repeat_count = 0
        self._response_cyclers = {k: itertools.cycle(v) for k, v in _MESSAGE_VARIANTS.items()}
        self.agents.planner.reset()
        self.agents.self_evaluator.reset()
        self._last_turn = None
        self.conversation_logger.end_conversation(self.user_id)
        self._last_eval = None
