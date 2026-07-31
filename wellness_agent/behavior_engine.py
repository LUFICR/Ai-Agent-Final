"""Behavior Learning layer — infers behavioral traits from repeated conversational evidence.

Deterministic and near-zero latency. A trait only materializes after repeated
supporting evidence (never on a single turn), and confidence moves gradually —
support increments slowly, contradiction erodes slowly, nothing is overwritten
instantly. Persisted per user in data/behaviors/.
"""

import re
from datetime import datetime

from .utils.storage import load_json, save_json, now_iso
from .config import get_data_dir

MIN_EVIDENCE = 2
SUPPORT_DELTA = 12
CONTRADICT_DELTA = 8
ACTIVE_THRESHOLD = 60
MAX_EVIDENCE = 12
MAX_SNIPPET = 80
DECAY_PER_DAY = 1        # slow decay: -1 confidence point per idle day
DECAY_FLOOR = 5
TREND_WINDOW = 2
TREND_TOLERANCE = 5
HISTORY_MAX = 15

TRAIT_LABELS = {
    "prefers_short_answers": "Prefers short answers",
    "reflective_thinker": "Reflective thinker",
    "analytical": "Analytical",
    "avoids_discussing_emotions": "Avoids discussing emotions",
    "motivated_by_progress": "Motivated by progress",
    "overwhelmed_by_choices": "Overwhelmed by choices",
    "likes_structured_routines": "Likes structured routines",
    # ─── Coaching traits (deterministic evidence, no LLM) ───
    "opens_up_slowly": "Opens up slowly",
    "responds_to_logic": "Responds to logic",
    "responds_to_empathy": "Responds to empathy",
    "motivated_by_rewards": "Motivated by rewards",
    "motivated_by_accountability": "Motivated by accountability",
    "avoids_specific_topics": "Avoids specific topics",
    "consistent_with_commitments": "Consistent with commitments",
    "loses_momentum_after_failure": "Loses momentum after failure",
    "perfectionist": "Perfectionist",
    "routine_builder": "Routine builder",
    "spontaneous": "Spontaneous",
    "highly_reflective": "Highly reflective",
}

EXCLUDE_SHORT = (
    "i don't know", "i dunno", "i dont know", "not sure", "nothing", "nah",
    "nope", "idk", "whatever", "maybe", "fine", "okay", "ok",
)

REFLECTIVE_PHRASES = [
    "i think", "i feel like", "maybe because", "probably because", "i realize",
    "i realized", "i notice", "i noticed", "i've noticed", "on reflection",
    "when i think about it", "it makes sense", "looking back", "i've been thinking",
    "i wonder", "i reflect", "i've realized", "i've been reflecting",
]

ANALYTICAL_PHRASES = [
    "because", "therefore", "since", "compared", "comparison", "pattern",
    "average", "consistently", "specifically", "the reason", "a pattern",
    "ratio", "percent", "on a scale", "typically", "in general",
]

EMOTION_PHRASES = [
    "i feel", "i'm feeling", "i am feeling", "i've been feeling", "feeling sad",
    "feeling anxious", "feeling lonely", "feeling stressed", "feeling angry",
    "feeling down", "feeling low", "anxious about", "worried about",
    "i get anxious", "i get stressed", "i feel sad", "i feel lonely",
    "i feel anxious", "i feel stressed", "it makes me sad", "i'm scared",
    "i've been sad",
]

AVOIDANCE_PHRASES = [
    "i don't want to talk", "i'd rather not", "i would rather not",
    "let's not go there", "can we change the subject", "it's nothing",
    "i don't know", "i dunno", "not sure", "forget it", "skip it",
    "prefer not to say",
]

PROGRESS_PHRASES = [
    "progress", "improved", "improving", "getting better", "better than",
    "made progress", "consistency", "streak", "in a row", "accomplished",
    "finished", "completed", "proud", "kept up", "followed through",
    "did it", "this week i", "i managed to", "kept it up",
]

