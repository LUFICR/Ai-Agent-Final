"""Self Evaluation — lightweight assessment after every AI response.

Deterministic and near-zero latency. NO LLM calls. After each response, the
next user reply is scored against the objective the response was aligned with,
using heuristics over: user reply, conversation state, emotion, objective, and
behavior traits.

Result shape (per turn):
{
  "objective": "learn_sleep_habits",
  "objective_completed": true,
  "confidence": 84,        # how sure the assessment is
  "reason": "...",
  "next_strategy": "..."
}

Results are persisted per user. A per-objective track (attempts / successes /
average confidence / last result) is maintained, and future objective selection
reads it to prefer objectives the user responds well to.
"""

import re

from .utils.storage import load_json, save_json, now_iso
from .config import get_data_dir
from .behavior_engine import (
    EXCLUDE_SHORT, PROGRESS_PHRASES, REFLECTIVE_PHRASES, AVOIDANCE_PHRASES,
    LOGIC_PHRASES, ACCOUNTABILITY_PHRASES, REWARD_PHRASES,
)
from .objective_engine import PILLAR_HINTS, TOPIC_PATTERNS

MAX_EVALUATIONS = 100
COMPLETED_THRESHOLD = 55
SCORE_CEILING = 97

_ACK_PHRASES = (
    "yes", "yep", "yeah", "yup", "sure", "ok", "okay", "got it", "understood",
    "right", "exactly", "true", "correct", "agreed", "i agree", "sounds good",
    "that makes sense", "makes sense", "good idea", "great idea", "perfect",
    "i understand", "thank", "thanks", "helpful", "appreciate", "i think so",
    "i do", "that's me", "that's true", "spot on", "that's right", "will do",
    "i will", "i'll try", "i'll do", "let's do", "i'll pick", "i choose",
)

_NEG_PHRASES = (
    "no", "nope", "nah", "not really", "not at all", "i don't think",
    "i dont think", "wrong", "no way", "not yet", "didn't", "won't", "can't",
    "not helpful", "that doesn't", "i don't want", "i dont want", "forget it",
    "never mind", "no idea", "that's not", "thats not",
)

_CHOICE_PHRASES = (
    "i'll pick", "i choose", "i'll do the", "let's do the", "first one",
    "the first", "that one", "the second", "number one", "number two",
    "option one", "option two", "let's start with", "i'll try the",
)

_EXIT_PHRASES = (
    "bye", "goodbye", "see you", "later", "gotta go", "have to go",
    "take care", "good night",
)

_DEFLECTION_PHRASES = EXCLUDE_SHORT + tuple(AVOIDANCE_PHRASES)

_NEXT_STRATEGY_MAP = {
    "build_rapport": "advance_to_guided_discovery",
    "confirm_hypothesis": "advance_to_routine_planning",
    "support_decision": "move_to_action_planning",
    "close_conversation": "end_session",
}


