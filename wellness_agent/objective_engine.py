"""Conversation Objective Engine — picks ONE objective per turn to steer the conversation.

Deterministic (no LLM call, near-zero latency). Uses conversation state, the latest
message, recent memory facts, emotion scores, the previous objective, and active
behavior traits (read BEFORE the objective is selected) to choose a stable objective.
Every response produced by the orchestrator is aligned with it.
"""

import re

from .utils.storage import now_iso

OBJECTIVES = [
    "build_rapport",
    "learn_sleep_habits",
    "understand_work_stress",
    "explore_wellness_area",
    "confirm_hypothesis",
    "increase_confidence",
    "explore_emotional_trigger",
    "encourage_reflection",
    "support_decision",
    "close_conversation",
]

OBJECTIVE_META = {
    "build_rapport": {"expected_turns": 2, "label": "Build rapport"},
    "learn_sleep_habits": {"expected_turns": 4, "label": "Learn sleep habits"},
    "understand_work_stress": {"expected_turns": 4, "label": "Understand work stress"},
    "explore_wellness_area": {"expected_turns": 3, "label": "Explore a wellness area"},
    "confirm_hypothesis": {"expected_turns": 1, "label": "Confirm an existing hypothesis"},
    "increase_confidence": {"expected_turns": 2, "label": "Increase confidence in a memory"},
    "explore_emotional_trigger": {"expected_turns": 3, "label": "Explore emotional trigger"},
    "encourage_reflection": {"expected_turns": 2, "label": "Encourage reflection"},
    "support_decision": {"expected_turns": 2, "label": "Help user make a decision"},
    "close_conversation": {"expected_turns": 1, "label": "Close conversation naturally"},
}

TOPIC_PATTERNS = {
    "sleep": [r"\bsleep(?:ing|y)?\b", r"\binsomnia\b", r"\bbedtime\b", r"\btired\b", r"\bfatigue\b", r"\bnap\b", r"\bnight(s)?\b"],
    "work": [r"\bwork\b", r"\bjob\b", r"\bcareer\b", r"\bboss\b", r"\bcoworker\b", r"\bcolleague\b", r"\bdeadline\b", r"\boffice\b"],
    "stress": [r"\bstress(?:ed|ful)?\b", r"\boverwhelm", r"\bpressure\b", r"\bburnout\b", r"\banxious\b", r"\banxiety\b", r"\bdrowning\b"],
    "mood": [r"\bmood\b", r"\bsad\b", r"\blonely\b", r"\bloneliness\b", r"\bdown\b", r"\bdepressed\b", r"\bflat\b"],
}

PILLAR_HINTS = {
    "learn_sleep_habits": "sleep",
    "understand_work_stress": "work",
    "explore_emotional_trigger": "mood",
}

QUESTION_TYPE_HINTS = {
    "confirm_hypothesis": "reflective",
    "increase_confidence": "clarifying",
    "support_decision": "choice",
    "encourage_reflection": "reflective",
    "explore_emotional_trigger": "narrative",
    "learn_sleep_habits": "clarifying",
    "understand_work_stress": "clarifying",
}

RAPPORT_STATES = ("greeting", "rapport_building", "avoidance_detection", "soft_exploration")

# objective → (matching active traits, priority boost, reason note)
TRAIT_PRIORITY = [
    ("build_rapport", {"opens_up_slowly", "avoids_specific_topics", "avoids_discussing_emotions"},
     10, "trust-building traits"),
    ("build_rapport", {"highly_reflective"}, 5, "highly reflective"),
    ("support_decision", {"responds_to_logic", "responds_to_empathy",
                          "motivated_by_rewards", "motivated_by_accountability"},
     6, "responds to structured input"),
    ("explore_emotional_trigger", {"highly_reflective", "responds_to_empathy"},
     6, "receptive to emotional exploration"),
    ("confirm_hypothesis", {"responds_to_logic", "analytical"}, 6, "analytical user"),
    ("increase_confidence", {"perfectionist", "loses_momentum_after_failure"},
     6, "needs gentle reassurance"),
    ("explore_wellness_area", {"spontaneous"}, 4, "prefers open exploration"),
    ("learn_sleep_habits", {"motivated_by_progress", "consistent_with_commitments",
                            "motivated_by_accountability", "routine_builder"},
     4, "action-oriented"),
    ("understand_work_stress", {"motivated_by_progress", "consistent_with_commitments",
                                "motivated_by_accountability", "routine_builder"},
     4, "action-oriented"),
    ("explore_emotional_trigger", {"motivated_by_progress", "consistent_with_commitments",
                                   "motivated_by_accountability"},
     4, "action-oriented"),
]


