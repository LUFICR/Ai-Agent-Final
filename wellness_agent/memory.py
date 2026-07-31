import re
from .utils.storage import load_json, save_json, now_iso, days_since
from .config import get_user_memory_path

# Sentiment lexicon for contradiction detection (deterministic, no LLM)
_POSITIVE_WORDS = frozenset([
    "love", "loved", "loves", "likes", "liked", "enjoy", "enjoyed", "enjoys",
    "adore", "adored", "adores", "prefer", "preferred", "prefers", "good",
    "great", "fine", "well", "amazing", "better", "nice", "happy", "easy",
    "calm", "relaxed", "smooth", "positive", "restful", "peaceful",
    "energized", "strong", "productive", "bright",
])
_NEGATIVE_WORDS = frozenset([
    "hate", "hated", "hates", "dislike", "disliked", "dislikes", "loathe",
    "loathes", "dread", "dreaded", "dreads", "despise", "despises", "bad",
    "terrible", "awful", "poor", "horrible", "worse", "worst", "miserable",
    "struggle", "struggling", "hard", "difficult", "stressful", "anxious",
    "overwhelming", "chaotic", "painful", "sad", "depressed", "exhausted",
    "tired", "negative", "restless", "dark",
])
_NEGATED_PHRASES = frozenset([
    "don't like", "dont like", "do not like", "don't enjoy", "dont enjoy",
    "don't love", "dont love", "don't care for", "not a fan", "no longer like",
])
_STOPWORDS = frozenset([
    "i", "i'm", "im", "i've", "ive", "my", "me", "mine", "the", "a", "an",
    "and", "but", "or", "it", "it's", "its", "is", "was", "are", "were",
    "to", "of", "in", "on", "for", "with", "at", "that", "this", "these",
    "those", "really", "honestly", "just", "so", "very", "feel", "feeling",
    "feels", "felt", "been", "being", "am", "have", "has", "had", "do",
    "does", "did", "about", "from", "up", "out", "over", "into",
])
_HIGH_VALUE_KEYS = ("sleep_quality", "sleep_hours", "work_stress", "mood_state",
                    "exercise_frequency", "stress_level", "bedtime",
                    "relationship_status", "motivation", "routine", "preference")
_CONFIRM_ACCEPT = ("yes", "yeah", "yep", "yup", "correct", "right", "true",
                   "exactly", "definitely", "absolutely", "indeed", "sure",
                   "that's right", "thats right", "it changed", "changed")
_CONFIRM_REJECT = ("no", "nope", "nah", "not really", "not at all", "no way",
                   "wrong", "false", "still the same", "same as before",
                   "not changed", "no change")


