import re
from .modes import ConversationMode
from .actions import PlannerAction, _ASKING_ACTIONS
from .transition import _VALID_TRANSITIONS, _TEMPORARY_MODES
from .decision import PlannerDecision
from .signals import (_is_capability, _is_casual, _is_goodbye,
                       _is_topic_switch, _is_direct_question,
                       _is_wellness_concern, _extract_target_topic,
                       _ACCEPT_RE, _REJECT_RE, _TIME_RE)
from .policy import (_button_mode, _next_ladder_stage, _reset_ladder,
                       _attach_quick_replies, _is_rich_input,
                       _QUICK_REPLY_ENTRY_PILLARS)
from ..utils.storage import now_iso
from .. import branch_policy
from ..lifecycle_engine import (
    LifecycleStage, BranchState,
    evaluate_branch_lifecycle, get_next_stage,
    is_forbidden_transition, is_valid_transition,
    completion_score, is_complete,
)


class ConversationPlanner:
    """V2 decision engine: modes, actions, interruptions, commitments, loops."""

    def __init__(self, memory_system=None):
        self.memory = memory_system
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
        self._ladder_idx = 0
        self._ctx = None
        self._branch_state = None
        self._lifecycle_state = None

    def reset(self):
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
        self._ladder_idx = 0
        self._ctx = None
        self._branch_state = None
        self._lifecycle_state = None

    def current_mode(self):
        return self.mode

    def mode_state(self):
        return {
            "current_mode": self.mode.value if self.mode else None,
            "previous_mode": self.previous_mode.value if self.previous_mode else None,
            "entered_at": self.entered_at,
            "entered_by": self.entered_by,
            "exit_condition": self.exit_condition,
        }

    def decide(self, ctx):
        message = (ctx.get("message") or "").strip()
        ig = ctx.get("intent_graph") or {}
        emotion = ctx.get("emotion") or {}
        self._ctx = ctx

        primary_intent = (ig.get("primary_intent") or {}).get("intent", "")
        if emotion.get("risk_flag") or primary_intent == "crisis":
            return self._decide_escalation()

        pillar = ctx.get("current_pillar")
        if pillar:
            self._lifecycle_state = evaluate_branch_lifecycle(pillar, ctx)

        if self.mode in _TEMPORARY_MODES and self.previous_mode is not None:
            decision = self._recover_from_interruption(message, ig, ctx.get("state"))
            if decision:
                return self._record(decision)

        if self._is_capability(message):
            return self._record(self._enter_temporary(
                ConversationMode.QUESTION_ANSWERING,
                PlannerAction.ANSWER_CAPABILITY,
                "capability question pauses the current conversation"))

        if self._is_topic_switch(message, ig):
            target = self._extract_target_topic(message)
            return self._record(PlannerDecision(
                PlannerAction.SWITCH_TOPIC,
                f"user switched to topic: {target or 'unknown'}",
                confidence=0.90,
                metadata={"target_topic": target}))

        if self._is_goodbye(message):
            return self._record(PlannerDecision(
                PlannerAction.CLOSE_CONVERSATION,
                "user said goodbye — close gracefully",
                confidence=0.90,
                metadata={"graceful": True}))

        if self._is_casual(message):
            return self._record(self._enter_temporary(
                ConversationMode.CASUAL_CHAT,
                PlannerAction.CASUAL_CHAT,
                "casual chat suspends coaching"))

        if self._is_direct_question(message):
            return self._record(self._enter_temporary(
                ConversationMode.QUESTION_ANSWERING,
                PlannerAction.ANSWER_DIRECT_QUESTION,
                "direct question interrupts the active mode"))

        if self.mode == ConversationMode.COMMITMENT:
            return self._record(self._commitment_flow(message))

        if self.mode == ConversationMode.COACHING and self._pending_recommendation:
            decision = self._recommendation_reply(message)
            if decision:
                return self._record(decision)

        if self.mode == ConversationMode.SUMMARIZATION:
            return self._record(self._move(
                ConversationMode.CLOSURE,
                PlannerAction.CLOSE_CONVERSATION,
                "summarization exits to closure", by="summarization_complete"))

        decision = self._branch_completion_gate(ctx)
        if decision:
            return self._record(decision)

        decision = self._state_flow(ctx)
        return self._record(self._apply_loop_guard(decision, ctx))

    def _decide_escalation(self):
        self._enter_mode(ConversationMode.ESCALATION, by="risk_detected")
        return PlannerDecision(
            PlannerAction.ESCALATE,
            "safety-sensitive situation: coaching stops, safety workflow only",
            confidence=0.99,
            metadata={"risk": True})

    def _enter_temporary(self, temp_mode, action, reason):
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
        if self._is_capability(message):
            return PlannerDecision(PlannerAction.ANSWER_CAPABILITY,
                                   "another capability question", confidence=0.90)
        if self._is_direct_question(message):
            return PlannerDecision(PlannerAction.ANSWER_DIRECT_QUESTION,
                                   "another direct question", confidence=0.90)
        self._restore_previous_mode(state)
        return None

    def _restore_previous_mode(self, state=""):
        previous = self.previous_mode or ConversationMode.DISCOVERY
        if previous == ConversationMode.DISCOVERY and state == "deep_investigation":
            previous = ConversationMode.INVESTIGATION
        self.previous_mode = None
        self._enter_mode(previous, by="interruption_resolved", force=True)

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
            self._reset_ladder()
            return PlannerDecision(
                PlannerAction.ASK_QUESTION,
                "greeting policy: welcome naturally, one open question, no categories",
                metadata={"greeting": True, "open_question": True,
                          "question_priority": "reflective",
                          "button_mode": "free"})

        if "question_planner" in route and avoidance == 1 and not exit_consumed \
                and not ctx.get("minimal_input"):
            self._enter_mode_for_state(state)
            return PlannerDecision(
                PlannerAction.CLARIFY,
                "avoidance: force choice with concrete options",
                metadata={"force_choice": True, "button_mode": "choice"})

        if avoidance >= 3 and not exit_offered and not exit_consumed:
            self._enter_mode_for_state(state)
            return PlannerDecision(
                PlannerAction.WAIT,
                "repeated avoidance: offer to end the conversation",
                metadata={"exit_offer": True})

        if state != "greeting" and self._is_rich_input(ctx):
            self._enter_mode_for_state(state)
            return PlannerDecision(
                PlannerAction.EXPLORE_TOPIC,
                "rich free text: continue naturally, free text beats buttons",
                confidence=0.85,
                metadata={"question_priority": _next_ladder_stage(self),
                          "button_mode": "free", "natural": True})

        if "question_planner" in route:
            self._enter_mode_for_state(state)
            button_mode = _button_mode(ctx)
            if state == "deep_investigation":
                return PlannerDecision(
                    PlannerAction.EXPLORE_TOPIC,
                    "deepening understanding of the active branch",
                    metadata={"pillar": ctx.get("current_pillar"),
                              "question_priority": _next_ladder_stage(self),
                              "button_mode": button_mode})
            if button_mode == "choice":
                return PlannerDecision(
                    PlannerAction.CLARIFY,
                    "fallback: user cannot articulate — choice buttons are the recovery tool",
                    metadata={"quick_tree": True, "button_mode": "choice"})
            return PlannerDecision(
                PlannerAction.ASK_QUESTION, "discovery question",
                metadata={"pillar": ctx.get("current_pillar"),
                          "question_priority": _next_ladder_stage(self),
                          "button_mode": "free"})

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

        ig = ctx.get("intent_graph") or {}
        slot_progress = bool(ig.get("answered_current_question")) or \
            bool(ig.get("new_slots_detected"))
        if slot_progress and state not in ("greeting", "reflection", "follow_up"):
            self._enter_mode_for_state(state)
            return PlannerDecision(
                PlannerAction.EXPLORE_TOPIC,
                "slot completed: keep the active branch, never abandon the topic",
                confidence=0.88,
                metadata={"pillar": ctx.get("current_pillar"),
                          "question_priority": _next_ladder_stage(self),
                          "button_mode": "free", "slot_progress": True})

        if state == "free_conversation":
            self._enter_mode_for_state(state)
            return PlannerDecision(
                PlannerAction.ASK_QUESTION,
                "open dialogue: keep coaching momentum, never auto-casual",
                metadata={"open_dialogue": True, "button_mode": "free"})

        if state == "rapport_building":
            self._enter_mode_for_state(state)
            return PlannerDecision(
                PlannerAction.ASK_QUESTION,
                "rapport building: easy, low-pressure coaching question",
                metadata={"rapport": True, "button_mode": "free"})

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

    def _apply_loop_guard(self, decision, ctx):
        ig = ctx.get("intent_graph") or {}
        progress = bool(ig.get("answered_current_question")) or bool(ig.get("new_slots_detected"))
        primary = (ig.get("primary_intent") or {}).get("intent", "")
        if progress or primary in ("answer", "additional_information", "commitment", "goal_update"):
            self._asking_streak = 0
        elif decision.action in _ASKING_ACTIONS and self.last_decision and \
                self.last_decision.action in _ASKING_ACTIONS:
            self._asking_streak += 1
        else:
            self._asking_streak = 0

        if self._asking_streak >= 2 and decision.action in _ASKING_ACTIONS:
            self._asking_streak = 0
            self._reset_ladder()
            return PlannerDecision(
                PlannerAction.PROVIDE_INSIGHT,
                "maximum questions rule: two consecutive questions asked — provide value now",
                confidence=0.75,
                metadata={"loop_break": True, "insight": True})
        return decision

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
        else:
            if self.mode is not None:
                self._discovery_exited = True
        self.mode = next_mode
        self.entered_at = now_iso()
        self.entered_by = by
        self.exit_condition = None
        return True

    def _move(self, target_mode, action, reason, by=""):
        self._enter_mode(target_mode, by=by)
        return PlannerDecision(action, reason)

    def _record(self, decision):
        decision.mode = self.mode
        decision.next_state = self.mode
        self.last_decision = decision
        if decision.action not in _ASKING_ACTIONS:
            self._reset_ladder()
        _attach_quick_replies(decision, self)
        return decision

    def _branch_completion_gate(self, ctx):
        pillar = ctx.get("current_pillar")
        if not pillar:
            return None
        branch = branch_policy.branch_for_pillar(pillar)
        if branch is None:
            return None
        if self.mode not in (None, ConversationMode.DISCOVERY,
                             ConversationMode.INVESTIGATION):
            return None

        fills = branch_policy.detect_slot_fills(
            ctx.get("message") or "", pillar, ctx.get("intent_graph") or {})
        if not fills:
            return None

        lifecycle = evaluate_branch_lifecycle(branch, ctx)

        if self._branch_state is None or self._branch_state.get("pillar") != pillar:
            self._branch_state = {"pillar": pillar, "filled": set(fills),
                                  "completed": False}
        self._branch_state["filled"].update(fills)
        state = self._branch_state
        if state["completed"]:
            return None
        definition = branch_policy.BRANCH_DEFINITIONS[branch]
        required = set(definition["required_slots"])
        filled_required = required & state["filled"]
        if len(filled_required) < definition["completion_threshold"]:
            return None
        state["completed"] = True

        self._enter_mode_for_state(ctx.get("state") or "")
        if self.mode != ConversationMode.COACHING:
            self._enter_mode(ConversationMode.COACHING, by="branch_completed",
                             force=True)
        return PlannerDecision(
            PlannerAction.PROVIDE_INSIGHT,
            "branch complete: %d/%d required slots filled" % (
                len(filled_required), len(required)),
            confidence=0.90,
            metadata={
                "branch_completion": True,
                "branch": branch,
                "pillar": pillar,
                "insight": True,
                "filled": sorted(state["filled"]),
                "missing": sorted(required - state["filled"]),
                "next_actions": list(definition["next_actions"]),
                "lifecycle_stage": lifecycle.current_stage.value,
                "completion_score": lifecycle.completion_score,
            })

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
        lower = user_message.lower()
        for label, pillar in _QUICK_REPLY_ENTRY_PILLARS.items():
            if pillar in deprioritized:
                continue
            if label in lower:
                return {"target_pillar": pillar,
                        "reason": "Quick reply entry: '%s'" % label,
                        "urgency": "high"}
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
                    return {"target_pillar": pillar,
                            "reason": "Context match: '%s'" % pat,
                            "urgency": "high"}
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
        from ..utils.storage import days_since

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

    def _is_capability(self, message):
        return _is_capability(message)

    def _is_casual(self, message):
        return _is_casual(message)

    def _is_goodbye(self, message):
        return _is_goodbye(message)

    def _is_topic_switch(self, message, ig):
        return _is_topic_switch(message, ig)

    def _is_direct_question(self, message):
        return _is_direct_question(message)

    def _is_wellness_concern(self, message, ig):
        return _is_wellness_concern(message, ig)

    def _extract_target_topic(self, message):
        return _extract_target_topic(message)

    def _is_rich_input(self, ctx):
        return _is_rich_input(ctx)

    def _reset_ladder(self):
        _reset_ladder(self)