class ObjectiveEngine:
    def __init__(self, user_id="default"):
        self.user_id = user_id

    @staticmethod
    def pillar_hint(objective):
        return PILLAR_HINTS.get(objective)

    @staticmethod
    def question_type_hint(objective):
        return QUESTION_TYPE_HINTS.get(objective, "")

    def determine(self, state_info=None, user_message="", emotion=None, memory_facts=None,
                  previous_objective=None, current_pillar=None, avoidance_count=0,
                  exit_offered=False, active_traits=None, objective_history=None,
                  learning_boosts=None):
        state_info = state_info or {}
        emotion = emotion or {}
        memory_facts = memory_facts or []

        candidates = self._candidates(
            state_info, user_message, emotion, memory_facts,
            current_pillar, avoidance_count, exit_offered
        )
        if not candidates:
            candidates = [self._candidate("build_rapport", 70, "No stronger signal; default to rapport", 60)]

        if active_traits:
            self._apply_trait_priority(candidates, set(active_traits))
        if objective_history:
            self._apply_history_priority(candidates, objective_history)
        if learning_boosts:
            self._apply_learning_boosts(candidates, learning_boosts)

        chosen = max(candidates, key=lambda c: c["priority"])
        chosen = self._apply_stability(chosen, previous_objective, state_info)
        chosen["set_at"] = now_iso()
        chosen["set_state"] = state_info.get("current_state", "greeting")
        return chosen

    def _apply_history_priority(self, candidates, history):
        for c in candidates:
            entry = history.get(c["objective"])
            if not entry or not entry.get("attempts"):
                continue
            rate = entry["successes"] / entry["attempts"]
            boost = round((rate - 0.5) * 16)
            if boost:
                c["priority"] += boost
                c["reason"] += f" · history {rate:.0%} success"

    def _apply_learning_boosts(self, candidates, learning_boosts):
        """Per-user learned objective success rates (empty profile -> no-op)."""
        for c in candidates:
            boost = learning_boosts.get(c["objective"], 0)
            if boost:
                c["priority"] += boost
                c["reason"] += " · learned this works for you"

    def _apply_trait_priority(self, candidates, traits):
        for objective, trait_set, boost, note in TRAIT_PRIORITY:
            matches = sorted(traits & trait_set)
            if not matches:
                continue
            for c in candidates:
                if c["objective"] == objective:
                    c["priority"] += boost
                    if note not in c["reason"]:
                        c["reason"] += f" · {note}: {', '.join(matches)}"

    def _candidate(self, objective, priority, reason, confidence):
        meta = OBJECTIVE_META.get(objective, {"expected_turns": 2, "label": objective})
        return {
            "objective": objective,
            "label": meta["label"],
            "reason": reason,
            "priority": int(priority),
            "expected_turns": meta["expected_turns"],
            "confidence": int(min(100, max(0, confidence))),
            "elapsed": 0,
        }

    def _candidates(self, state_info, message, emotion, memory_facts, current_pillar,
                    avoidance_count, exit_offered):
        state = state_info.get("current_state", "greeting")
        candidates = []

        if exit_offered or avoidance_count >= 3:
            candidates.append(self._candidate(
                "close_conversation", 92, "Repeated avoidance; offer a graceful close", 90))

        if state in RAPPORT_STATES:
            candidates.append(self._candidate(
                "build_rapport", 80, f"State '{state}' needs trust before depth", 85))

        if state == "pillar_selection":
            candidates.append(self._candidate(
                "support_decision", 85, "User is choosing a focus area", 80))

        if state in ("guided_discovery", "deep_investigation"):
            pillar = current_pillar or state_info.get("selected_pillar")
            if not pillar:
                pillar = self._detect_topic(message)
            if pillar == "sleep":
                candidates.append(self._candidate(
                    "learn_sleep_habits", 88, "Sleep is the active area", 90))
            elif pillar in ("work", "stress"):
                candidates.append(self._candidate(
                    "understand_work_stress", 88, "Work stress is the active area", 90))
            elif pillar == "mood":
                candidates.append(self._candidate(
                    "explore_emotional_trigger", 84, "Mood is the active area", 82))
            elif pillar:
                candidates.append(self._candidate(
                    "explore_wellness_area", 80, f"Exploring area '{pillar}'", 75))
            if state == "deep_investigation" and self._has_low_confidence_facts(memory_facts):
                candidates.append(self._candidate(
                    "increase_confidence", 78, "Low-confidence facts need verification", 70))

        if state == "insight_generation" or state_info.get("insight_delivered"):
            candidates.append(self._candidate(
                "confirm_hypothesis", 86, "Hypothesis delivered; confirm resonance", 85))

        if state == "routine_planning":
            candidates.append(self._candidate(
                "support_decision", 84, "User is choosing routine steps", 80))

        if state == "reflection":
            candidates.append(self._candidate(
                "encourage_reflection", 82, "Closing the loop with reflection", 80))

        if emotion.get("avoidance", 0) > 60:
            candidates.append(self._candidate(
                "build_rapport", 86, "High avoidance; rebuild safety first", 80))

        return candidates

    def _apply_stability(self, chosen, previous, state_info):
        if not previous or not previous.get("objective"):
            return chosen
        if previous.get("set_state") != state_info.get("current_state"):
            chosen["elapsed"] = 0
            return chosen

        elapsed = previous.get("elapsed", 0) + 1
        if elapsed < previous.get("expected_turns", 2) and chosen["priority"] <= previous.get("priority", 0) + 10:
            kept = dict(previous)
            kept["elapsed"] = elapsed
            kept["confidence"] = max(kept.get("confidence", 0), chosen["confidence"])
            return kept

        chosen["elapsed"] = elapsed if chosen["objective"] == previous.get("objective") else 0
        return chosen

    def _has_low_confidence_facts(self, facts):
        return any(
            isinstance(f, dict) and f.get("category") != "emotional_history" and f.get("confidence", 100) < 60
            for f in facts
        )

    def _detect_topic(self, message):
        if not message:
            return None
        text = message.lower()
        best, best_count = None, 0
        for topic, patterns in TOPIC_PATTERNS.items():
            count = sum(1 for p in patterns if re.search(p, text))
            if count > best_count:
                best, best_count = topic, count
        return best if best_count > 0 else None
