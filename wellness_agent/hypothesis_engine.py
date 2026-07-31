"""Hypothesis Engine — maintains multiple candidate explanations with confidence.

Deterministic and near-zero latency. Hypotheses are generated from message,
pillar, and emotion signals; supported or contradicted turn by turn; merged via
canonical names; rejected below a confidence floor; and expired when stale.
Each hypothesis tracks evidence, supporting memories, and conflicting memories.
"""

from .utils.storage import load_json, save_json, now_iso, days_since
from .config import get_data_dir

REJECT_THRESHOLD = 25
EXPIRE_DAYS = 7
MAX_HYPOTHESES = 15
STREAK_BONUS_AFTER = 3
MAX_EVIDENCE = 8
MAX_MEMORIES = 5

HYPOTHESIS_ALIASES = {
    "Poor sleep": ["poor sleep", "sleep issues", "sleep problems", "can't sleep",
                   "cannot sleep", "insomnia", "sleep quality", "not sleeping",
                   "bad sleep", "no sleep", "sleep disruption", "sleep deprived"],
    "Work stress": ["work stress", "job stress", "work overload", "workload",
                    "pressure at work", "work pressure", "stress at work",
                    "job pressure", "pressure from work"],
    "Burnout": ["burnout", "burnt out", "burned out", "exhausted", "drained",
                "running on empty", "no energy", "burning out", "totally spent"],
    "Stress accumulation": ["stressed", "stress", "overwhelm", "pressure",
                            "too much", "can't keep up", "drowning", "strain"],
    "Anxiety / racing thoughts": ["anxiety", "anxious", "racing thoughts",
                                  "overthinking", "worried", "worry", "nervous"],
    "Screen time / late nights": ["screen time", "late night", "late nights",
                                  "phone", "scrolling", "stay up", "staying up",
                                  "netflix", "scrolling at night"],
    "Relationship strain": ["relationship", "partner", "spouse", "family",
                            "friend", "lonely", "loneliness", "social",
                            "arguing", "disconnected"],
    "Financial pressure": ["money", "finance", "financial", "budget", "debt",
                           "bills", "rent", "income", "expensive"],
    "Unstable routine": ["routine", "schedule", "irregular", "no structure",
                         "chaotic", "unorganized", "no plan"],
    "Low mood cycle": ["low mood", "sad", "depressed", "flat", "numb",
                       "hopeless", "miserable", "crying", "feeling down"],
    "Motivation dip": ["motivation", "motivated", "procrastinat", "can't start",
                       "can't get started", "unmotivated", "no drive", "no motivation"],
}

NEGATION_ALIASES = {
    "Poor sleep": ["sleep great", "sleep well", "sleep good", "sleeping well",
                   "sleeping fine", "sleep fine", "sleeping great",
                   "no problem sleeping", "sleep is fine"],
    "Work stress": ["work is fine", "work fine", "work great", "love my job",
                    "not stressed at work", "work is great", "no stress at work",
                    "job is fine"],
    "Stress accumulation": ["not stressed", "feeling calm", "relaxed", "feeling good"],
    "Burnout": ["lots of energy", "feeling energized", "full of energy", "energized"],
    "Relationship strain": ["relationship is good", "relationship fine", "great relationship"],
    "Financial pressure": ["money is fine", "financially fine", "no money problems"],
    "Low mood cycle": ["feeling happy", "feeling great", "mood is good", "mood good"],
}

PILLAR_HYPOTHESES = {
    "sleep": ["Poor sleep", "Work stress", "Anxiety / racing thoughts", "Screen time / late nights"],
    "stress": ["Stress accumulation", "Work stress", "Burnout", "Financial pressure"],
    "work": ["Work stress", "Burnout", "Stress accumulation", "Motivation dip"],
    "mood": ["Low mood cycle", "Burnout", "Stress accumulation", "Anxiety / racing thoughts"],
    "motivation": ["Motivation dip", "Burnout", "Stress accumulation", "Low mood cycle"],
    "relationships": ["Relationship strain", "Low mood cycle", "Stress accumulation"],
    "exercise": ["Burnout", "Motivation dip", "Unstable routine"],
    "routine": ["Unstable routine", "Poor sleep", "Work stress"],
    "nutrition": ["Unstable routine", "Stress accumulation", "Burnout"],
    "finances": ["Financial pressure", "Work stress", "Stress accumulation"],
}


