"""Per-user Learning Layer — experience accumulation without model retraining.

After every completed live conversation the layer updates, for THAT user only:

  - behavior confidence     (calibrate trait confidence from observed activity)
  - hypotheses              (evidence counts and confirmed/contradicted outcomes)
  - intervention success    (per-topic success/failure)
  - conversation style      (openness, directness, emotionality, message length)
  - coaching style          (which coaching states work for this user)
  - objective success       (per-objective completion)
  - pattern confidence      (validated patterns driving fact retrieval)

Privacy: every profile lives in its own per-user file; the layer never reads or
writes another user's data and never aggregates across users.

It improves runtime behavior only through deterministic per-user signals:

  - objective selection    -> objective_boosts()   (learned success rates)
  - intervention ranking   -> intervention_weights (learned topic success)
  - retrieval              -> reorder_facts()      (learned-important topics first)
  - behavior profile       -> behavior_confidences (calibrated trait confidence)
  - confidence             -> confirmed_hypotheses (evidence-backed hypothesis boosts)
  - pattern detection      -> pattern_confidence() (validated hypothesis topics)

All runtime helpers are no-ops for a fresh profile, so a user with no completed
conversations behaves exactly as before.
"""

from .config import get_data_dir
from .utils.storage import load_json, save_json, now_iso

MIN_TURNS_TO_LEARN = 2
HYPOTHESIS_BOOST_EVIDENCE = 3
TOPIC_KEYWORDS = {
    "sleep": ["sleep", "insomnia", "rest", "tired", "fatigue", "bedtime"],
    "stress": ["stress", "overwhelm", "anxiety", "calm", "relax", "tense", "grounding"],
    "work": ["work", "job", "career", "burnout", "overwork", "deadline", "productivity", "focus"],
    "exercise": ["exercise", "workout", "gym", "fitness", "movement", "walk", "stretch"],
    "mood": ["mood", "emotion", "sad", "happy", "positive", "gratitude"],
    "motivation": ["motivation", "drive", "goal", "purpose", "energy", "momentum"],
    "relationships": ["relation", "social", "friend", "family", "connect", "lonely"],
    "routine": ["routine", "schedule", "plan", "habit", "morning"],
    "nutrition": ["nutrition", "eat", "food", "diet", "meal", "water"],
    "meditation": ["meditation", "mindfulness", "breathe", "present", "quiet"],
}


def match_topic(text):
    """Best-matching topic keyword group for a text (empty string if none)."""
    lowered = (text or "").lower()
    best, best_hits = "", 0
    for topic, kws in TOPIC_KEYWORDS.items():
        hits = sum(1 for kw in kws if kw in lowered)
        if hits > best_hits:
            best, best_hits = topic, hits
    return best if best_hits else ""


def _ema(old, new, samples):
    """Exponential moving average: new sample weighted 0.3, growing more stable."""
    if old is None:
        return round(new, 4)
    alpha = max(0.15, 0.3 / (1 + samples * 0.1))
    return round(alpha * new + (1 - alpha) * old, 4)

def _clamp(v, lo=5, hi=95):
    return max(lo, min(hi, v))


