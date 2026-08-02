"""Conversation Planner V2 — the single decision-making engine.

Implements docs/specifications/CONVERSATION_PLANNER_V2.md exactly:

- the planner never writes responses; it selects exactly one PlannerAction
- the LLM is responsible only for expressing that action naturally
- the planner operates within exactly one ConversationMode at any time
- Conversation Modes form an explicit state machine; DISCOVERY is entered
  once per conversation and never re-entered
- direct questions, capability questions, casual chat and topic switches
  are interruptions: they suspend the active mode and the previous mode
  always resumes
- recommendation acceptance creates a commitment; commitment flows
  CREATE_COMMITMENT -> SCHEDULE_ACTION -> CLOSURE
- loop prevention is mandatory: no repeated actions without new
  information, no re-entering DISCOVERY, no restart after commitment

Architecture freeze note: the Runtime, Engine Registry, RuntimeContext,
Intent Resolver and Memory Engine are frozen. This planner replaces the old
`ConversationPlanner` wholesale; `select_target_pillar` is kept only as a
backward-compatible method (used by the legacy registry facade).
"""

import re
from enum import Enum

from .utils.storage import now_iso


# ─── Conversation Modes (spec Chapter 3) ─────────────────────────────

class ConversationMode(str, Enum):
    DISCOVERY = "discovery"
    INVESTIGATION = "investigation"
    COACHING = "coaching"
    REFLECTION = "reflection"
    COMMITMENT = "commitment"
    FOLLOW_UP = "follow_up"
    QUESTION_ANSWERING = "question_answering"
    CASUAL_CHAT = "casual_chat"
    SUMMARIZATION = "summarization"
    CLOSURE = "closure"
    ESCALATION = "escalation"


# ─── Planner Actions (spec Chapter 2) ────────────────────────────────

class PlannerAction(str, Enum):
    ASK_QUESTION = "ask_question"
    ANSWER_DIRECT_QUESTION = "answer_direct_question"
    ANSWER_CAPABILITY = "answer_capability"
    PROVIDE_INSIGHT = "provide_insight"
    PROVIDE_RECOMMENDATION = "provide_recommendation"
    EXPLORE_TOPIC = "explore_topic"
    CLARIFY = "clarify"
    CONFIRM_UNDERSTANDING = "confirm_understanding"
    CREATE_COMMITMENT = "create_commitment"
    SCHEDULE_ACTION = "schedule_action"
    CHECK_PROGRESS = "check_progress"
    RESUME_TOPIC = "resume_topic"
    SWITCH_TOPIC = "switch_topic"
    CASUAL_CHAT = "casual_chat"
    REFLECT = "reflect"
    SUMMARIZE = "summarize"
    CLOSE_CONVERSATION = "close_conversation"
    ESCALATE = "escalate"
    WAIT = "wait"


# ─── Valid mode transitions (spec: Valid Transitions / Invalid Transitions) ──

_VALID_TRANSITIONS = {
    ConversationMode.DISCOVERY: {ConversationMode.INVESTIGATION},
    ConversationMode.INVESTIGATION: {ConversationMode.COACHING},
    ConversationMode.COACHING: {ConversationMode.COMMITMENT, ConversationMode.SUMMARIZATION},
    ConversationMode.COMMITMENT: {ConversationMode.FOLLOW_UP, ConversationMode.CLOSURE},
    ConversationMode.FOLLOW_UP: {ConversationMode.CLOSURE},
    ConversationMode.REFLECTION: {ConversationMode.CLOSURE, ConversationMode.FOLLOW_UP},
    ConversationMode.SUMMARIZATION: {ConversationMode.CLOSURE},
    ConversationMode.CLOSURE: set(),
    ConversationMode.ESCALATION: set(),
}

# interruption modes may be entered from anywhere and return to previous
_TEMPORARY_MODES = {ConversationMode.QUESTION_ANSWERING, ConversationMode.CASUAL_CHAT}


# ─── PlannerDecision (spec Chapter 1) ────────────────────────────────

class PlannerDecision:
    """The planner's output: exactly one action + the reasoning behind it."""

    __slots__ = ("action", "reason", "confidence", "next_state", "metadata", "mode")

    def __init__(self, action, reason, confidence=0.80, next_state=None,
                 metadata=None, mode=None):
        self.action = action
        self.reason = reason
        self.confidence = confidence
        self.next_state = next_state
        self.metadata = metadata or {}
        self.mode = mode

    def to_dict(self):
        return {
            "action": self.action.value if isinstance(self.action, PlannerAction) else self.action,
            "reason": self.reason,
            "confidence": round(self.confidence, 3),
            "next_state": (self.next_state.value if isinstance(self.next_state, ConversationMode) else self.next_state),
            "metadata": dict(self.metadata or {}),
            "mode": (self.mode.value if isinstance(self.mode, ConversationMode) else self.mode),
        }