class SelfEvaluator:
    def __init__(self, user_id="default"):
        self.user_id = user_id
        self.path = get_data_dir("evaluations") / f"{user_id}_evaluations.json"
        self.store = self._load()

    def _load(self):
        data = load_json(self.path)
        if not data:
            data = {"user_id": self.user_id, "entries": [], "objective_track": {}}
        return data

    def _save(self):
        save_json(self.path, self.store)

    def reset(self):
        self.store = {"user_id": self.user_id, "entries": [], "objective_track": {}}
        self._save()

    # ─── Public API ───────────────────────────────────────────

    def evaluate(self, reply="", state=None, emotion=None, objective=None,
                 traits=None):
        objective = objective or {}
        objective_name = objective.get("objective")
        if not objective_name:
            return None
        text = (reply or "").strip().lower()
        words = re.findall(r"\b\w+\b", text)
        word_count = len(words)
        emotion = emotion or {}
        traits = set(traits or [])
        score, signals = 50, []

        def add(delta, label):
            nonlocal score
            score += delta
            signals.append((delta, label))

        # ─── User reply signals ───
        if self._find(text, _ACK_PHRASES):
            add(18, "positive acknowledgment")
        if self._find(text, _NEG_PHRASES):
            add(-22, "negative reply")
        if self._find(text, PROGRESS_PHRASES):
            add(16, "progress reported")
        if self._find(text, REFLECTIVE_PHRASES):
            add(10, "reflective reply")
        if self._find(text, LOGIC_PHRASES):
            add(10, "logical engagement")
        if self._find(text, _CHOICE_PHRASES):
            add(20, "user made a choice")
        if self._find(text, ACCOUNTABILITY_PHRASES) or self._find(text, REWARD_PHRASES):
            add(14, "commitment language")
        if self._find(text, _EXIT_PHRASES):
            add(16, "closing the session")
        if self._find(text, _DEFLECTION_PHRASES):
            add(-15, "deflection")
        if word_count >= 12:
            add(8, "detailed reply")
        elif word_count <= 2 and not self._find(text, _ACK_PHRASES):
            add(-12, "bare reply")

        # ─── Emotion signals ───
        engagement = emotion.get("engagement", 50)
        if engagement >= 60:
            add(8, "high engagement")
        elif engagement < 35:
            add(-8, "low engagement")
        if emotion.get("avoidance", 0) >= 60:
            add(-14, "high avoidance")
        if emotion.get("stress", 50) <= 35:
            add(5, "calm reply")

        # ─── Behavior trait adjustments ───
        if "prefers_short_answers" in traits and word_count <= 6:
            add(6, "short replies are normal for this user")
        if "avoids_discussing_emotions" in traits and word_count >= 6:
            add(4, "topical engagement despite emotion avoidance")
        if "responds_to_logic" in traits and self._find(text, LOGIC_PHRASES):
            add(6, "matches the user's logical style")

        # ─── Objective-specific signals ───
        if objective_name == "build_rapport":
            if not self._find(text, _DEFLECTION_PHRASES) and word_count >= 3:
                add(10, "engaged with rapport")
        elif objective_name in ("learn_sleep_habits", "understand_work_stress",
                                "explore_emotional_trigger"):
            pillar = PILLAR_HINTS.get(objective_name)
            patterns = TOPIC_PATTERNS.get(pillar, []) if pillar else []
            if patterns and any(re.search(p, text) for p in patterns):
                add(15, f"{pillar} topic discussed")
            if word_count >= 10:
                add(5, "in-depth reply")
        elif objective_name == "explore_wellness_area":
            if word_count >= 8:
                add(10, "explored an area")
        elif objective_name == "confirm_hypothesis":
            if self._find(text, _ACK_PHRASES):
                add(12, "hypothesis confirmed")
            elif self._find(text, _NEG_PHRASES):
                add(-18, "hypothesis rejected")
        elif objective_name == "increase_confidence":
            if self._find(text, _ACK_PHRASES) or word_count >= 10:
                add(12, "detail shared")
        elif objective_name == "encourage_reflection":
            if self._find(text, REFLECTIVE_PHRASES):
                add(14, "reflection offered")
            elif word_count >= 10:
                add(8, "thoughtful reply")
        elif objective_name == "support_decision":
            if self._find(text, _CHOICE_PHRASES):
                add(12, "decision made")
            elif self._find(text, _ACK_PHRASES):
                add(8, "decision acknowledged")
        elif objective_name == "close_conversation":
            if self._find(text, _EXIT_PHRASES):
                add(15, "session closing")
            elif self._find(text, _ACK_PHRASES):
                add(10, "accepted the close")

        score = max(0, min(100, score))
        completed = score >= COMPLETED_THRESHOLD
        confidence = score if completed else 100 - score
        confidence = max(5, min(SCORE_CEILING, confidence))
        reason = "; ".join(label for _, label in sorted(signals, reverse=True)[:3])
        reason = reason or "no strong signals"

        return {
            "objective": objective_name,
            "objective_completed": completed,
            "confidence": confidence,
            "reason": reason,
            "next_strategy": self._next_strategy(completed, objective_name, emotion, score),
            "state": state,
            "emotion": emotion.get("primary_emotion", "neutral"),
            "reply_snippet": (reply or "").strip()[:80],
            "at": now_iso(),
        }

    def record(self, result):
        if not result:
            return
        entries = self.store.setdefault("entries", [])
        entries.append(result)
        self.store["entries"] = entries[-MAX_EVALUATIONS:]
        track = self.store.setdefault("objective_track", {})
        entry = track.setdefault(result["objective"], {
            "attempts": 0, "successes": 0, "avg_confidence": 0, "last": None})
        entry["attempts"] += 1
        if result["objective_completed"]:
            entry["successes"] += 1
        entry["avg_confidence"] = round(
            ((entry["attempts"] - 1) * entry["avg_confidence"] + result["confidence"])
            / entry["attempts"])
        entry["last"] = result["objective_completed"]
        self._save()

    def get_track(self):
        return dict(self.store.get("objective_track", {}))

    def get_recent(self, limit=10):
        return [dict(e) for e in self.store.get("entries", [])[-limit:]]

    # ─── Internals ────────────────────────────────────────────

    def _next_strategy(self, completed, objective_name, emotion, score):
        if not completed:
            if emotion.get("avoidance", 0) >= 60:
                return "switch_to_rapport_building"
            if score <= 25:
                return "change_approach"
            if objective_name in ("learn_sleep_habits", "understand_work_stress",
                                  "explore_emotional_trigger"):
                return "simplify_question"
            return "persist_with_alternative"
        return _NEXT_STRATEGY_MAP.get(objective_name, "continue_current_objective")

    @staticmethod
    def _find(text, phrases):
        for p in phrases:
            if re.search(rf"\b{re.escape(p)}\b", text):
                return p
        return None
