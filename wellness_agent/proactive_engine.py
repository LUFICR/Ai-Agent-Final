"""Proactive check-in engine — replaces generic openers with evidence-backed questions.

Deterministic and near-zero latency. Before a session starts (greeting turn), the
engine checks stored data for:

1. Unfinished conversations   — last session ended mid-exploration (session turns)
2. Previous commitments       — last session's conversation objective (session turns)
3. Recurring weekday insights — a signal that repeatedly deviates on one weekday (memory)
4. Repeated struggles         — high-confidence recurring patterns (why engine)
5. Behavior traits            — materialized behavioral traits (behavior engine)

A check-in is ONLY produced when a source has explicit stored evidence. If nothing
qualifies, the engine returns None and the normal greeting is used.
"""

from datetime import datetime

from .utils.storage import load_json
from .config import get_user_session_path
from .why_engine import SIGNAL_META

HOURS_AGO_CUTOFF = 2                 # last session must be > 2h old (in hours)
RECENT_DAYS = 30                     # weekday insight recency window
MIN_WEEKDAY_DAYS = 3                 # deviating days needed for a weekday insight
MIN_WEEKDAY_COUNT = 2                # min occurrences on the repeating weekday
MIN_PATTERN_CONFIDENCE = 70
MIN_TRAIT_CONFIDENCE = 60

UNFINISHED_STATES = ("deep_investigation", "insight_generation", "pillar_selection",
                     "routine_planning", "guided_discovery")

_COMMITMENT_PHRASES = {
    "learn_sleep_habits": "work on your sleep",
    "understand_work_stress": "understand your work stress",
    "explore_emotional_trigger": "explore what's been triggering your mood",
    "support_decision": "work through a decision",
    "explore_wellness_area": None,   # pillar-based, resolved dynamically
}

_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

_TRAIT_PHRASES = {
    "prefers_short_answers": "I've noticed you tend to prefer short, direct answers. Want to keep it that way today?",
    "reflective_thinker": "You seem to get a lot from reflecting out loud — anything on your mind?",
    "analytical": "You tend to notice patterns and details. Anything specific you've been tracking?",
    "overwhelmed_by_choices": "I've noticed too many options can feel heavy for you. Want me to keep choices simple today?",
    "motivated_by_progress": "You're motivated by progress. How have things been moving this week?",
    "likes_structured_routines": "You tend to like structured plans. Want to keep building on that?",
}


def _hours_ago(timestamp):
    try:
        then = datetime.fromisoformat(timestamp)
        return (datetime.now() - then).total_seconds() / 3600
    except Exception:
        return None