def canonical(name):
    lowered = (name or "").strip().lower()
    if not lowered:
        return None
    best, best_len = None, 0
    for canon in HYPOTHESIS_ALIASES:
        if lowered == canon.lower():
            return canon
        if canon.lower() in lowered and len(canon) > best_len:
            best, best_len = canon, len(canon)
        for alias in HYPOTHESIS_ALIASES[canon]:
            if alias in lowered and len(alias) > best_len:
                best, best_len = canon, len(alias)
    return best or name.strip()


class HypothesisEngine:
    def __init__(self, user_id="default"):
        self.user_id = user_id
        self.path = get_data_dir("hypotheses") / f"{user_id}_hypotheses.json"
        self.store = self._load()
        self._expire_old()

    def _load(self):
        data = load_json(self.path)
        if not data:
            data = {"user_id": self.user_id, "turn": 0, "hypotheses": {}}
        return data

    def _save(self):
        save_json(self.path, self.store)

    def get_hypotheses(self):
        return {k: dict(v) for k, v in self.store.get("hypotheses", {}).items()}

    def get_active(self, min_confidence=0):
        hyps = [
            dict(v) for v in self.store.get("hypotheses", {}).values()
            if v.get("status") == "active" and v.get("confidence", 0) >= min_confidence
        ]
        return sorted(hyps, key=lambda h: h["confidence"], reverse=True)

    def get_leading(self, min_confidence=0):
        active = self.get_active(min_confidence)
        return active[0] if active else None

    def update(self, message, emotion=None, current_pillar=None, memory_facts=None):
        emotion = emotion or {}
        memory_facts = memory_facts or []
        self.store["turn"] = self.store.get("turn", 0) + 1
        turn = self.store["turn"]

        for name, strength, snippet, seeded in self._generate_candidates(message, emotion, current_pillar):
            self._support(name, strength, snippet, turn, create_only=seeded)
        self._apply_conflicts(message, turn)
        self._decay_unmentioned(turn)
        self._refresh_memories(memory_facts)
        self._expire_old()
        self._prune()
        self._save()
        return self.get_hypotheses()

    def support_hypothesis(self, hypothesis, snippet="root cause analysis"):
        canon = canonical(hypothesis)
        if canon:
            current = self.store.get("hypotheses", {}).get(canon, {}).get("confidence", 60)
            self._support(canon, min(96, current + 6), snippet, self.store.get("turn", 0))
            self._save()
        return self.get_hypotheses()

    def _support(self, name, strength, snippet, turn, create_only=False):
        canon = canonical(name)
        if not canon:
            return
        hyps = self.store.setdefault("hypotheses", {})
        existing = hyps.get(canon)
        if existing is None:
            hyps[canon] = {
                "hypothesis": canon,
                "confidence": min(96, strength),
                "status": "active",
                "streak": 1,
                "streak_turn": turn,
                "evidence": [self._evidence(snippet)],
                "supporting_memories": [],
                "conflicting_memories": [],
                "created_at": now_iso(),
                "last_updated": now_iso(),
            }
            return
        if existing.get("status") != "active":
            return
        if create_only:
            return

        if existing.get("streak_turn") == turn - 1:
            existing["streak"] = existing.get("streak", 0) + 1
        else:
            existing["streak"] = 1
        existing["streak_turn"] = turn

        delta = max(4, round((100 - existing["confidence"]) * 0.15))
        if existing.get("streak", 0) >= STREAK_BONUS_AFTER:
            delta += 2
        existing["confidence"] = min(96, existing["confidence"] + delta)
        existing["last_updated"] = now_iso()
        existing["evidence"] = (existing.get("evidence", []) + [self._evidence(snippet)])[-MAX_EVIDENCE:]

    def _apply_conflicts(self, message, turn):
        text = (message or "").lower()
        for canon, entry in self.store.get("hypotheses", {}).items():
            if entry.get("status") != "active":
                continue
            for neg in NEGATION_ALIASES.get(canon, []):
                if neg in text:
                    delta = max(8, round(entry["confidence"] * 0.25))
                    entry["confidence"] = max(5, entry["confidence"] - delta)
                    entry["streak"] = 0
                    entry["last_updated"] = now_iso()
                    entry["evidence"] = (entry.get("evidence", []) + [self._evidence("counter: " + neg)])[-MAX_EVIDENCE:]
                    if entry["confidence"] < REJECT_THRESHOLD:
                        entry["status"] = "rejected"
                        entry["rejected_at"] = now_iso()
                    break

    def _decay_unmentioned(self, turn):
        for entry in self.store.get("hypotheses", {}).values():
            if entry.get("streak_turn") != turn and entry.get("status") == "active":
                entry["streak"] = 0

    def _refresh_memories(self, memory_facts):
        hyps = self.store.get("hypotheses", {})
        for canon, entry in hyps.items():
            if entry.get("status") != "active":
                continue
            supporting, conflicting = [], []
            aliases = HYPOTHESIS_ALIASES.get(canon, [])
            negations = NEGATION_ALIASES.get(canon, [])
            for f in memory_facts:
                hay = f"{f.get('key', '')} {f.get('value', '')}".lower()
                if any(a in hay for a in aliases) or canon.lower() in hay:
                    supporting.append({"key": f.get("key"), "value": f.get("value")})
                elif any(n in hay for n in negations):
                    conflicting.append({"key": f.get("key"), "value": f.get("value")})
            entry["supporting_memories"] = supporting[:MAX_MEMORIES]
            entry["conflicting_memories"] = conflicting[:MAX_MEMORIES]

    def _expire_old(self):
        for entry in self.store.get("hypotheses", {}).values():
            if entry.get("status") != "rejected":
                updated = entry.get("last_updated", "")
                if updated and days_since(updated) >= EXPIRE_DAYS:
                    entry["status"] = "expired"
                    entry["expired_at"] = now_iso()

    def _prune(self):
        hyps = self.store.get("hypotheses", {})
        if len(hyps) <= MAX_HYPOTHESES:
            return
        frozen = sorted(
            (k for k, v in hyps.items() if v.get("status") != "active"),
            key=lambda k: hyps[k].get("confidence", 0),
        )
        for k in frozen:
            if len(hyps) <= MAX_HYPOTHESES:
                break
            del hyps[k]
        if len(hyps) > MAX_HYPOTHESES:
            overflow = len(hyps) - MAX_HYPOTHESES
            lowest = sorted(hyps, key=lambda k: hyps[k].get("confidence", 0))
            for k in lowest[:overflow]:
                del hyps[k]

    def _generate_candidates(self, message, emotion, current_pillar):
        text = (message or "").lower()
        strength_map = {}

        for canon, aliases in HYPOTHESIS_ALIASES.items():
            hits = sum(1 for a in aliases if a in text)
            if hits:
                strength = min(85, 55 + hits * 8)
                strength_map[canon] = max(strength_map.get(canon, 0), strength)

        if current_pillar and not strength_map:
            return [(name, 62, "pillar seed", True) for name in PILLAR_HYPOTHESES.get(current_pillar, [])]

        if emotion.get("burnout", 0) > 65:
            strength_map["Burnout"] = max(strength_map.get("Burnout", 0), 60)
        if emotion.get("stress", 0) > 65:
            strength_map["Stress accumulation"] = max(strength_map.get("Stress accumulation", 0), 60)
        if emotion.get("anxiety", 0) > 60:
            strength_map["Anxiety / racing thoughts"] = max(strength_map.get("Anxiety / racing thoughts", 0), 58)
        if emotion.get("loneliness", 0) > 60:
            strength_map["Relationship strain"] = max(strength_map.get("Relationship strain", 0), 58)

        candidates = []
        for canon, strength in strength_map.items():
            candidates.append((canon, strength, self._match_snippet(canon, text), False))

        if current_pillar:
            for name in PILLAR_HYPOTHESES.get(current_pillar, []):
                if name not in strength_map:
                    candidates.append((name, 62, "pillar seed", True))
        return candidates

    def _match_snippet(self, canon, text):
        for alias in HYPOTHESIS_ALIASES.get(canon, []):
            if alias in text:
                return alias
        if canon.lower() in text:
            return canon.lower()
        return "signal"

    @staticmethod
    def _evidence(snippet):
        return {"type": "message", "snippet": str(snippet)[:80], "at": now_iso()}