# ─── Deterministic signal detectors (never LLM) ──────────────────────

_WELLNESS_TOPIC_WORDS = [
    "work", "sleep", "stress", "relation", "friend", "family", "exercise",
    "health", "mood", "feel", "anxious", "worry", "happy", "sad", "lonely",
    "tired", "eat", "food", "routine", "focus", "energy", "overwhelm",
    "burnout", "motivation", "procrastination", "nutrition", "money",
    "finances", "anxiety", "depressed",
]

_TOPIC_PATTERNS = {
    "sleep": [r"\bsleep", r"\binsomnia", r"\bbedtime\b", r"\btired", r"\bnap\b", r"\bnight\b"],
    "stress": [r"\bstress", r"\boverwhelm", r"\bpressure\b", r"\bburnout", r"\bdread\b"],
    "work": [r"\bwork\b", r"\bjob\b", r"\bcareer\b", r"\bboss\b", r"\bcolleague", r"\bdeadline", r"\boffice\b"],
    "relationships": [r"\brelationship", r"\bfriend", r"\bpartner\b", r"\bfamily\b", r"\blonely", r"\balone\b"],
    "mood": [r"\bmood\b", r"\bsad\b", r"\bdepressed\b", r"\banxious\b", r"\bworry\b", r"\bdown\b"],
    "motivation": [r"\bmotivation", r"\bdrive\b", r"\bprocrastinat", r"\bfocus\b", r"\bgoal\b"],
    "exercise": [r"\bexercise\b", r"\bworkout\b", r"\bgym\b", r"\bwalk", r"\byoga\b", r"\bfitness\b"],
    "nutrition": [r"\bnutrition\b", r"\bdiet\b", r"\bmeal\b", r"\bfood\b", r"\beat\b", r"\bhungry\b"],
    "routine": [r"\broutine\b", r"\bhabit\b", r"\bschedule\b", r"\bmorning\b", r"\bevening\b"],
    "finances": [r"\bfinance", r"\bmoney\b", r"\bbudget\b", r"\bdebt\b", r"\bbill\b"],
}

_CAPABILITY_RE = re.compile(
    r"\bwhat can you (?:do|help(?: me)?(?: with)?|assist|recommend|offer)\b|"
    r"\bwhat are you (?:able|capable) to do\b|"
    r"\bhow can you help\b|\bhow do you work\b|\bwhat do you do\b|"
    r"\bwhat (?:are|who is) you\b|\bare you a (?:robot|bot|ai|chatbot|human)\b|"
    r"\btell me about yourself\b|\bwhat'?s your (?:purpose|role|name)\b|"
    r"\bwhat can (?:this|the) (?:app|bot|companion) do\b|\byour (?:features|capabilities)\b|"
    r"\bwhat should i use (?:this|you) for\b",
    re.IGNORECASE,
)

_CASUAL_RE = re.compile(
    r"\btell me a joke\b|\bmake me laugh\b|\banother joke\b|\bhow'?s your day\b|"
    r"\bhow is your day going\b|"
    r"\bwhat (?:movies|music|books|songs|films|tv shows?) do you (?:like|enjoy|watch|listen to)\b|"
    r"\bwho'?s your favorite\b|\bdo you like (?:movies|music|games)\b|"
    r"\blet'?s (?:just )?chat\b|\bjust chatting\b|\bchat (?:casually|about anything)\b|"
    r"\bsmall talk\b|\btell me a (?:story|riddle|fun fact)\b|\bwhat did you do today\b|"
    r"\b(?:the )?weather\b|\bthe game last night\b",
    re.IGNORECASE,
)

_QUESTION_START_RE = re.compile(
    r"^(?:why|what|how|when|where|which|who|can|could|would|should|"
    r"do|does|did|is|are|will|am)\b",
    re.IGNORECASE,
)

_RHETORICAL_QUESTION_RE = re.compile(
    r"\b(?:right|right there|eh|huh|isn'?t it|don'?t you think|"
    r"do you even care|who cares|does it matter|what difference does it make|"
    r"why bother|what'?s the (?:point|use))\??\s*$|"
    r"^who needs\b.*\?$",
    re.IGNORECASE,
)

