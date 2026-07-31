"""Intervention Ranking Engine — deterministic ranking of recommendations.

For every candidate recommendation the engine computes:

  - impact      (0-10): how much the action is likely to move the user's wellbeing
  - confidence  (0-100): how well the action fits THIS user's stored evidence
  - difficulty  (1-10): effort required, adjusted for learned behavior traits
  - urgency     (0-10): how time-sensitive the action is right now

Ranked items carry a `reason` that references the user's stored history whenever
possible (memory facts, hypotheses, recurring why-patterns, recent emotions).

The engine is deterministic and near-zero latency — no LLM calls. It ranks any
list of action dicts (LLM-generated or template-generated), so both sources flow
through the same scoring.
"""

from datetime import datetime

_EASY, _MEDIUM, _HARD = 2, 5, 8

_TOPIC_KEYWORDS = {
    "sleep": ["sleep", "insomnia", "rest", "tired", "fatigue", "bedtime", "circadian"],
    "morning": ["morning", "wake", "start the day", "breakfast", "daylight"],
    "work": ["work", "job", "career", "burnout", "overwork", "deadline", "productivity",
             "focus", "screen", "deep work", "meeting"],
    "stress": ["stress", "overwhelm", "anxiety", "calm", "relax", "tense", "breath",
               "parasympathetic", "grounding"],
    "exercise": ["exercise", "workout", "gym", "fitness", "movement", "active", "walk",
                 "stretch"],
    "meditation": ["meditation", "mindfulness", "breathe", "present", "quiet"],
    "recovery": ["recovery", "rest", "break", "pause", "recharge", "unstructured"],
    "nutrition": ["nutrition", "eat", "food", "diet", "meal", "water", "hydration",
                  "vegetable"],
    "relationships": ["relation", "social", "friend", "family", "connect", "lonely",
                      "message", "vulnerab"],
    "mood": ["mood", "emotion", "feel", "sad", "happy", "positive", "gratitude"],
    "motivation": ["motivation", "drive", "goal", "purpose", "energy", "productive",
                   "momentum", "task"],
}

# Topics that are close enough that an action on one supports the other
_RELATED_TOPICS = {
    "stress": {"work", "mood", "sleep"},
    "work": {"stress", "productivity", "mood"},
    "mood": {"stress", "sleep", "motivation"},
    "sleep": {"stress", "mood", "recovery"},
    "exercise": {"mood", "sleep", "energy"},
    "motivation": {"work", "mood"},
    "meditation": {"stress", "mood"},
    "relationships": {"mood"},
    "recovery": {"stress", "sleep"},
    "nutrition": {"energy", "mood"},
}

# Topics to topics we rank support for urgency signals (recent high emotion)
_URGENT_SIGNAL_TOPICS = {"stress", "work", "mood", "sleep", "anxiety"}

# Behavior traits that make a plan heavier in practice
_HEAVY_PLAN_TRAITS = ("overwhelmed_by_choices", "prefers_short_answers")

_DIFFICULTY_SCALE = {"easy": _EASY, "medium": _MEDIUM, "hard": _HARD}


def _hours_ago(timestamp):
    try:
        then = datetime.fromisoformat(str(timestamp))
        return (datetime.now() - then).total_seconds() / 3600
    except Exception:
        return None