CHOICE_OVERWHELM_PHRASES = [
    "too many", "can't decide", "can't choose", "hard to choose",
    "no idea what to pick", "all the options", "so many options",
    "don't know what i want", "overwhelmed", "what if i pick wrong",
    "what if i choose", "hard to decide", "unsure which", "decision fatigue",
]

ROUTINE_PHRASES = [
    "routine", "schedule", "structured", "structure", "checklist",
    "step by step", "steps", "organize", "organised", "organized",
    "habit", "tracker", "calendar", "planned", "planning",
    "same time", "consistency", "my list", "plan out",
]

# ─── Coaching trait evidence phrases (deterministic, no LLM) ───

LOGIC_PHRASES = [
    "makes sense", "that's logical", "that is logical", "logic",
    "the reason is", "because of", "caused by", "triggered by",
    "that explains", "that would explain", "the connection",
    "cause and effect", "it adds up", "that adds up", "fair point",
    "good point", "i see the connection",
]

EMPATHY_RESPONSE_PHRASES = [
    "thank you for listening", "thanks for listening", "thank you",
    "thanks for being", "that helps", "that really helps",
    "it helps to talk", "feels good to talk", "nice to talk",
    "helped me", "you understand", "that's kind", "i appreciate that",
    "appreciate you", "feels better talking", "feel heard", "being heard",
    "good to get it out",
]

REWARD_PHRASES = [
    "reward", "rewards", "treat myself", "treat for", "incentive",
    "bonus", "prize", "celebration", "celebrate", "if i finish",
    "then i'll treat", "sticker", "gift", "rewarded",
]

ACCOUNTABILITY_PHRASES = [
    "accountable", "accountability", "check in on me", "check-in",
    "hold me", "hold myself accountable", "someone to answer to",
    "keep me on track", "remind me", "deadline", "report back",
    "you'll check", "will you check", "make sure i", "follow up",
    "keep tabs on me",
]

SPECIFIC_TOPIC_WORDS = [
    "work", "job", "boss", "deadline", "sleep", "stress", "anxiety",
    "sad", "lonely", "family", "relationship", "partner", "money",
    "health", "mood",
]

COMMITMENT_KEEP_PHRASES = [
    "followed through", "kept my word", "kept it up", "stuck to",
    "stuck with", "didn't skip", "didn't miss", "did it every",
    "every day this week", "i've been keeping", "stayed consistent",
    "kept going", "made myself do", "kept at it", "haven't missed",
]

MOMENTUM_LOSS_PHRASES = [
    "missed one day", "missed a day", "broke my streak", "fell off",
    "went off track", "one bad day", "ruined", "gave up after",
    "stopped after", "quit after", "after i missed", "after one slip",
    "then i stopped", "gave up", "fell apart", "gave it up",
    "back to square one",
]

COMEBACK_PHRASES = [
    "got back on track", "picked it back up", "restarted",
    "started again", "got right back", "got back into",
]

PERFECTION_PHRASES = [
    "perfect", "perfectionist", "all or nothing", "if it's not perfect",
    "not good enough", "one mistake", "one slip", "ruined the whole",
    "what's the point if", "exactly right", "fall short", "never enough",
    "i failed", "not perfect", "wrecked it",
]

ACCEPT_PROGRESS_PHRASES = [
    "good enough", "something is better than nothing",
    "any progress counts", "it's okay if", "that's fine for now",
    "better than nothing",
]

ROUTINE_BUILD_PHRASES = [
    "i built", "i made a routine", "i set up", "started a habit",
    "new routine", "built a schedule", "planned my", "my routine is",
    "added to my routine", "made a schedule", "created a habit",
    "my checklist", "i do it every",
]

SPONTANEOUS_PHRASES = [
    "go with the flow", "whatever i feel like", "i don't plan",
    "not a planner", "no plan", "unplanned", "spontaneous",
    "last minute", "wing it", "i wing", "improvise", "in the moment",
    "just see how i feel", "follow my mood",
]

