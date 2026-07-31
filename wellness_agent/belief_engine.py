"""Belief Layer — beliefs inferred from memory facts.

Facts never disappear: the memory system is read-only here and is never
modified. Beliefs are deterministic inferences that EVOLVE over time:
  * they form when facts support them,
  * they strengthen or weaken as supporting/contradicting evidence changes,
  * they decay and fade out when support disappears — beliefs change,
    facts persist.

Belief shape:
{
  "id": "poor_sleep_reduced_energy",
  "belief": "Poor sleep is contributing to reduced energy.",
  "confidence": 84,
  "supporting_facts": [{"key", "value", "confidence", "at"}, ...],
  "contradicting_facts": [...],
  "evidence_count": 3,
  "created": iso, "updated": iso
}

Conversation uses beliefs first, facts second.
"""

import re

from .utils.storage import load_json, save_json, now_iso
from .config import get_data_dir

MAX_FACT_REFS = 6
BASE_CONFIDENCE = 30
CONFIDENCE_PER_POINT = 0.25
COUNT_BONUS = 2
COUNT_BONUS_CAP = 8
DECAY_PER_UPDATE = 8
FADE_THRESHOLD = 25
CONFIDENCE_FLOOR = 5
CONFIDENCE_CEIL = 95

_BAD_SLEEP = ("bad", "poor", "terrible", "awful", "horrible")
_GOOD_SLEEP = ("great", "good", "amazing", "excellent", "well", "fine")
_BAD_RELATIONSHIP = ("bad", "strain", "tense", "arguing", "distant", "struggl")
_GOOD_RELATIONSHIP = ("good", "great", "fine", "strong", "better")
_LOW_MOOD_WORDS = ("sad", "down", "low", "depressed", "unhappy", "miserable")
_GOOD_MOOD_WORDS = ("happy", "good", "great", "calm", "okay", "fine")
_LOW_MOTIVATION = ("low", "none", "zero", "no drive")
_HIGH_MOTIVATION = ("high", "good", "better", "improving")


def _num(value):
    m = re.search(r"\d+(?:\.\d+)?", str(value or ""))
    return float(m.group(0)) if m else None


def _has_any(value, words):
    value = str(value or "").lower()
    return any(w in value for w in words)


# id, belief text, support matcher(key, value, num), contradict matcher(key, value, num)
_BELIEF_RULES = [
    (
        "poor_sleep_reduced_energy",
        "Poor sleep is contributing to reduced energy.",
        lambda k, v, n: ("sleep_hours" in k and n is not None and n <= 5.5)
                        or ("sleep_quality" in k and _has_any(v, _BAD_SLEEP)),
        lambda k, v, n: ("sleep_hours" in k and n is not None and n >= 7.5)
                        or ("sleep_quality" in k and _has_any(v, _GOOD_SLEEP)),
    ),
    (
        "high_recurring_stress",
        "Stress is currently high and recurring.",
        lambda k, v, n: ("stress_level" in k and ((n or 0) >= 7
                                                  or _has_any(v, ("high", "elevated", "stressful", "hectic"))))
                        or ("work_stress" in k and _has_any(v, ("high", "elevated", "stressful", "hectic"))),
        lambda k, v, n: ("stress_level" in k and ((n is not None and n <= 3)
                                                  or _has_any(v, ("low", "calm", "relaxed", "fine", "minimal"))))
                        or ("work_stress" in k and _has_any(v, ("low", "fine", "good"))),
    ),
    (
        "recurring_low_mood",
        "Low mood has been a recurring pattern.",
        lambda k, v, n: "mood_state" in k and _has_any(v, _LOW_MOOD_WORDS),
        lambda k, v, n: "mood_state" in k and _has_any(v, _GOOD_MOOD_WORDS),
    ),
    (
        "limited_movement",
        "Movement is currently limited.",
        lambda k, v, n: "exercise" in k and n is not None and n <= 1,
        lambda k, v, n: "exercise" in k and n is not None and n >= 3,
    ),
    (
        "low_motivation",
        "Motivation is low right now.",
        lambda k, v, n: "motivation" in k and _has_any(v, _LOW_MOTIVATION),
        lambda k, v, n: "motivation" in k and _has_any(v, _HIGH_MOTIVATION),
    ),
    (
        "relationships_under_strain",
        "Relationships are under strain.",
        lambda k, v, n: "relationship" in k and _has_any(v, _BAD_RELATIONSHIP),
        lambda k, v, n: "relationship" in k and _has_any(v, _GOOD_RELATIONSHIP),
    ),
    (
        "anxiety_interfering",
        "Anxiety has been interfering with daily life.",
        lambda k, v, n: ("anxiety" in k and ((n or 0) >= 7 or "high" in str(v).lower()))
                        or "emotion_anxious" in k or "emotion_worried" in k,
        lambda k, v, n: "anxiety" in k and ((n is not None and n <= 3)
                                            or _has_any(v, ("low", "calm", "relaxed", "manageable"))),
    ),
]