class ProactiveEngine:
    def __init__(self, memory, why_engine, behavior_engine):
        self.memory = memory
        self.why_engine = why_engine
        self.behavior_engine = behavior_engine
        self.user_id = memory.user_id

    def checkin(self):
        """Return {"question", "reason", "priority", "evidence"} or None."""
        candidates = []
        for method, priority in (
            (self._unfinished_conversation, 90),
            (self._previous_commitment, 85),
            (self._weekday_insight, 75),
            (self._repeated_struggle, 70),
            (self._behavior_trait, 60),
        ):
            result = method()
            if result:
                result["priority"] = priority
                candidates.append(result)
        if not candidates:
            return None
        best = max(candidates, key=lambda c: c["priority"])
        return best

    # ─── Sources ──────────────────────────────────────────────

    def _session_turns(self):
        data = load_json(get_user_session_path(self.user_id))
        return data.get("turns", []) if data else []

    def _latest_pillar(self):
        coverage = self.memory.get_pillar_coverage()
        best_pillar, best_ts = None, ""
        for pillar, info in coverage.items():
            ts = (info or {}).get("last_updated") or ""
            if ts > best_ts:
                best_pillar, best_ts = pillar, ts
        return best_pillar

    def _unfinished_conversation(self):
        turns = self._session_turns()
        last = turns[-1] if turns else {}
        state = (last.get("state") or {}).get("current_state") if isinstance(last.get("state"), dict) else None
        if not state or state not in UNFINISHED_STATES:
            return None
        hours = _hours_ago(last.get("timestamp", ""))
        if hours is None or hours <= HOURS_AGO_CUTOFF:
            return None
        info = last.get("state") or {}
        if info.get("insight_delivered"):
            return None
        pillar = (info.get("selected_pillar") or self._latest_pillar() or "").title()
        question = (f"Last time, we were exploring {pillar} — want to pick up where we left off?"
                    if pillar else
                    "Last time, we were in the middle of something. Want to continue where we left off?")
        return {"question": question, "reason": "unfinished_conversation",
                "evidence": {"state": state, "last_turn": last.get("timestamp")}}

    def _previous_commitment(self):
        turns = self._session_turns()
        last = turns[-1] if turns else {}
        objective = (last.get("objective") or {}) if isinstance(last.get("objective"), dict) else {}
        name = objective.get("objective") or ""
        phrase = _COMMITMENT_PHRASES.get(name)
        if name == "explore_wellness_area":
            pillar = self._latest_pillar()
            phrase = f"explore {pillar}" if pillar else None
        if not phrase:
            return None
        hours = _hours_ago(objective.get("set_at") or last.get("timestamp", ""))
        if hours is None or hours <= HOURS_AGO_CUTOFF:
            return None
        days = hours / 24
        if days >= 6:
            when = "last week"
        elif days >= 2:
            when = "earlier this week"
        elif days >= 1:
            when = "yesterday"
        else:
            when = "the other day"
        return {"question": f"You mentioned {when} you wanted to {phrase}. How has that been going?",
                "reason": "previous_commitment",
                "evidence": {"objective": name, "set_at": objective.get("set_at")}}

    def _weekday_insight(self):
        best = None
        for signal, meta in SIGNAL_META.items():
            days = self.why_engine.get_signal_deviations(signal)
            if len(days) < MIN_WEEKDAY_DAYS:
                continue
            counts = [0] * 7
            for day in days:
                try:
                    counts[datetime.fromisoformat(day).weekday()] += 1
                except Exception:
                    continue
            top = max(counts)
            if top < MIN_WEEKDAY_COUNT or top < len(days) / 2:
                continue
            if best is None or top > best[0]:
                best = (top, signal, days[-1])
        if not best:
            return None
        _, signal, last_seen = best
        counts = [0] * 7
        for day in self.why_engine.get_signal_deviations(signal):
            counts[datetime.fromisoformat(day).weekday()] += 1
        weekday = _WEEKDAYS[max(range(7), key=lambda i: counts[i])]
        meta = SIGNAL_META[signal]
        verb = "dips" if meta["arrow"] == "↓" else "spikes"
        return {"question": f"I noticed your {meta['display'].lower()} usually {verb} on {weekday}s. Is that still the case?",
                "reason": "weekday_insight",
                "evidence": {"signal": signal, "weekday": weekday, "last_seen": last_seen}}

    def _repeated_struggle(self):
        top = self.why_engine.get_top(min_confidence=MIN_PATTERN_CONFIDENCE)
        if not top:
            return None
        human = top.get("human")
        if human:
            return {"question": f"{human} Has that been happening lately?",
                    "reason": "repeated_struggle",
                    "evidence": {"pattern": top["pattern"], "repeats": top["repeats"]}}
        return {"question": f"I noticed {top['pattern']} has shown up {top['repeats']} times in your history. Has that been happening lately?",
                "reason": "repeated_struggle",
                "evidence": {"pattern": top["pattern"], "repeats": top["repeats"]}}

    def _behavior_trait(self):
        traits = self.behavior_engine.get_traits()
        best = None
        for trait, entry in traits.items():
            if entry.get("status") != "active" or entry.get("confidence", 0) < MIN_TRAIT_CONFIDENCE:
                continue
            phrase = _TRAIT_PHRASES.get(trait)
            if phrase and (best is None or entry.get("confidence", 0) > best[0]):
                best = (entry.get("confidence", 0), trait, phrase)
        if not best:
            return None
        return {"question": best[2], "reason": "behavior_trait",
                "evidence": {"trait": best[1], "confidence": best[0]}}
