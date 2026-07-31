import re


class ConversationPlanner:
    def __init__(self, memory_system=None):
        self.memory = memory_system

    def select_target_pillar(self, known_pillars=None, unknown_pillars=None,
                             current_state=None, latest_emotion_scores=None,
                             user_message=None):
        if known_pillars is None and self.memory:
            known_pillars = self.memory.get_known_pillars()
        if unknown_pillars is None and self.memory:
            unknown_pillars = self.memory.get_unknown_pillars()

        known_pillars = known_pillars or {}
        unknown_pillars = unknown_pillars or []
        emotion_scores = latest_emotion_scores or {}

        deprioritized = self.memory.get_deprioritized_pillars() if self.memory else []

        if current_state in ("deep_investigation", "insight_generation", "routine_planning"):
            current_pillar = getattr(self.memory, "selected_pillar", None)
            if current_pillar:
                return {"target_pillar": current_pillar, "reason": "Continuing current investigation", "urgency": "normal"}

        context_pillar = self._detect_context_pillar(user_message, deprioritized)
        if context_pillar:
            return context_pillar

        spike_pillar = self._detect_emotion_spike(emotion_scores, deprioritized)
        if spike_pillar:
            return spike_pillar

        stale_pillar = self._find_stale_pillar(known_pillars, deprioritized)
        if stale_pillar:
            return stale_pillar

        unknown_filtered = [p for p in unknown_pillars if p not in deprioritized]
        if unknown_filtered:
            pillar = unknown_filtered[0]
            return {"target_pillar": pillar, "reason": f"Uncovered pillar: {pillar}", "urgency": "normal"}

        known_filtered = {p: v for p, v in known_pillars.items() if p not in deprioritized}
        if known_filtered:
            lowest_conf = min(known_filtered.items(), key=lambda x: x[1].get("confidence", 0))
            return {"target_pillar": lowest_conf[0], "reason": f"Lowest confidence known pillar: {lowest_conf[0]}", "urgency": "low"}

        return {"target_pillar": "mood", "reason": "Default pillar - mood", "urgency": "low"}

    def _detect_context_pillar(self, user_message, deprioritized):
        if not user_message:
            return None
        pillar_map = {
            "sleep": [r"\bsleep\b", r"\binsomnia\b", r"\bbed\b", r"\btired\b", r"\brest\b", r"\bnightmare\b", r"\bcant sleep\b"],
            "stress": [r"\bstress\b", r"\bstressed\b", r"\boverwhelm\b", r"\bpressure\b", r"\bdrowning\b", r"\bdeadline\b"],
            "relationships": [r"\brelationship\b", r"\bfriend\b", r"\bpartner\b", r"\bspouse\b", r"\bfamily\b", r"\balone\b", r"\blonely\b"],
            "exercise": [r"\bexercise\b", r"\bworkout\b", r"\bgym\b", r"\bwalk(?:ing|ed)?\b", r"\brun(?:ning|s)?\b", r"\byoga\b", r"\bfitness\b"],
            "work": [r"\bwork\b", r"\bjob\b", r"\bcareer\b", r"\bboss\b", r"\bcoworker\b", r"\bdeadline\b", r"\boffice\b", r"\bcolleague\b"],
            "mood": [r"\bmood\b", r"\bfeel(?:ing|s)?\b", r"\bsad\b", r"\bhappy\b", r"\bemotion\b", r"\bdown\b", r"\bdepressed\b", r"\bflat\b"],
            "motivation": [r"\bmotivation\b", r"\bmotivated\b", r"\bdrive\b", r"\bgoal\b", r"\bprocrastinate\b", r"\bfocus\b", r"\bproductive\b"],
            "routine": [r"\broutine\b", r"\bhabit\b", r"\bschedule\b", r"\bmorning\b", r"\bevening\b", r"\bdaily\b"],
            "nutrition": [r"\bnutrition\b", r"\beat(?:ing|s)?\b", r"\bfood\b", r"\bdiet\b", r"\bmeal\b", r"\bhungry\b", r"\bweight\b"],
            "finances": [r"\bfinance\b", r"\bmoney\b", r"\bbudget\b", r"\bdebt\b", r"\bspend(?:ing|s)?\b", r"\bincome\b", r"\bbill\b", r"\bpayment\b"],
        }
        for pillar, patterns in pillar_map.items():
            if pillar in deprioritized:
                continue
            for pat in patterns:
                if re.search(pat, user_message, re.IGNORECASE):
                    return {"target_pillar": pillar, "reason": f"Context match: '{pat}'", "urgency": "high"}
        return None

    def _detect_emotion_spike(self, emotion_scores, deprioritized):
        spikes = {
            "stress": ("stress", 70, "work"),
            "anxiety": ("anxiety", 65, "stress"),
            "loneliness": ("loneliness", 60, "relationships"),
            "burnout": ("burnout", 60, "work"),
            "frustration": ("frustration", 65, "work"),
            "low_energy": ("energy", 25, "mood"),
            "low_motivation": ("motivation", 25, "mood"),
            "poor_sleep_signal": ("emotional_intensity", 70, "sleep"),
        }

        for spike_name, (dim, threshold, pillar) in spikes.items():
            if pillar in deprioritized:
                continue
            if dim in emotion_scores:
                score = emotion_scores[dim]
                if isinstance(score, (int, float)) and (
                    (score > threshold) or
                    (dim in ("energy", "motivation", "self_esteem") and score < threshold)
                ):
                    return {"target_pillar": pillar, "reason": f"Emotion spike detected: {dim}={score}", "urgency": "high"}

        return None

    def _find_stale_pillar(self, known_pillars, deprioritized):
        from .utils.storage import days_since

        stalest = None
        stalest_days = 0

        for pillar, info in known_pillars.items():
            if pillar in deprioritized:
                continue
            last_update = info.get("last_updated")
            if last_update:
                days = days_since(last_update)
                if days > stalest_days and days > 3:
                    stalest = pillar
                    stalest_days = days

        if stalest:
            return {"target_pillar": stalest, "reason": f"Stale data ({stalest_days}d old)", "urgency": "normal"}
        return None