class BeliefEngine:
    def __init__(self, user_id="default"):
        self.user_id = user_id
        self.path = get_data_dir("beliefs") / f"{user_id}_beliefs.json"
        self.store = self._load()

    def _load(self):
        data = load_json(self.path)
        if not data:
            data = {"user_id": self.user_id, "beliefs": {}}
        return data

    def _save(self):
        save_json(self.path, self.store)

    # ─── Public API ───────────────────────────────────────────

    def update(self, facts=None):
        facts = facts or []
        now = now_iso()
        existing = self.store.get("beliefs", {})
        updated = {}

        for rule_id, text, support_fn, contradict_fn in _BELIEF_RULES:
            supporting = [self._ref(f) for f in facts
                          if support_fn(f.get("key", ""), f.get("value", ""), _num(f.get("value")))]
            contradicting = [self._ref(f) for f in facts
                             if contradict_fn(f.get("key", ""), f.get("value", ""), _num(f.get("value")))]
            old = existing.get(rule_id)

            # Beliefs form and live on SUPPORT. Contradiction alone never mints
            # a belief — it only weakens (or, with support gone, decays) one.
            if supporting:
                strength = (sum(f["confidence"] for f in supporting)
                            - sum(f["confidence"] for f in contradicting))
                bonus = min(COUNT_BONUS_CAP, COUNT_BONUS * len(supporting))
                confidence = round(max(CONFIDENCE_FLOOR, min(CONFIDENCE_CEIL,
                                    BASE_CONFIDENCE + strength * CONFIDENCE_PER_POINT + bonus)))
                confidence = max(CONFIDENCE_FLOOR, confidence)
                updated[rule_id] = {
                    "id": rule_id,
                    "belief": text,
                    "confidence": confidence,
                    "supporting_facts": supporting[:MAX_FACT_REFS],
                    "contradicting_facts": contradicting[:MAX_FACT_REFS],
                    "evidence_count": len(supporting) + len(contradicting),
                    "created": old["created"] if old else now,
                    "updated": now if not old or old.get("confidence") != confidence else (old.get("updated") or now),
                }
            elif old:
                # Support faded: beliefs evolve — decay until they fade out.
                # Facts are never touched; only the inference changes.
                confidence = max(CONFIDENCE_FLOOR, old.get("confidence", 50) - DECAY_PER_UPDATE)
                if confidence < FADE_THRESHOLD:
                    continue
                faded = dict(old)
                faded["confidence"] = confidence
                faded["updated"] = now
                updated[rule_id] = faded

        self.store["beliefs"] = updated
        self.store["updated_at"] = now
        self._save()
        return self.get_beliefs()

    def get_beliefs(self, min_confidence=0):
        beliefs = [dict(b) for b in self.store.get("beliefs", {}).values()
                   if b.get("confidence", 0) >= min_confidence]
        return sorted(beliefs, key=lambda b: b["confidence"], reverse=True)

    def get_top(self, limit=3, min_confidence=40):
        return self.get_beliefs(min_confidence)[:limit]

    def get_belief(self, rule_id):
        return dict(self.store.get("beliefs", {}).get(rule_id) or {})

    # ─── Internals ────────────────────────────────────────────

    @staticmethod
    def _ref(fact):
        return {
            "key": fact.get("key", ""),
            "value": str(fact.get("value", ""))[:60],
            "confidence": fact.get("confidence", 60),
            "at": (fact.get("created_at") or fact.get("last_updated") or "")[:10],
        }