class InterventionRankingEngine:
    def __init__(self, memory=None, hypothesis_engine=None, why_engine=None, behavior_engine=None):
        self.memory = memory
        self.hypothesis_engine = hypothesis_engine
        self.why_engine = why_engine
        self.behavior_engine = behavior_engine

    # ─── Public API ───────────────────────────────────────────

    def rank(self, actions, pillar=None, root_cause="", facts=None, emotions=None,
             learning_weights=None):
        """Rank a list of recommendation dicts.

        Each action: {"action", "why", "time_of_day", "difficulty"}
        `learning_weights` (optional) maps topic -> 0.75..1.25 multiplier from
        the per-user learning layer; absent or empty -> no behavior change.
        Returns a sorted list of:
        {"action", "impact", "confidence", "difficulty", "urgency",
         "why", "time_of_day", "reason"}
        """
        facts = facts or []
        emotions = emotions or []
        learning_weights = learning_weights or {}
        traits = self._active_traits()
        leading_hypothesis = self._leading_hypothesis()
        why_pattern = self._why_pattern_for_pillar(pillar) if pillar else None

        ranked = []
        for action in self._normalize_actions(actions):
            topic = self._match_topic(action["action"]) or (pillar or "morning")
            item = {
                "action": action["action"],
                "impact": self._impact(topic, pillar),
                "confidence": self._confidence(topic, pillar, facts, traits, leading_hypothesis),
                "difficulty": self._difficulty(action.get("difficulty", "medium"), traits),
                "urgency": self._urgency(topic, facts, emotions, why_pattern),
                "why": action.get("why", ""),
                "time_of_day": action.get("time_of_day", "flexible"),
            }
            item["reason"] = self._reason(topic, pillar, facts, leading_hypothesis, why_pattern)
            weight = learning_weights.get(topic, 1.0)
            if weight != 1.0:
                item["score"] = round(self._composite(item) * weight, 2)
                if weight > 1.0:
                    item["reason"] += (" · I've seen this kind of step work well "
                                       "for you before")
            else:
                item["score"] = self._composite(item)
            ranked.append(item)

        ranked.sort(key=lambda i: (i["score"], i["confidence"]), reverse=True)
        for item in ranked:
            item.pop("score", None)
        return ranked

    def get_ranked_slice(self, actions, pillar=None, facts=None, emotions=None, limit=3):
        """Convenience wrapper: rank then return the top `limit` items."""
        return self.rank(actions, pillar=pillar, facts=facts, emotions=emotions)[:limit]

    # ─── Scoring ──────────────────────────────────────────────

    def _composite(self, item):
        return (item["impact"] * 4
                + item["urgency"] * 3
                + item["confidence"] / 10 * 2
                + (10 - item["difficulty"]) * 1.5)

    def _impact(self, topic, pillar):
        score = 5
        if pillar and topic == pillar:
            score += 2
        elif pillar and topic in _RELATED_TOPICS.get(pillar, set()):
            score += 1
        if self._has_fact(topic, min_confidence=80):
            score += 1
        if self.why_engine and self._why_count(topic) >= 3:
            score += 1
        if self._hypothesis_matches(topic, min_confidence=55):
            score += 1
        return min(10, score)

    def _confidence(self, topic, pillar, facts, traits, leading_hypothesis):
        score = 55
        if pillar and topic == pillar:
            score += 15
        elif pillar and topic in _RELATED_TOPICS.get(pillar, set()):
            score += 6
        matches = self._matching_facts(topic, facts)
        score += min(15, 5 * len(matches))
        if matches and sum(m.get("confidence", 50) for m in matches) / len(matches) >= 80:
            score += 5
        if leading_hypothesis:
            score += min(5, leading_hypothesis.get("confidence", 0) / 20)
        if self.why_engine:
            pattern = self._why_pattern(topic)
            if pattern:
                score += min(5, pattern.get("confidence", 0) / 20)
        if any(t in traits for t in _HEAVY_PLAN_TRAITS) and self._difficulty("medium", traits) >= 5:
            score -= 8
        return max(30, min(95, score))

    def _difficulty(self, difficulty, traits):
        base = _DIFFICULTY_SCALE.get(str(difficulty).lower(), _MEDIUM)
        if base >= 5 and any(t in traits for t in _HEAVY_PLAN_TRAITS):
            base += 1
        return min(10, base)

    def _urgency(self, topic, facts, emotions, why_pattern):
        score = 3
        recent = [e for e in emotions[-3:] if isinstance(e, dict)]
        if topic in _URGENT_SIGNAL_TOPICS and recent:
            if any(e.get("stress", 0) > 70 or e.get("anxiety", 0) > 70
                   or e.get("burnout", 0) > 70 for e in recent):
                score += 2
        if recent:
            intensities = [e.get("emotional_intensity", 0) for e in recent]
            if intensities and sum(intensities) / len(intensities) > 60:
                score += 1
        if why_pattern and why_pattern.get("topic") == topic:
            last_seen = why_pattern.get("last_seen")
            hours = _hours_ago(last_seen) if last_seen else None
            if hours is not None and hours <= 72:
                score += 2
        matches = self._matching_facts(topic, facts)
        if any(m.get("evidence_count", 0) >= 3 for m in matches):
            score += 1
        return min(10, score)

    # ─── History reference ────────────────────────────────────

    def _reason(self, topic, pillar, facts, leading_hypothesis, why_pattern):
        parts = []
        match = self._best_fact(topic, facts)
        if match:
            value = str(match.get("value", ""))[:120]
            parts.append(f"This fits what you told me earlier: \u201c{value}\u201d")
        if why_pattern:
            parts.append(f"it connects to the {why_pattern.get('pattern', 'pattern').lower()} "
                         f"pattern I've seen {why_pattern.get('repeats', 0)} times")
        if leading_hypothesis:
            parts.append(f"it targets the pattern we've been exploring "
                         f"({leading_hypothesis.get('hypothesis', 'your situation').lower()})")
        if not parts:
            base = pillar or "this area"
            parts.append(f"it's the step I think fits best for {base} right now")
        return "; ".join(parts).capitalize()

    # ─── Evidence lookups ─────────────────────────────────────

    def _active_traits(self):
        if not self.behavior_engine:
            return set()
        traits = self.behavior_engine.get_traits()
        return {name for name, entry in traits.items()
                if entry.get("status") == "active" and entry.get("confidence", 0) >= 60}

    def _leading_hypothesis(self):
        if not self.hypothesis_engine:
            return None
        return self.hypothesis_engine.get_leading()

    def _why_pattern(self, topic):
        if not self.why_engine:
            return None
        relevant = self.why_engine.get_relevant(topic, min_confidence=55)
        if relevant:
            relevant["topic"] = topic
            return relevant
        return None

    def _why_pattern_for_pillar(self, pillar):
        if not self.why_engine:
            return None
        relevant = self.why_engine.get_relevant(pillar, min_confidence=55)
        if relevant:
            relevant["topic"] = pillar
            return relevant
        return None

    def _why_count(self, topic):
        pattern = self._why_pattern(topic)
        return pattern.get("repeats", 0) if pattern else 0

    def _hypothesis_matches(self, topic, min_confidence=55):
        leading = self._leading_hypothesis()
        if not leading or leading.get("confidence", 0) < min_confidence:
            return False
        text = f"{leading.get('hypothesis', '')}".lower()
        return any(kw in text for kw in _TOPIC_KEYWORDS.get(topic, []))

    def _matching_facts(self, topic, facts):
        keywords = _TOPIC_KEYWORDS.get(topic, [])
        matched = []
        for f in facts or []:
            if not isinstance(f, dict):
                continue
            haystack = f"{f.get('key', '')} {f.get('value', '')}".lower()
            if any(kw in haystack for kw in keywords):
                matched.append(f)
        return matched

    def _best_fact(self, topic, facts):
        matches = self._matching_facts(topic, facts)
        if not matches:
            return None
        return max(matches, key=lambda f: (f.get("confidence", 0), f.get("evidence_count", 0)))

    def _has_fact(self, topic, min_confidence=80):
        facts = self.memory.get_all_facts() if self.memory else []
        return any(f.get("confidence", 0) >= min_confidence
                   for f in self._matching_facts(topic, facts))

    def _match_topic(self, text):
        text_lower = (text or "").lower()
        scores = {topic: sum(1 for kw in kws if kw in text_lower)
                  for topic, kws in _TOPIC_KEYWORDS.items()}
        best = max(scores, key=scores.get)
        return best if scores[best] > 0 else None

    def _normalize_actions(self, actions):
        normalized = []
        for action in actions or []:
            if not isinstance(action, dict):
                continue
            text = action.get("action")
            if not text:
                continue
            normalized.append({
                "action": text,
                "why": action.get("why", ""),
                "time_of_day": action.get("time_of_day", "flexible"),
                "difficulty": action.get("difficulty", "medium"),
            })
        return normalized