PLANNED_PHRASES = [
    "i planned", "made a schedule", "my routine", "my schedule",
    "i scheduled",
]

DEEP_REFLECTION_PHRASES = [
    "i've been thinking", "i've been reflecting", "thinking about why",
    "trying to understand why", "understand myself", "deep down",
    "i realize that i", "i realized that i", "patterns in myself",
    "self-aware", "i analyzed", "figured out why",
    "i've noticed about myself", "make me tick", "i wonder why i",
]


class BehaviorEngine:
    def __init__(self, user_id="default"):
        self.user_id = user_id
        self.path = get_data_dir("behaviors") / f"{user_id}_behaviors.json"
        self.store = self._load()

    def _load(self):
        data = load_json(self.path)
        if not data:
            data = {"user_id": self.user_id, "traits": {}, "signals": {}}
        for entry in data.setdefault("traits", {}).values():
            entry.setdefault("label", TRAIT_LABELS.get(entry.get("trait"), entry.get("trait")))
            entry.setdefault("evidence", [])
            entry.setdefault("status", self._status(entry.get("confidence", 40)))
            last = entry.get("last_updated") or now_iso()
            entry.setdefault("last_updated", last)
            entry.setdefault("last_confirmed", entry.get("last_confirmed") or last)
            entry.setdefault("trend", "stable")
            entry.setdefault("confidence_history", [{"at": last, "confidence": entry.get("confidence", 40)}])
        return data

    def _save(self):
        save_json(self.path, self.store)

    def get_traits(self):
        return {k: dict(v) for k, v in self.store.get("traits", {}).items()}

    def active_traits(self):
        return sorted(
            t for t, v in self.get_traits().items() if v.get("status") == "active"
        )

    def update(self, message, emotion=None):
        emotion = emotion or {}
        if not message or not message.strip():
            return self.get_traits()

        self._decay_traits()

        for trait, direction, snippet in self._evaluate_turn(message, emotion):
            if direction > 0:
                self._apply_support(trait, snippet)
            else:
                self._apply_contradiction(trait, snippet)
        self._save()
        return self.get_traits()

    def _apply_support(self, trait, snippet):
        signals = self.store.setdefault("signals", {})
        signals[trait] = signals.get(trait, 0) + 1
        traits = self.store.setdefault("traits", {})
        now = now_iso()

        if trait not in traits:
            if signals[trait] < MIN_EVIDENCE:
                return
            traits[trait] = {
                "trait": trait,
                "label": TRAIT_LABELS.get(trait, trait),
                "confidence": 40,
                "evidence": [self._evidence(snippet)],
                "last_updated": now,
                "last_confirmed": now,
                "trend": "stable",
                "confidence_history": [{"at": now, "confidence": 40}],
                "status": "uncertain",
            }
            return

        entry = traits[trait]
        entry["confidence"] = min(95, entry["confidence"] + SUPPORT_DELTA)
        entry["last_updated"] = now
        entry["last_confirmed"] = now
        entry["evidence"] = self._append_evidence(entry, snippet)
        entry["status"] = self._status(entry["confidence"])
        self._record_history(entry, now)
        entry["trend"] = self._trend(entry)

    def _apply_contradiction(self, trait, snippet):
        traits = self.store.get("traits", {})
        entry = traits.get(trait)
        if entry is None:
            return
        now = now_iso()
        entry["confidence"] = max(5, entry["confidence"] - CONTRADICT_DELTA)
        entry["last_updated"] = now
        entry["evidence"] = self._append_evidence(entry, "counter: " + snippet)
        entry["status"] = self._status(entry["confidence"])
        self._record_history(entry, now)
        entry["trend"] = self._trend(entry)

    def _decay_traits(self):
        traits = self.store.get("traits", {})
        now = now_iso()
        changed = False
        for entry in traits.values():
            days = self._days_since(entry.get("last_updated"))
            if not days or days <= 0:
                continue
            drop = min(days * DECAY_PER_DAY, entry["confidence"] - DECAY_FLOOR)
            if drop <= 0:
                continue
            entry["confidence"] -= drop
            entry["last_updated"] = now
            entry["status"] = self._status(entry["confidence"])
            self._record_history(entry, now)
            entry["trend"] = self._trend(entry)
            changed = True
        if changed:
            self._save()

    def _record_history(self, entry, now):
        history = entry.setdefault("confidence_history", [])
        history.append({"at": now, "confidence": entry["confidence"]})
        entry["confidence_history"] = history[-HISTORY_MAX:]
        entry["last_confirmed"] = entry.get("last_confirmed") or now

    def calibrate(self, trait, learned_confidence):
        """Blend a trait's stored confidence toward the learning layer's value.

        Called once at conversation end (live sessions only); no-op for traits
        that have never been observed. Per-user — never calibrated across users.
        """
        entry = self.store.get("traits", {}).get(trait)
        if entry is None:
            return
        now = now_iso()
        blend = round(0.5 * entry["confidence"] + 0.5 * max(20, min(95, learned_confidence)))
        if blend == entry["confidence"]:
            return
        entry["confidence"] = blend
        entry["status"] = self._status(blend)
        entry["last_updated"] = now
        self._record_history(entry, now)
        entry["trend"] = self._trend(entry)
        self._save()

    @staticmethod
    def _trend(entry):
        history = entry.get("confidence_history") or []
        if len(history) < 2:
            return "stable"
        window = [h["confidence"] for h in history[-TREND_WINDOW:]]
        delta = window[-1] - window[0]
        if delta > TREND_TOLERANCE:
            return "up"
        if delta < -TREND_TOLERANCE:
            return "down"
        return "stable"

    @staticmethod
    def _days_since(iso):
        if not iso:
            return 0
        try:
            last = datetime.fromisoformat(iso)
        except (TypeError, ValueError):
            return 0
        return max(0, (datetime.now() - last).days)

    def _append_evidence(self, entry, snippet):
        evidence = entry.get("evidence", []) + [self._evidence(snippet)]
        return evidence[-MAX_EVIDENCE:]

    @staticmethod
    def _evidence(snippet):
        return {"type": "message", "snippet": str(snippet)[:MAX_SNIPPET], "at": now_iso()}

    @staticmethod
    def _status(confidence):
        return "active" if confidence >= ACTIVE_THRESHOLD else "uncertain"

    def _evaluate_turn(self, message, emotion):
        text = message.strip().lower()
        words = re.findall(r"\b\w+\b", text)
        word_count = len(words)
        signals = []

        if 2 <= word_count <= 8 and not any(p in text for p in EXCLUDE_SHORT) \
                and emotion.get("avoidance", 0) < 55:
            signals.append(("prefers_short_answers", 1, f"{word_count} words"))
        elif word_count >= 25:
            signals.append(("prefers_short_answers", -1, f"{word_count} words"))

        found = self._find(text, REFLECTIVE_PHRASES)
        if found:
            signals.append(("reflective_thinker", 1, found))

        analytical_hits = [p for p in ANALYTICAL_PHRASES if p in text]
        has_number = bool(re.search(r"\b\d+(?:\.\d+)?\b", text))
        if len(analytical_hits) >= 2 or (has_number and word_count > 15):
            signals.append((
                "analytical", 1,
                "; ".join(analytical_hits[:3]) if analytical_hits else "numeric detail"
            ))

        if emotion.get("avoidance", 0) > 60:
            signals.append(("avoids_discussing_emotions", 1,
                            f"avoidance={emotion.get('avoidance')}"))
        elif self._find(text, AVOIDANCE_PHRASES) and not self._find(text, EMOTION_PHRASES):
            signals.append(("avoids_discussing_emotions", 1,
                            self._find(text, AVOIDANCE_PHRASES)))
        elif word_count >= 6 and self._find(text, EMOTION_PHRASES):
            signals.append(("avoids_discussing_emotions", -1,
                            self._find(text, EMOTION_PHRASES)))

        found = self._find(text, PROGRESS_PHRASES)
        if found:
            signals.append(("motivated_by_progress", 1, found))

        found = self._find(text, CHOICE_OVERWHELM_PHRASES)
        if found and emotion.get("stress", 0) >= 55:
            signals.append(("overwhelmed_by_choices", 1, found))

        found = self._find(text, ROUTINE_PHRASES)
        if found:
            signals.append(("likes_structured_routines", 1, found))

        # ─── Coaching trait signals (deterministic, no LLM) ───

        if 2 <= word_count <= 10 and emotion.get("engagement", 50) < 45 \
                and not any(t in text for t in SPECIFIC_TOPIC_WORDS) \
                and not any(p in text for p in EMOTION_PHRASES):
            signals.append(("opens_up_slowly", 1, f"{word_count} words, low engagement"))
        elif word_count >= 20 and self._find(text, EMOTION_PHRASES):
            signals.append(("opens_up_slowly", -1, f"long open turn ({word_count} words)"))

        found = self._find(text, LOGIC_PHRASES)
        if found:
            signals.append(("responds_to_logic", 1, found))

        found = self._find(text, EMPATHY_RESPONSE_PHRASES)
        if found:
            signals.append(("responds_to_empathy", 1, found))

        found = self._find(text, REWARD_PHRASES)
        if found:
            signals.append(("motivated_by_rewards", 1, found))

        found = self._find(text, ACCOUNTABILITY_PHRASES)
        if found:
            signals.append(("motivated_by_accountability", 1, found))

        topic_hit = any(t in text for t in SPECIFIC_TOPIC_WORDS)
        avoidance_found = self._find(text, AVOIDANCE_PHRASES)
        if (avoidance_found and topic_hit) or (emotion.get("avoidance", 0) > 60 and topic_hit):
            signals.append(("avoids_specific_topics", 1,
                            avoidance_found or f"avoidance={emotion.get('avoidance')}"))
        elif topic_hit and word_count >= 6 and not avoidance_found:
            signals.append(("avoids_specific_topics", -1, "engaged with a specific topic"))

        found = self._find(text, COMMITMENT_KEEP_PHRASES)
        if found:
            signals.append(("consistent_with_commitments", 1, found))
        elif self._find(text, MOMENTUM_LOSS_PHRASES):
            signals.append(("consistent_with_commitments", -1,
                            self._find(text, MOMENTUM_LOSS_PHRASES)))

        found = self._find(text, MOMENTUM_LOSS_PHRASES)
        if found:
            signals.append(("loses_momentum_after_failure", 1, found))
        elif self._find(text, COMEBACK_PHRASES):
            signals.append(("loses_momentum_after_failure", -1,
                            self._find(text, COMEBACK_PHRASES)))

        found = self._find(text, PERFECTION_PHRASES)
        if found:
            signals.append(("perfectionist", 1, found))
        elif self._find(text, ACCEPT_PROGRESS_PHRASES):
            signals.append(("perfectionist", -1, self._find(text, ACCEPT_PROGRESS_PHRASES)))

        found = self._find(text, ROUTINE_BUILD_PHRASES)
        if found:
            signals.append(("routine_builder", 1, found))
        elif self._find(text, SPONTANEOUS_PHRASES):
            signals.append(("routine_builder", -1, self._find(text, SPONTANEOUS_PHRASES)))

        found = self._find(text, SPONTANEOUS_PHRASES)
        if found:
            signals.append(("spontaneous", 1, found))
        elif self._find(text, PLANNED_PHRASES):
            signals.append(("spontaneous", -1, self._find(text, PLANNED_PHRASES)))

        found = self._find(text, DEEP_REFLECTION_PHRASES)
        if found:
            signals.append(("highly_reflective", 1, found))
        elif word_count <= 5:
            signals.append(("highly_reflective", -1, f"very short turn ({word_count} words)"))

        return signals

    @staticmethod
    def _find(text, phrases):
        for p in phrases:
            if p in text:
                return p
        return ""
