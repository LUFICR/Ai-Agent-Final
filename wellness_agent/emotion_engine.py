import re
from .utils.nlp_utils import (
    extract_emotion_keywords, detect_avoidance, detect_risk,
    compute_sentiment
)


class EmotionEngine:
    def __init__(self, memory_system=None):
        self.memory = memory_system

    def analyze(self, message, recent_context=None):
        text = message or ""
        keyword_scores = extract_emotion_keywords(text)
        avoidance = detect_avoidance(text)
        risk_flag, risk_reason = detect_risk(text)
        sentiment = compute_sentiment(text)

        primary, secondary = self._determine_emotions(keyword_scores, sentiment)
        intensity = self._compute_intensity(keyword_scores)
        confidence = self._compute_confidence(keyword_scores, text)

        stress = self._score_dimension(text, keyword_scores, "stressed", 0.6)
        motivation = self._inverse_from_avoidance(avoidance, sentiment)
        hope = max(0, int((sentiment * 70) + (motivation * 0.3)))
        energy = self._compute_energy(keyword_scores, sentiment)
        engagement = self._compute_engagement(text, avoidance)
        trust = self._compute_trust(text, avoidance, sentiment)
        loneliness = self._score_dimension(text, keyword_scores, "lonely", 0.8)
        frustration = self._score_dimension(text, keyword_scores, "angry", 0.7)
        burnout = self._score_dimension(text, keyword_scores, "tired", 0.5)
        anxiety = self._score_dimension(text, keyword_scores, "anxious", 0.75)

        depression_risk = self._compute_depression_risk(keyword_scores, sentiment, text)
        self_esteem = self._compute_self_esteem(sentiment, keyword_scores)

        result = {
            "primary_emotion": primary,
            "secondary_emotion": secondary,
            "emotional_intensity": intensity,
            "confidence": confidence,
            "avoidance": avoidance * 100 if isinstance(avoidance, bool) else avoidance,
            "stress": stress,
            "motivation": motivation,
            "hope": hope,
            "energy": energy,
            "engagement": engagement,
            "trust": trust,
            "loneliness": loneliness,
            "frustration": frustration,
            "burnout": burnout,
            "anxiety": anxiety,
            "depression_risk": depression_risk,
            "self_esteem": self_esteem,
            "risk_flag": risk_flag,
            "risk_reason": risk_reason
        }

        if self.memory:
            self._update_memory_from_emotion(result)

        return result

    def _determine_emotions(self, keyword_scores, sentiment):
        sorted_scores = sorted(keyword_scores.items(), key=lambda x: x[1], reverse=True)
        top = [e for e, s in sorted_scores if s > 0]

        if not top:
            if sentiment > 0.6:
                return "content", "neutral"
            elif sentiment < 0.4:
                return "neutral", "neutral"
            return "neutral", "neutral"

        primary = top[0]
        secondary = top[1] if len(top) > 1 else "neutral"
        return primary, secondary

    def _compute_intensity(self, keyword_scores):
        total = sum(keyword_scores.values())
        return min(100, int(total * 20))

    def _compute_confidence(self, keyword_scores, text):
        word_count = len(text.split())
        total = sum(keyword_scores.values())
        if word_count < 3:
            return 30
        if total == 0:
            return 40
        base = min(95, int((total / max(1, word_count)) * 100 + 30))
        return min(95, base)

    def _score_dimension(self, text, keyword_scores, keyword_key, weight):
        base = keyword_scores.get(keyword_key, 0) * 25
        return min(100, int(base * weight + 10))

    def _inverse_from_avoidance(self, avoidance, sentiment):
        if avoidance:
            return max(10, int(50 - (sentiment * 20)))
        return min(90, int(sentiment * 70 + 20))

    def _compute_energy(self, keyword_scores, sentiment):
        tired = keyword_scores.get("tired", 0)
        sad = keyword_scores.get("sad", 0)
        drain = (tired * 25 + sad * 15)
        return max(5, min(95, int(sentiment * 60 + 20 - drain * 0.3)))

    def _compute_engagement(self, text, avoidance):
        word_count = len(text.split())
        if avoidance:
            return max(10, 50 - word_count * 5)
        if word_count > 20:
            return 85
        if word_count > 10:
            return 65
        return 40

    def _compute_trust(self, text, avoidance, sentiment):
        word_count = len(text.split())
        base = int(sentiment * 30 + 30)
        if avoidance:
            base -= 20
        if word_count > 15:
            base += 15
        return max(10, min(95, base))

    def _compute_depression_risk(self, keyword_scores, sentiment, text):
        sad = keyword_scores.get("sad", 0)
        tired = keyword_scores.get("tired", 0)
        lonely = keyword_scores.get("lonely", 0)

        combined = (sad * 30 + lonely * 25 + tired * 10)
        if sentiment < 0.3:
            combined += 15
        if sentiment < 0.2:
            combined += 10

        if re.search(r'\b(hopeless|worthless|nobody cares|no one cares|empty|numb)\b', text.lower()):
            combined += 20

        return min(90, int(combined))

    def _compute_self_esteem(self, sentiment, keyword_scores):
        base = int(sentiment * 60 + 20)
        sad = keyword_scores.get("sad", 0)
        lonely = keyword_scores.get("lonely", 0)
        base -= (sad * 5 + lonely * 5)
        return max(5, min(95, base))

    def _update_memory_from_emotion(self, result):
        if not self.memory:
            return
        if result["risk_flag"]:
            return

        if result["primary_emotion"] != "neutral":
            self.memory.add_fact(
                category="emotional_history",
                key=f"emotion_{result['primary_emotion']}",
                value=result["primary_emotion"],
                confidence=result["confidence"],
                source="conversation"
            )

        if result["stress"] > 70:
            self.memory.add_fact(
                category="emotional_history",
                key="stress_level",
                value=f"high_{result['stress']}",
                confidence=min(90, result["confidence"]),
                source="conversation"
            )