class MemorySystem:
    def __init__(self, user_id="default"):
        self.user_id = user_id
        self.path = get_user_memory_path(user_id)
        self.memory = self._load()

    def _load(self):
        data = load_json(self.path)
        if not data:
            data = {
                "user_id": self.user_id,
                "facts": [],
                "trust_score": 30,
                "pillar_coverage": {},
                "last_updated": now_iso(),
                "session_count": 0,
                "avoided_pillars": {},
                "deprioritized_pillars": [],
                "_pending_confirmations": []
            }
        for fact in data.get("facts", []):
            self._normalize_fact(fact)
        data.setdefault("_pending_confirmations", [])
        return data

    def _normalize_fact(self, fact):
        if not isinstance(fact, dict):
            return
        fact.setdefault("category", "identity")
        fact.setdefault("key", "unknown")
        fact.setdefault("value", "")
        fact.setdefault("created_at", fact.get("last_updated", now_iso()))
        fact.setdefault("last_updated", now_iso())
        fact.setdefault("source", "conversation")
        fact.setdefault("importance", self._score_importance(
            fact["category"], fact["key"], fact.get("value", ""), fact.get("source", "conversation")))
        fact.setdefault("confidence", 60)
        fact.setdefault("evidence_count", 1)
        fact.setdefault("last_confirmed", None)
        fact.setdefault("needs_confirmation", False)
        fact.setdefault("source_history", [{
            "source": fact.get("source", "conversation"),
            "text": fact.get("value", ""),
            "at": fact.get("created_at", fact.get("last_updated", now_iso()))
        }])
        fact.setdefault("resolved", False)
        fact.setdefault("contradicts", False)

    def _score_importance(self, category, key, value, source):
        score = 40
        if category == "emotional_history":
            score += 25
        elif category == "habits":
            score += 10
        elif category in ("identity", "preferences", "lifestyle"):
            score += 20
        if any(k in str(key) for k in _HIGH_VALUE_KEYS):
            score += 15
        v = str(value).lower()
        if any(w in v for w in ("love", "hate", "enjoy", "struggl", "suffer",
                                "panic", "can't stand", "always", "never")):
            score += 10
        if source == "user_statement":
            score += 5
        return min(95, score)

    def save(self):
        self.memory["last_updated"] = now_iso()
        save_json(self.path, self.memory)

    def add_fact(self, category, key, value, confidence=70, source="conversation", message=None):
        self._apply_decay()
        existing = self.get_fact(key)
        if existing:
            return self.update_fact(key, value, confidence, source, message)
        fact = {
            "category": category,
            "key": key,
            "value": value,
            "confidence": confidence,
            "source": source,
            "last_updated": now_iso(),
            "created_at": now_iso(),
            "importance": self._score_importance(category, key, value, source),
            "evidence_count": 1,
            "last_confirmed": None,
            "needs_confirmation": False,
            "source_history": [{
                "source": source,
                "text": message or value,
                "at": now_iso()
            }],
            "resolved": False,
            "contradicts": False
        }
        self.memory["facts"].append(fact)
        self._update_pillar_coverage(key, confidence)
        self.save()
        return fact

    def update_fact(self, key, value, confidence=None, source="conversation", message=None):
        for fact in self.memory["facts"]:
            if fact["key"] == key:
                if self._detect_contradiction(fact, value, message):
                    return self._handle_contradiction(fact, value, source, message)
                old_value = fact["value"]
                same = str(old_value).strip().lower() == str(value).strip().lower()
                fact["value"] = value
                if confidence:
                    base = max(fact.get("confidence", 60), confidence)
                    fact["confidence"] = min(95, base + (5 if same else 0))
                fact["source"] = source
                fact["last_updated"] = now_iso()
                fact["evidence_count"] = fact.get("evidence_count", 1) + 1
                hist = fact.setdefault("source_history", [])
                hist.append({"source": source, "text": message or value, "at": now_iso()})
                fact["source_history"] = hist[-8:]
                if same:
                    fact["last_confirmed"] = now_iso()
                    fact["needs_confirmation"] = False
                    fact["contradicts"] = False
                self._update_pillar_coverage(key, fact["confidence"])
                self.save()
                return {"action": "update", "old_value": old_value, "new_value": value, "fact": fact}
        return None

    # ─── Contradiction detection & confirmation ───────────────

    def _polarity(self, text):
        t = f" {str(text or '').lower()} "
        for n in _NEGATED_PHRASES:
            if n in t:
                return -1
        words = set(re.findall(r"[a-z']+", t))
        pos = sum(1 for w in _POSITIVE_WORDS if w in words)
        neg = sum(1 for w in _NEGATIVE_WORDS if w in words)
        return 1 if pos > neg else (-1 if neg > pos else 0)

    def _shared_tokens(self, a, b):
        ta = {t for t in str(a).lower().split() if t not in _STOPWORDS and len(t) > 2}
        tb = {t for t in str(b).lower().split() if t not in _STOPWORDS and len(t) > 2}
        return ta & tb

    def _detect_contradiction(self, fact, new_value, new_message=None):
        if fact.get("category") == "emotional_history":
            return False
        old_value = str(fact.get("value", ""))
        old_message = str(fact.get("source_history", [{}])[-1].get("text") or "")
        new_value = str(new_value or "")
        new_message = str(new_message or "")
        if not old_value or not new_value:
            return False
        old_pol = self._polarity(old_value)
        new_pol = self._polarity(new_value)
        used_message = False
        if old_pol == 0 and old_message and old_message != old_value:
            old_pol = self._polarity(old_message)
            used_message = True
        if new_pol == 0 and new_message and new_message != new_value:
            new_pol = self._polarity(new_message)
            used_message = True
        if old_pol == 0 or new_pol == 0 or old_pol == new_pol:
            return False
        if used_message:
            return bool(self._shared_tokens(old_message, new_message))
        return bool(self._shared_tokens(old_value, new_value))

    def _confirmation_question(self, old_value, old_message=None):
        text = (old_message or old_value or "").strip().lower()
        if not text:
            return "Earlier you mentioned something about this. Has your view changed?"
        if text.startswith("my "):
            text = text[3:]
        for prefix in ("i'm ", "im ", "i am ", "i "):
            if text.startswith(prefix):
                text = text[len(prefix):]
                break
        words = text.split()
        gerunds = {"love": "loving", "loves": "loving", "like": "liking",
                   "likes": "liking", "enjoy": "enjoying", "enjoys": "enjoying",
                   "hate": "hating", "hates": "hating", "dislike": "disliking",
                   "dislikes": "disliking", "prefer": "preferring", "prefers": "preferring"}
        if words and words[0] in gerunds:
            words[0] = gerunds[words[0]]
        return f"Earlier you mentioned {(' '.join(words))}. Has something changed?"

    def _handle_contradiction(self, fact, new_value, source, message=None):
        old_value = fact.get("value", "")
        old_message = fact.get("source_history", [{}])[-1].get("text") or old_value
        fact["needs_confirmation"] = True
        fact["contradicts"] = True
        hist = fact.setdefault("source_history", [])
        hist.append({"source": source, "text": message or new_value, "at": now_iso(),
                     "contradiction": True})
        fact["source_history"] = hist[-8:]
        pending = self.memory.setdefault("_pending_confirmations", [])
        for p in pending:
            if p.get("fact_key") == fact["key"] and not p.get("resolved"):
                p["new_value"] = new_value
                p["new_message"] = message or new_value
                p["updated_at"] = now_iso()
                self.save()
                return {"action": "contradiction", "fact": fact}
        pending.append({
            "fact_key": fact["key"],
            "old_value": old_value,
            "new_value": new_value,
            "old_message": old_message,
            "new_message": message or new_value,
            "question": self._confirmation_question(old_value, old_message),
            "created_at": now_iso(),
            "asked": False,
            "resolved": False
        })
        self.save()
        return {"action": "contradiction", "fact": fact}

    def get_pending_confirmation(self):
        for p in self.memory.get("_pending_confirmations", []):
            if not p.get("resolved"):
                return p
        return None

    def mark_confirmation_asked(self):
        p = self.get_pending_confirmation()
        if p and not p.get("asked"):
            p["asked"] = True
            self.save()

    def resolve_pending_confirmation(self, accept=True):
        for p in self.memory.get("_pending_confirmations", []):
            if p.get("fact_key") and not p.get("resolved"):
                fact = self.get_fact(p["fact_key"])
                if accept and fact:
                    if str(fact.get("value", "")) != str(p["new_value"]):
                        prev = fact.setdefault("previous_values", [])
                        prev.append(fact.get("value", ""))
                        fact["previous_values"] = prev[-3:]
                        fact["value"] = p["new_value"]
                    fact["confidence"] = min(95, max(fact.get("confidence", 60), 70) + 10)
                    fact["evidence_count"] = fact.get("evidence_count", 1) + 1
                    fact["last_confirmed"] = now_iso()
                    fact["needs_confirmation"] = False
                    fact["contradicts"] = False
                    hist = fact.setdefault("source_history", [])
                    hist.append({"source": "confirmation", "text": p["new_message"],
                                 "at": now_iso(), "confirmed": True})
                    fact["source_history"] = hist[-8:]
                elif fact:
                    fact["needs_confirmation"] = False
                    fact["contradicts"] = False
                    hist = fact.setdefault("source_history", [])
                    hist.append({"source": "confirmation", "text": p["new_message"],
                                 "at": now_iso(), "rejected": True})
                    fact["source_history"] = hist[-8:]
                p["resolved"] = True
                p["resolved_at"] = now_iso()
                self.save()
                return {"accepted": accept, "fact": fact,
                        "old_value": p["old_value"], "new_value": p["new_value"]}
        return None

    # ─── Decay ────────────────────────────────────────────────

    def _apply_decay(self):
        for fact in self.memory["facts"]:
            if fact.get("evidence_count", 1) >= 3:
                continue
            created = fact.get("created_at") or fact.get("last_updated")
            confirmed = fact.get("last_confirmed")
            try:
                created_days = days_since(created) if created else 0
                confirmed_days = days_since(confirmed) if confirmed else None
            except Exception:
                created_days = 0
                confirmed_days = None
            if created_days >= 30:
                fact["importance"] = max(10, fact.get("importance", 40) - 10)
            if created_days >= 14 and not confirmed:
                fact["confidence"] = max(35, fact.get("confidence", 60) - 10)
                fact["needs_confirmation"] = True
            elif created_days >= 7 and not confirmed:
                fact["importance"] = max(15, fact.get("importance", 40) - 5)
            if confirmed_days is not None and confirmed_days >= 14:
                fact["confidence"] = max(40, fact.get("confidence", 60) - 5)
        self._expire_pending()

    def _expire_pending(self):
        keep = []
        for p in self.memory.get("_pending_confirmations", []):
            try:
                stale = days_since(p.get("created_at", "")) >= 3
            except Exception:
                stale = False
            if not stale:
                keep.append(p)
        self.memory["_pending_confirmations"] = keep

    def get_fact(self, key):
        for fact in self.memory["facts"]:
            if fact["key"] == key:
                return fact
        return None

    def get_facts_by_category(self, category):
        return [f for f in self.memory["facts"] if f["category"] == category]

    def get_facts_by_pillar(self, pillar):
        return [f for f in self.memory["facts"] if pillar in f["key"] or pillar in f.get("tags", [])]

    def get_all_facts(self):
        return self.memory["facts"]

    def get_pillar_coverage(self):
        return self.memory.get("pillar_coverage", {})

    def _update_pillar_coverage(self, key, confidence):
        from .config import PILLARS
        for pillar in PILLARS:
            if pillar in key:
                coverage = self.memory.setdefault("pillar_coverage", {})
                if pillar not in coverage:
                    coverage[pillar] = {"confidence": 0, "last_updated": None, "fact_count": 0}
                coverage[pillar]["fact_count"] = coverage[pillar].get("fact_count", 0) + 1
                coverage[pillar]["confidence"] = max(coverage[pillar]["confidence"], confidence)
                coverage[pillar]["last_updated"] = now_iso()
                break

    def get_known_pillars(self):
        coverage = self.get_pillar_coverage()
        return {p: v for p, v in coverage.items() if v.get("fact_count", 0) > 0}

    def get_unknown_pillars(self):
        known = self.get_known_pillars()
        from .config import PILLARS
        return [p for p in PILLARS if p not in known]

    def get_pillar_recency(self, pillar):
        coverage = self.get_pillar_coverage()
        if pillar in coverage and coverage[pillar].get("last_updated"):
            return days_since(coverage[pillar]["last_updated"])
        return 999

    def get_trust_score(self):
        return self.memory.get("trust_score", 30)

    def adjust_trust_score(self, delta):
        self.memory["trust_score"] = max(0, min(100, self.memory.get("trust_score", 30) + delta))
        self.save()

    def mark_avoided_pillar(self, pillar):
        avoided = self.memory.setdefault("avoided_pillars", {})
        avoided[pillar] = avoided.get(pillar, 0) + 1
        if avoided[pillar] >= 2:
            if pillar not in self.memory.setdefault("deprioritized_pillars", []):
                self.memory["deprioritized_pillars"].append(pillar)
        self.save()

    def get_avoided_pillars(self):
        return self.memory.get("avoided_pillars", {})

    def get_deprioritized_pillars(self):
        return self.memory.get("deprioritized_pillars", [])

    def get_emotional_history(self, limit=10):
        facts = self.get_facts_by_category("emotional_history")
        return sorted(facts, key=lambda f: f.get("last_updated", ""), reverse=True)[:limit]

    def get_habit_trends(self):
        habits = self.get_facts_by_category("habits")
        trends = {}
        for h in habits:
            key_base = h["key"].split("_trend")[0] if "_trend" in h["key"] else h["key"]
            if key_base not in trends:
                trends[key_base] = []
            trends[key_base].append(h)
        return trends

    def extract_facts_from_message(self, message):
        extracted = []
        message_lower = message.lower()

        sleep_patterns = [
            ("sleep_hours", r'(\d+(?:\.\d+)?)\s*(?:hours?|hrs?)\s*(?:of\s*)?sleep', 80),
            ("sleep_quality", r'sleep\s*(?:quality|was|is)\s*(bad|poor|terrible|okay|good|great|amazing)', 70),
            ("bedtime", r'(?:went to|hit the|to)\s*bed\s*(?:at\s*)?(\d+\s*(?::\d{2})\s*(?:am|pm)?)', 60),
        ]

        for key, pattern, conf in sleep_patterns:
            match = re.search(pattern, message_lower)
            if match:
                value = match.group(1) if match.groups() else "mentioned"
                extracted.append(("habits", key, value, conf))

        mood_patterns = [
            (r"\b(i'm?\s*(?:feeling|feel)\s*(sad|depressed|down|unhappy|miserable))\b", "mood_state", 75),
            (r"\b(i'm?\s*(?:feeling|feel)\s*(anxious|worried|nervous|stressed))\b", "mood_state", 75),
            (r"\b(i'm?\s*(?:feeling|feel)\s*(happy|good|great|okay|fine))\b", "mood_state", 60),
            (r"\b(i'm?\s*(?:feeling|feel)\s*(lonely|alone))\b", "mood_state", 75),
            (r"\b(i'm?\s*(?:feeling|feel)\s*(tired|exhausted|drained))\b", "mood_state", 65),
        ]

        for pattern, key, conf in mood_patterns:
            match = re.search(pattern, message_lower)
            if match:
                value = match.group(1)
                extracted.append(("emotional_history", key, value, conf))
                break

        work_patterns = [
            (r"\b(work|job|career)\s*(is|has been)\s*(stressful|busy|hectic|overwhelming)\b", "work_stress", 75),
            (r"\b(deadlines?|overwork|burnout)\b", "work_stress", 80),
        ]
        for pattern, key, conf in work_patterns:
            if re.search(pattern, message_lower):
                extracted.append(("emotional_history", key, "high", conf))
                break

        if "exercise" in message_lower or "workout" in message_lower or "gym" in message_lower:
            nums = re.findall(r'\b(\d+)\s*(?:times?|days?|x)\b', message_lower)
            value = f"{nums[0]}x/week" if nums else "mentioned"
            extracted.append(("habits", "exercise_frequency", value, 65))

        if "eat" in message_lower or "food" in message_lower or "diet" in message_lower or "meal" in message_lower:
            extracted.append(("habits", "nutrition_mentioned", "true", 50))

        if "stress" in message_lower or "stressed" in message_lower:
            extracted.append(("emotional_history", "stress_level", "elevated", 70))

        return extracted

    def get_session_summary(self):
        return {
            "user_id": self.user_id,
            "trust_score": self.get_trust_score(),
            "facts_count": len(self.memory["facts"]),
            "known_pillars": list(self.get_known_pillars().keys()),
            "unknown_pillars": self.get_unknown_pillars(),
            "session_count": self.memory.get("session_count", 0),
            "last_updated": self.memory.get("last_updated", "")
        }

    def increment_session(self):
        self.memory["session_count"] = self.memory.get("session_count", 0) + 1
        self.save()