_PROCESS_COMPLAINT_RE = re.compile(
    r"\bwhy do you keep\b|\b(?:same|the same|new|different) questions?\b|"
    r"\bkeep asking me\b|\bkeep asking the same\b|\bstop asking\b|\b(?:always|keep) asking\b|"
    r"\bare you (?:even )?(?:listening|real|human)\b|\bwhat'?s the point\b|"
    r"\b(?:this|it) (?:isn'?t|is not|ain'?t) helping\b|\byou'?re not helping\b|"
    r"\bwasting my time\b|\bi hate this\b|\bi'?m fed up\b|\bthis app\b",
    re.IGNORECASE,
)

_SWITCH_RE = re.compile(
    r"\b(?:let'?s|could we|can we|how about|what about|switch|change|"
    r"move on|talk about|discuss|i want to talk about|i'?d like to talk about|"
    r"i want to focus on|let'?s move to)\b.*\b"
    r"(?:work|sleep|stress|anxiety|mood|relationships?|family|friends?|"
    r"exercise|health|energy|motivation|focus|routine|nutrition|food|"
    r"finances|money|overwhelm|burnout|productivity|procrastination)\b",
    re.IGNORECASE,
)

_ACCEPT_RE = re.compile(
    r"^\s*(?:yes|yeah|yep|yup|sure|ok|okay|fine|alright|definitely|"
    r"absolutely|sounds good|sounds great|that works|that'?s great|"
    r"good idea|deal|let'?s do it|let'?s try|i'?m in|i'?ll try|i'?ll do it|"
    r"i will|works for me|good)\b",
    re.IGNORECASE,
)

_REJECT_RE = re.compile(
    r"^\s*(?:no|nah|nope|not really|not now|not right now|maybe later|"
    r"i don'?t think so|not for me|no thanks|skip|can'?t|i can'?t|"
    r"won'?t|don'?t want)\b",
    re.IGNORECASE,
)

_TIME_RE = re.compile(
    r"\b(?:tomorrow|tonight|today|this (?:week|weekend|morning|evening|"
    r"afternoon)|next week|monday|tuesday|wednesday|thursday|friday|"
    r"saturday|sunday|morning|afternoon|evening|after work|before bed|"
    r"weekend|at \d{1,2}(?::\d{2})?\s*(?:am|pm)?)\b",
    re.IGNORECASE,
)

_ASKING_ACTIONS = (PlannerAction.ASK_QUESTION, PlannerAction.EXPLORE_TOPIC,
                   PlannerAction.CLARIFY)