class LearningLayer:
    """Per-user learning store. Never aggregates across users."""

    def __init__(self, user_id="default"):
        self.user_id = user_id
        self.path = get_data_dir("learning") / f"{user_id}_learning.json"
        self.store = self._load()

    # ─── Storage ───────────────────────────────────────────────

    def _load(self):
        data = load_json(self.path)
        if not data:
            data = {"user_id": self.user_id, "conversations_learned": 0}
        return data

    def _save(self):
        self.store["last_updated"] = now_iso()
        save_json(self.path, self.store)

    def profile(self):
        """Read-only view of this user's learning profile (never shared)."""
        p = dict(self.store)
        p["user_id"] = self.user_id
        return p

    # ─── Conversation-end learning ────────────────────────────

    def record_conversation(self, turns=None, memory_facts=None, traits=None,
                            hypotheses=None, objective_track=None,
                            judge_result=None, reasoning_context=None):
        """Update this user's learning profile from one completed conversation.

        All inputs are per-user engine outputs; nothing here reads other users.
        Returns a summary of what was updated.
        """
        turns = turns or []
        if len(turns) < MIN_TURNS_TO_LEARN:
            return {"skipped": "too short to learn from"}
        judge = judge_result or {}
        dims = judge.get("dims") or {}
        objective_completed = (dims.get("objective_completion", 0) or 0) >= 60
        updates = {"objective_completed": bool(objective_completed), "turns": len(turns)}

        updates["behavior_confidences"] = self._update_behaviors(traits or {})
        updates["hypotheses"] = self._update_hypotheses(hypotheses or {})
        updates["interventions"] = self._update_interventions(
            objective_completed, reasoning_context or {})
        updates["conversation_style"] = self._update_style(turns)
        updates["coaching_style"] = self._update_coaching(turns, objective_completed)
        updates["objective_success"] = self._update_objectives(objective_track or {})

        self.store["conversations_learned"] = self.store.get("conversations_learned", 0) + 1
        self._save()
        return updates

    def _update_behaviors(self, traits):
        active = [t for t, e in traits.items()
                  if e.get("status") == "active" and e.get("confidence", 0) >= 60]
        profile = self.store.setdefault("behavior_confidences", {})
        for t in active:
            base = traits[t].get("confidence", 60)
            entry = profile.get(t, {"confidence": base, "samples": 0})
            conf = _clamp(round(0.7 * entry.get("confidence", base) + 0.3 * base))
            profile[t] = {"confidence": conf, "samples": entry.get("samples", 0) + 1}
        for t in list(profile):
            if t not in active and profile[t].get("samples", 0) >= 3:
                profile[t] = {"confidence": _clamp(profile[t]["confidence"] - 5),
                              "samples": profile[t]["samples"] + 1}
        return dict(profile)

    def _update_hypotheses(self, hypotheses):
        profile = self.store.setdefault("hypotheses", {})
        for name, entry in hypotheses.items():
            conf = entry.get("confidence", 0)
            hp = profile.get(name, {"confidence": conf, "evidence_count": 0, "outcomes": []})
            if entry.get("status") == "active" and conf >= 50:
                hp["evidence_count"] = hp.get("evidence_count", 0) + 1
                hp["confidence"] = _clamp(round(0.7 * hp.get("confidence", conf) + 0.3 * conf))
                hp["outcomes"] = (hp.get("outcomes", []) + ["confirmed"])[-12:]
            elif entry.get("status") == "rejected":
                hp["evidence_count"] = max(0, hp.get("evidence_count", 0) - 1)
                hp["confidence"] = _clamp(hp.get("confidence", conf) - 10)
                hp["outcomes"] = (hp.get("outcomes", []) + ["contradicted"])[-12:]
            else:
                hp["confidence"] = _clamp(hp.get("confidence", conf) - 3)
            profile[name] = hp
        return dict(profile)

    def _update_interventions(self, objective_completed, reasoning_context):
        profile = self.store.setdefault("intervention_success", {})
        rec = (reasoning_context or {}).get("recommended_intervention") or {}
        action = (rec.get("action") or "") + " " + (rec.get("topic") or "")
        topic = match_topic(action)
        if not topic:
            pillar = (reasoning_context or {}).get("conversation_mode") or ""
            topic = match_topic(pillar)
        if not topic:
            return dict(profile)
        entry = profile.setdefault(topic, {"successes": 0, "failures": 0})
        if objective_completed:
            entry["successes"] += 1
        else:
            entry["failures"] += 1
        return dict(profile)

    def _update_style(self, turns):
        style = self.store.setdefault("conversation_style", {})
        samples = style.get("samples", 0)
        lengths, intensities = [], []
        for t in turns:
            text = str(t.get("user_message") or t.get("user") or "")
            lengths.append(len(text.split()))
            emo = t.get("emotion_summary") or t.get("emotion") or {}
            if isinstance(emo, dict):
                intensity = emo.get("intensity")
                if intensity is None:
                    intensity = emo.get("emotional_intensity")
            else:
                intensity = None
            if isinstance(intensity, (int, float)):
                intensities.append(intensity)
        if not lengths:
            return dict(style)
        avg_words = sum(lengths) / len(lengths)
        openness = sum(1 for i in intensities if i >= 40) / max(1, len(intensities))
        directness = sum(1 for w in lengths if w <= 12) / len(lengths)
        emotionality = (sum(intensities) / max(1, len(intensities))) / 100 if intensities else 0.0
        style["avg_message_words"] = _ema(style.get("avg_message_words"), avg_words, samples)
        style["openness"] = _ema(style.get("openness"), openness, samples)
        style["directness"] = _ema(style.get("directness"), directness, samples)
        style["emotionality"] = _ema(style.get("emotionality"), emotionality, samples)
        style["samples"] = samples + 1
        return dict(style)

    def _update_coaching(self, turns, objective_completed):
        profile = self.store.setdefault("coaching_style", {})
        states = set()
        for t in turns:
            st = t.get("state")
            if isinstance(st, dict):
                st = st.get("current_state")
            if st:
                states.add(st)
        for st in states:
            entry = profile.setdefault(st, {"successes": 0, "failures": 0})
            if objective_completed:
                entry["successes"] += 1
            else:
                entry["failures"] += 1
        return dict(profile)

    def _update_objectives(self, objective_track):
        profile = self.store.setdefault("objective_success", {})
        for name, info in objective_track.items():
            attempts = info.get("attempts", 0)
            successes = info.get("successes", 0)
            if not attempts:
                continue
            entry = profile.setdefault(name, {"successes": 0, "failures": 0})
            entry["successes"] = max(entry["successes"], successes)
            entry["failures"] = max(entry["failures"], attempts - successes)
        return dict(profile)

    # ─── Runtime improvement signals (empty-profile no-ops) ───

    def objective_boosts(self):
        """{objective: priority boost} from learned success rates.

        Mirrors ObjectiveEngine history logic; empty for a fresh profile.
        """
        boosts = {}
        for name, entry in (self.store.get("objective_success") or {}).items():
            attempts = entry.get("successes", 0) + entry.get("failures", 0)
            if attempts < 2:
                continue
            rate = entry["successes"] / attempts
            boost = round((rate - 0.5) * 16)
            if boost:
                boosts[name] = boost
        return boosts

    def intervention_weights(self):
        """{topic: multiplier 0.75–1.25} from learned topic success rates."""
        weights = {}
        for topic, entry in (self.store.get("intervention_success") or {}).items():
            total = entry.get("successes", 0) + entry.get("failures", 0)
            if total < 2:
                continue
            rate = entry["successes"] / total
            weight = round(1 + (rate - 0.5) * 0.5, 3)
            weights[topic] = max(0.75, min(1.25, weight))
        return weights

    def reorder_facts(self, facts):
        """Retrieval improvement: facts on learned-high-value topics first.

        Stable reorder — nothing is dropped, empty profile returns input as-is.
        """
        if not facts:
            return list(facts or [])
        weights = self.intervention_weights()
        confidences = self.pattern_confidence()
        if not weights and not confidences:
            return list(facts)

        def topic_score(f):
            if not isinstance(f, dict):
                return 0.0
            text = f"{f.get('key', '')} {f.get('value', '')}"
            topic = match_topic(text)
            score = weights.get(topic, 1.0) - 1.0
            for pattern, pconf in confidences.items():
                if match_topic(pattern) == topic and pconf >= 55:
                    score += 0.15
            return score

        scored = [(topic_score(f), idx, f) for idx, f in enumerate(facts)]
        scored.sort(key=lambda x: (-x[0], x[1]))
        return [f for _, _, f in scored]

    def behavior_confidences(self):
        """Calibrated per-trait confidence for the behavior profile."""
        return {k: v.get("confidence", 60)
                for k, v in (self.store.get("behavior_confidences") or {}).items()}

    def confirmed_hypotheses(self, min_evidence=HYPOTHESIS_BOOST_EVIDENCE):
        """Hypothesis names with enough confirmed evidence to trust more."""
        return sorted(
            name for name, hp in (self.store.get("hypotheses") or {}).items()
            if hp.get("evidence_count", 0) >= min_evidence
        )

    def pattern_confidence(self):
        """{pattern topic: confidence} — validated patterns, for retrieval."""
        patterns = {}
        for name, hp in (self.store.get("hypotheses") or {}).items():
            topic = match_topic(name)
            if topic and hp.get("outcomes", []) and hp["outcomes"][-1] == "confirmed":
                patterns[topic] = max(patterns.get(topic, 0),
                                      hp.get("confidence", 50))
        return patterns

    def conversation_style(self):
        return dict(self.store.get("conversation_style") or {})

    def coaching_style(self):
        return {k: dict(v) for k, v in (self.store.get("coaching_style") or {}).items()}

    def learning_active(self):
        """True once this user has completed at least one conversation."""
        return self.store.get("conversations_learned", 0) > 0