class ConversationPlanner:
    """V2 decision engine: modes, actions, interruptions, commitments, loops."""

    def __init__(self, memory_system=None):
        self.memory = memory_system
        # ConversationModeState (spec: Mode Persistence)
        self.mode = None
        self.previous_mode = None
        self.entered_at = None
        self.entered_by = None
        self.exit_condition = None
        # decision state
        self.last_decision = None
        self._discovery_exited = False
        self._asking_streak = 0
        self._pending_recommendation = False
        self._commit_stage = None
        self._asked = set()

    # ─── public API ─────────────────────────────────────────────────

    def reset(self):
        """Start a brand-new conversation (fresh mode state)."""
        self.mode = None
        self.previous_mode = None
        self.entered_at = None
        self.entered_by = None
        self.exit_condition = None
        self.last_decision = None
        self._discovery_exited = False
        self._asking_streak = 0
        self._pending_recommendation = False
        self._commit_stage = None
        self._asked = set()

    def current_mode(self):
        return self.mode

    def mode_state(self):
        """ConversationModeState record (spec Chapter 3)."""
        return {
            "current_mode": self.mode.value if self.mode else None,
            "previous_mode": self.previous_mode.value if self.previous_mode else None,
            "entered_at": self.entered_at,
            "entered_by": self.entered_by,
            "exit_condition": self.exit_condition,
        }

    # ─── the decision process (spec: Planner Decision Process) ──────

    def decide(self, ctx):
        """Complete decision process for one turn.

        ctx keys (assembled deterministically by the caller):
          message, intent_graph, emotion, state, state_info, route,
          current_pillar, objective, avoidance_count, exit_offered,
          exit_consumed, minimal_input, has_emotion_keyword
        """
        message = (ctx.get("message") or "").strip()
        ig = ctx.get("intent_graph") or {}
        emotion = ctx.get("emotion") or {}

        # 1. ESCALATE — prevent harm, always first
        primary_intent = (ig.get("primary_intent") or {}).get("intent", "")
        if emotion.get("risk_flag") or primary_intent == "crisis":
            return self._decide_escalation()

        # 2. interruption-mode recovery (resume previous mode)
        if self.mode in _TEMPORARY_MODES and self.previous_mode is not None:
            decision = self._recover_from_interruption(message, ig, ctx.get("state"))
            if decision:
                return self._record(decision)

        # 3. capability questions pause the conversation
        if self._is_capability(message):
            return self._record(self._enter_temporary(
                ConversationMode.QUESTION_ANSWERING,
                PlannerAction.ANSWER_CAPABILITY,
                "capability question pauses the current conversation"))

        # 4. explicit topic switches change the branch
        if self._is_topic_switch(message, ig):
            target = self._extract_target_topic(message)
            return self._record(PlannerDecision(
                PlannerAction.SWITCH_TOPIC,
                f"user switched to topic: {target or 'unknown'}",
                confidence=0.90,
                metadata={"target_topic": target}))

        # 5. casual chat suspends coaching
        if self._is_casual(message):
            return self._record(self._enter_temporary(
                ConversationMode.CASUAL_CHAT,
                PlannerAction.CASUAL_CHAT,
                "casual chat suspends coaching"))

        # 6. direct questions interrupt investigations
        if self._is_direct_question(message):
            return self._record(self._enter_temporary(
                ConversationMode.QUESTION_ANSWERING,
                PlannerAction.ANSWER_DIRECT_QUESTION,
                "direct question interrupts the active mode"))

        # 7. commitment flow (spec: CREATE_COMMITMENT -> SCHEDULE_ACTION -> CLOSURE)
        if self.mode == ConversationMode.COMMITMENT:
            return self._record(self._commitment_flow(message))

        # 8. recommendation acceptance creates a commitment
        if self.mode == ConversationMode.COACHING and self._pending_recommendation:
            decision = self._recommendation_reply(message)
            if decision:
                return self._record(decision)

        if self.mode == ConversationMode.SUMMARIZATION:
            return self._record(self._move(
                ConversationMode.CLOSURE,
                PlannerAction.CLOSE_CONVERSATION,
                "summarization exits to closure", by="summarization_complete"))

        # 9. state-machine-driven flow (deterministic branch order)
        decision = self._state_flow(ctx)
        return self._record(self._apply_loop_guard(decision, ctx))

    # ─── escalation ────────────────────────────────────────────────

    def _decide_escalation(self):
        self._enter_mode(ConversationMode.ESCALATION, by="risk_detected")
        return PlannerDecision(
            PlannerAction.ESCALATE,
            "safety-sensitive situation: coaching stops, safety workflow only",
            confidence=0.99,
            metadata={"risk": True})

    # ─── interruptions ─────────────────────────────────────────────

    def _enter_temporary(self, temp_mode, action, reason):
        """Suspend the active mode; the previous mode is remembered."""
        self.previous_mode = self.mode or ConversationMode.DISCOVERY
        self._enter_mode(temp_mode, by="interruption")
        return PlannerDecision(
            action, reason, confidence=0.90,
            metadata={"resumed_mode": self.previous_mode.value})

    def _recover_from_interruption(self, message, ig, state=""):
        if self._is_topic_switch(message, ig):
            target = self._extract_target_topic(message)
            prev = self.previous_mode
            self._restore_previous_mode(state)
            return PlannerDecision(
                PlannerAction.SWITCH_TOPIC,
                f"user switched topic to {target or 'new topic'} after interruption",
                confidence=0.90,
                metadata={"target_topic": target, "resumed_mode": prev.value})
        if self._is_wellness_concern(message, ig):
            prev = self.previous_mode
            self._restore_previous_mode(state)
            return PlannerDecision(
                PlannerAction.RESUME_TOPIC,
                f"user returned to a coaching concern; resuming {prev.value}",
                confidence=0.88,
                metadata={"resumed_mode": prev.value,
                          "target_topic": self._extract_target_topic(message)})
        if self._is_casual(message):
            if self.mode != ConversationMode.CASUAL_CHAT:
                self._enter_mode(ConversationMode.CASUAL_CHAT, by="interruption", force=True)
            return PlannerDecision(
                PlannerAction.CASUAL_CHAT,
                "continuing casual conversation until a coaching concern appears",
                confidence=0.85)
        if self.mode == ConversationMode.CASUAL_CHAT:
            return PlannerDecision(
                PlannerAction.CASUAL_CHAT,
                "no coaching concern yet; continuing casual conversation",
                confidence=0.80)
        # QUESTION_ANSWERING without a new question or concern
        if self._is_capability(message):
            return PlannerDecision(PlannerAction.ANSWER_CAPABILITY,
                                   "another capability question", confidence=0.90)
        if self._is_direct_question(message):
            return PlannerDecision(PlannerAction.ANSWER_DIRECT_QUESTION,
                                   "another direct question", confidence=0.90)
        # The message has nothing to do with the interruption: the user has
        # moved on. Restore the previous mode and let the standard flow decide
        # (keeps momentum; never parks the conversation in WAIT).
        self._restore_previous_mode(state)
        return None

    def _restore_previous_mode(self, state=""):
        previous = self.previous_mode or ConversationMode.DISCOVERY
        if previous == ConversationMode.DISCOVERY and state == "deep_investigation":
            previous = ConversationMode.INVESTIGATION
        self.previous_mode = None
        self._enter_mode(previous, by="interruption_resolved", force=True)

    # ─── commitment flow ───────────────────────────────────────────

    def _recommendation_reply(self, message):
        if _ACCEPT_RE.match(message) or _TIME_RE.search(message):
            self._pending_recommendation = False
            self._commit_stage = "proposed"
            self._enter_mode(ConversationMode.COMMITMENT, by="recommendation_accepted")
            return PlannerDecision(
                PlannerAction.CREATE_COMMITMENT,
                "recommendation accepted; converting advice into an achievable action",
                confidence=0.92)
        if _REJECT_RE.match(message):
            self._pending_recommendation = False
            self._enter_mode(ConversationMode.SUMMARIZATION, by="recommendation_declined")
            return PlannerDecision(
                PlannerAction.SUMMARIZE,
                "recommendation declined; summarizing before closure",
                confidence=0.85)
        if self.last_decision and self.last_decision.action == PlannerAction.PROVIDE_RECOMMENDATION:
            return PlannerDecision(
                PlannerAction.PROVIDE_RECOMMENDATION,
                "recommendation pending; no acceptance or decline yet",
                confidence=0.70)
        return None

    def _commitment_flow(self, message):
        if _REJECT_RE.match(message):
            self._commit_stage = None
            self._enter_mode(ConversationMode.CLOSURE, by="commitment_declined")
            return PlannerDecision(
                PlannerAction.CLOSE_CONVERSATION,
                "commitment declined; closing gracefully", confidence=0.85,
                metadata={"graceful": True})
        if self._commit_stage == "proposed":
            if _ACCEPT_RE.match(message) or _TIME_RE.search(message):
                self._commit_stage = "scheduled"
                return PlannerDecision(
                    PlannerAction.SCHEDULE_ACTION,
                    "commitment accepted; scheduling the action", confidence=0.92)
            return PlannerDecision(
                PlannerAction.WAIT,
                "commitment proposed; waiting for the user's answer",
                confidence=0.75,
                metadata={"commitment_pause": True})
        self._commit_stage = None
        self._enter_mode(ConversationMode.CLOSURE, by="commitment_scheduled")
        return PlannerDecision(
            PlannerAction.CLOSE_CONVERSATION,
            "commitment scheduled; closing the conversation", confidence=0.92,
            metadata={"commitment_done": True})

    # ─── standard flow (deterministic branch order) ────────────────

    def _state_flow(self, ctx):
        state = ctx.get("state") or ""
        route = ctx.get("route") or []
        avoidance = ctx.get("avoidance_count") or 0
        exit_offered = ctx.get("exit_offered") or False
        exit_consumed = ctx.get("exit_consumed") or False
        objective = ctx.get("objective") or ""
        state_info = ctx.get("state_info") or {}

        if state == "greeting":
            self._enter_mode(ConversationMode.DISCOVERY, by="new_conversation")
            return PlannerDecision(
                PlannerAction.ASK_QUESTION, "opening greeting in discovery",
                metadata={"greeting": True})

        if "question_planner" in route and avoidance == 1 and not exit_consumed:
            self._enter_mode_for_state(state)
            return PlannerDecision(
                PlannerAction.CLARIFY,
                "avoidance: force choice with concrete options",
                metadata={"force_choice": True})

        if avoidance >= 3 and not exit_offered and not exit_consumed:
            self._enter_mode_for_state(state)
            return PlannerDecision(
                PlannerAction.WAIT,
                "repeated avoidance: offer to end the conversation",
                metadata={"exit_offer": True})

        if state == "rapport_building" and avoidance == 2 and not exit_consumed:
            self._enter_mode_for_state(state)
            return PlannerDecision(
                PlannerAction.CASUAL_CHAT,
                "avoidance at rapport: offer casual conversation",
                metadata={"casual_offer": True})

        if state != "greeting" and (ctx.get("minimal_input") or ctx.get("has_emotion_keyword")):
            self._enter_mode_for_state(state)
            return PlannerDecision(
                PlannerAction.CLARIFY,
                "short or emotional input: narrow with a category tree",
                metadata={"quick_tree": True})

        if "question_planner" in route:
            self._enter_mode_for_state(state)
            if state == "deep_investigation":
                return PlannerDecision(
                    PlannerAction.EXPLORE_TOPIC,
                    "deepening understanding of the active branch",
                    metadata={"pillar": ctx.get("current_pillar")})
            return PlannerDecision(
                PlannerAction.ASK_QUESTION, "discovery question",
                metadata={"pillar": ctx.get("current_pillar")})

        if "root_cause_engine" in route and ctx.get("current_pillar") and "question_planner" not in route:
            self._enter_mode_for_state(state)
            return PlannerDecision(
                PlannerAction.PROVIDE_INSIGHT,
                "enough investigation confidence: share the pattern",
                metadata={"insight": True})

        if "routine_generator" in route:
            self._enter_mode_for_state(state)
            self._pending_recommendation = True
            return PlannerDecision(
                PlannerAction.PROVIDE_RECOMMENDATION,
                "investigation complete: offer one actionable recommendation",
                metadata={"pending": True})

        if objective == "close_conversation" and state != "greeting":
            self._enter_mode_for_state(state)
            return PlannerDecision(
                PlannerAction.CLOSE_CONVERSATION, "objective is conversation closure")

        if state == "reflection":
            self._enter_mode(ConversationMode.REFLECTION, by="state_reflection")
            return PlannerDecision(PlannerAction.REFLECT, "reflection mode: prioritize listening")

        if state == "follow_up":
            self._enter_mode(ConversationMode.FOLLOW_UP, by="state_follow_up")
            return PlannerDecision(PlannerAction.CHECK_PROGRESS,
                                   "follow-up: review progress on commitments")

        if state == "free_conversation":
            self._enter_mode_for_state(state)
            return PlannerDecision(PlannerAction.CASUAL_CHAT,
                                   "free conversation continues naturally")

        if state == "rapport_building":
            self._enter_mode_for_state(state)
            return PlannerDecision(PlannerAction.CASUAL_CHAT,
                                   "rapport building: easy, low-pressure exchange",
                                   metadata={"rapport": True})

        if state == "avoidance_detection":
            self._enter_mode_for_state(state)
            return PlannerDecision(PlannerAction.WAIT,
                                   "avoidance: offer choices without pressure",
                                   metadata={"avoidance": True})

        if state == "soft_exploration":
            self._enter_mode_for_state(state)
            return PlannerDecision(PlannerAction.ASK_QUESTION,
                                   "soft exploration: gentle opening",
                                   metadata={"soft": True})

        if state == "insight_generation":
            self._enter_mode_for_state(state)
            return PlannerDecision(PlannerAction.PROVIDE_INSIGHT,
                                   "insight already delivered: check in",
                                   metadata={"variant": True})

        self._enter_mode_for_state(state)
        return PlannerDecision(PlannerAction.ASK_QUESTION, "default: keep momentum",
                               metadata={"default": True})

    def _enter_mode_for_state(self, state):
        mapping = {
            "guided_discovery": ConversationMode.DISCOVERY,
            "pillar_selection": ConversationMode.DISCOVERY,
            "deep_investigation": ConversationMode.INVESTIGATION,
            "insight_generation": ConversationMode.COACHING,
            "routine_planning": ConversationMode.COACHING,
        }
        target = mapping.get(state)
        if target is None:
            return
        reason = "state_machine_%s" % state
        if target == ConversationMode.INVESTIGATION:
            if self.mode is None:
                self._enter_mode(ConversationMode.DISCOVERY, by="new_conversation")
            if self.mode == ConversationMode.DISCOVERY:
                self._enter_mode(target, by=reason)
        else:
            self._enter_mode(target, by=reason)

    # ─── loop prevention (spec Chapter 3) ──────────────────────────

    def _apply_loop_guard(self, decision, ctx):
        ig = ctx.get("intent_graph") or {}
        progress = bool(ig.get("answered_current_question")) or bool(ig.get("new_slots_detected"))
        primary = (ig.get("primary_intent") or {}).get("intent", "")
        if progress or primary in ("answer", "additional_information", "commitment", "goal_update"):
            self._asking_streak = 0
        elif decision.action in _ASKING_ACTIONS and self.last_decision and \
                self.last_decision.action == decision.action:
            self._asking_streak += 1
        else:
            self._asking_streak = 0

        if self._asking_streak >= 2 and decision.action in _ASKING_ACTIONS:
            if self.mode in (ConversationMode.INVESTIGATION, ConversationMode.COACHING):
                self._asking_streak = 0
                return PlannerDecision(
                    PlannerAction.PROVIDE_INSIGHT,
                    "loop prevention: repeated questions without new information",
                    confidence=0.75,
                    metadata={"loop_break": True})
            return PlannerDecision(
                PlannerAction.WAIT,
                "loop prevention: repeated questions without progress",
                confidence=0.75,
                metadata={"loop_break": True})
        return decision

    # ─── signal detectors ──────────────────────────────────────────

    def _is_capability(self, message):
        return bool(message) and bool(_CAPABILITY_RE.search(message))

    def _is_casual(self, message):
        return bool(message) and bool(_CASUAL_RE.search(message))

    def _is_topic_switch(self, message, ig):
        if (ig.get("topic_shift") or ig.get("branch_change_requested")):
            return True
        if not message:
            return False
        lower = message.lower()
        if re.search(r"\b(?:back to|get back|go back|return to|back on)\b", lower):
            return False
        return bool(_SWITCH_RE.search(message))

    def _is_direct_question(self, message):
        if not message:
            return False
        if len(message) <= 1:
            return False
        stripped = message.strip()
        if _CAPABILITY_RE.search(stripped) or _CASUAL_RE.search(stripped) \
                or _SWITCH_RE.search(stripped):
            return False
        # Process complaints ("why do you keep asking the same questions?") are
        # about the conversation itself, not wellness content — the standard
        # coaching flow should keep control, not a Q&A answer. Same for
        # rhetorical questions ("who needs sleep anyway, right?").
        if _PROCESS_COMPLAINT_RE.search(stripped) or _RHETORICAL_QUESTION_RE.search(stripped):
            return False
        if stripped.endswith("?"):
            return True
        return bool(_QUESTION_START_RE.match(stripped))

    def _is_wellness_concern(self, message, ig):
        primary = (ig.get("primary_intent") or {}).get("intent", "")
        if primary in ("commitment", "goal_update", "correction", "crisis"):
            return True
        if not message:
            return False
        lower = message.lower()
        return any(word in lower for word in _WELLNESS_TOPIC_WORDS)

    def _extract_target_topic(self, message):
        if not message:
            return None
        lower = message.lower()
        for pillar, patterns in _TOPIC_PATTERNS.items():
            for pat in patterns:
                if re.search(pat, lower):
                    return pillar
        return None

    # ─── mode persistence ──────────────────────────────────────────

    def _enter_mode(self, next_mode, by="", force=False):
        if next_mode == self.mode:
            return True
        if next_mode == ConversationMode.DISCOVERY:
            if self._discovery_exited and not force:
                return False
        elif self.mode is not None and not force:
            if next_mode not in _TEMPORARY_MODES and next_mode != ConversationMode.ESCALATION:
                allowed = _VALID_TRANSITIONS.get(self.mode, set())
                if next_mode not in allowed:
                    return False
        if next_mode == ConversationMode.DISCOVERY:
            self._discovery_exited = False
        elif self.mode is not None and self.mode != ConversationMode.DISCOVERY:
            self._discovery_exited = True
        self.mode = next_mode
        self.entered_at = now_iso()
        self.entered_by = by
        self.exit_condition = None
        return True

    def _move(self, target_mode, action, reason, by=""):
        self._enter_mode(target_mode, by=by)
        return PlannerDecision(action, reason)

    # ─── record ────────────────────────────────────────────────────

    def _record(self, decision):
        decision.mode = self.mode
        decision.next_state = self.mode
        self.last_decision = decision
        return decision

    # ─── backward compatibility (legacy registry facade) ───────────

    def select_target_pillar(self, known_pillars=None, unknown_pillars=None,
                             current_state=None, latest_emotion_scores=None,
                             user_message=None):
        if known_pillars is None and self.memory:
            known_pillars = self.memory.get_known_pillars()
        if unknown_pillars is None and self.memory:
            unknown_pillars = self.memory.get_unknown_pillars()

        known_pillars = known_pillars or {}
        unknown_pillars = unknown_pillars or []
        emotion_scores = latest_emotion_scores or {}

        deprioritized = self.memory.get_deprioritized_pillars() if self.memory else []

        if current_state in ("deep_investigation", "insight_generation", "routine_planning"):
            current_pillar = getattr(self.memory, "selected_pillar", None)
            if current_pillar:
                return {"target_pillar": current_pillar, "reason": "Continuing current investigation", "urgency": "normal"}

        context_pillar = self._detect_context_pillar(user_message, deprioritized)
        if context_pillar:
            return context_pillar

        spike_pillar = self._detect_emotion_spike(emotion_scores, deprioritized)
        if spike_pillar:
            return spike_pillar

        stale_pillar = self._find_stale_pillar(known_pillars, deprioritized)
        if stale_pillar:
            return stale_pillar

        unknown_filtered = [p for p in unknown_pillars if p not in deprioritized]
        if unknown_filtered:
            pillar = unknown_filtered[0]
            return {"target_pillar": pillar, "reason": f"Uncovered pillar: {pillar}", "urgency": "normal"}

        known_filtered = {p: v for p, v in known_pillars.items() if p not in deprioritized}
        if known_filtered:
            lowest_conf = min(known_filtered.items(), key=lambda x: x[1].get("confidence", 0))
            return {"target_pillar": lowest_conf[0], "reason": f"Lowest confidence known pillar: {lowest_conf[0]}", "urgency": "low"}

        return {"target_pillar": "mood", "reason": "Default pillar - mood", "urgency": "low"}

    def _detect_context_pillar(self, user_message, deprioritized):
        if not user_message:
            return None
        pillar_map = {
            "sleep": [r"\bsleep\b", r"\binsomnia\b", r"\bbed\b", r"\btired\b", r"\brest\b", r"\bnightmare\b", r"\bcant sleep\b"],
            "stress": [r"\bstress\b", r"\bstressed\b", r"\boverwhelm\b", r"\bpressure\b", r"\bdrowning\b", r"\bdeadline\b"],
            "relationships": [r"\brelationship\b", r"\bfriend\b", r"\bpartner\b", r"\bspouse\b", r"\bfamily\b", r"\balone\b", r"\blonely\b"],
            "exercise": [r"\bexercise\b", r"\bworkout\b", r"\bgym\b", r"\bwalk(?:ing|ed)?\b", r"\brun(?:ning|s)?\b", r"\byoga\b", r"\bfitness\b"],
            "work": [r"\bwork\b", r"\bjob\b", r"\bcareer\b", r"\bboss\b", r"\bcoworker\b", r"\bdeadline\b", r"\boffice\b", r"\bcolleague\b"],
            "mood": [r"\bmood\b", r"\bfeel(?:ing|s)?\b", r"\bsad\b", r"\bhappy\b", r"\bemotion\b", r"\bdown\b", r"\bdepressed\b", r"\bflat\b"],
            "motivation": [r"\bmotivation\b", r"\bmotivated\b", r"\bdrive\b", r"\bgoal\b", r"\bprocrastinate\b", r"\bfocus\b", r"\bproductive\b"],
            "routine": [r"\broutine\b", r"\bhabit\b", r"\bschedule\b", r"\bmorning\b", r"\bevening\b", r"\bdaily\b"],
            "nutrition": [r"\bnutrition\b", r"\beat(?:ing|s)?\b", r"\bfood\b", r"\bdiet\b", r"\bmeal\b", r"\bhungry\b", r"\bweight\b"],
            "finances": [r"\bfinance\b", r"\bmoney\b", r"\bbudget\b", r"\bdebt\b", r"\bspend(?:ing|s)?\b", r"\bincome\b", r"\bbill\b", r"\bpayment\b"],
        }
        for pillar, patterns in pillar_map.items():
            if pillar in deprioritized:
                continue
            for pat in patterns:
                if re.search(pat, user_message, re.IGNORECASE):
                    return {"target_pillar": pillar, "reason": f"Context match: '{pat}'", "urgency": "high"}
        return None

    def _detect_emotion_spike(self, emotion_scores, deprioritized):
        spikes = {
            "stress": ("stress", 70, "work"),
            "anxiety": ("anxiety", 65, "stress"),
            "loneliness": ("loneliness", 60, "relationships"),
            "burnout": ("burnout", 60, "work"),
            "frustration": ("frustration", 65, "work"),
            "low_energy": ("energy", 25, "mood"),
            "low_motivation": ("motivation", 25, "mood"),
            "poor_sleep_signal": ("emotional_intensity", 70, "sleep"),
        }

        for spike_name, (dim, threshold, pillar) in spikes.items():
            if pillar in deprioritized:
                continue
            if dim in emotion_scores:
                score = emotion_scores[dim]
                if isinstance(score, (int, float)) and (
                    (score > threshold) or
                    (dim in ("energy", "motivation", "self_esteem") and score < threshold)
                ):
                    return {"target_pillar": pillar, "reason": f"Emotion spike detected: {dim}={score}", "urgency": "high"}

        return None

    def _find_stale_pillar(self, known_pillars, deprioritized):
        from .utils.storage import days_since

        stalest = None
        stalest_days = 0

        for pillar, info in known_pillars.items():
            if pillar in deprioritized:
                continue
            last_update = info.get("last_updated")
            if last_update:
                days = days_since(last_update)
                if days > stalest_days and days > 3:
                    stalest = pillar
                    stalest_days = days

        if stalest:
            return {"target_pillar": stalest, "reason": f"Stale data ({stalest_days}d old)", "urgency": "normal"}
        return None
