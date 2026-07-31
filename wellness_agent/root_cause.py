class RootCauseAnalyzer:
    def __init__(self, memory_system=None):
        self.memory = memory_system

    def analyze(self, pillar, memory_facts=None, emotion_history=None, habit_trends=None):
        memory_facts = memory_facts or []
        emotion_history = emotion_history or []
        habit_trends = habit_trends or {}

        chain = self._build_chain(pillar, memory_facts, emotion_history, habit_trends)
        likely_cause, probability = self._determine_root_cause(pillar, chain, emotion_history)
        caveat = "Correlational, based on self-reported data — not a diagnosis."

        return {
            "chain": chain,
            "likely_root_cause": likely_cause,
            "probability": probability,
            "caveat": caveat
        }

    def _build_chain(self, pillar, memory_facts, emotion_history, habit_trends):
        chain = []
        pillar_map = {
            "sleep": self._build_sleep_chain,
            "stress": self._build_stress_chain,
            "relationships": self._build_relationship_chain,
            "exercise": self._build_exercise_chain,
            "work": self._build_work_chain,
            "mood": self._build_mood_chain,
            "motivation": self._build_motivation_chain,
            "routine": self._build_routine_chain,
            "nutrition": self._build_nutrition_chain,
        }

        builder = pillar_map.get(pillar, self._build_generic_chain)
        chain = builder(memory_facts, emotion_history, habit_trends)

        chain.sort(key=lambda x: x.get("confidence", 50), reverse=True)
        return chain

    def _build_sleep_chain(self, facts, emotions, habits):
        chain = []
        for f in facts:
            if "sleep" in f.get("key", ""):
                chain.append({"observation": f"Sleep: {f.get('value', 'mentioned')}", "confidence": f.get("confidence", 60)})

        stress_high = any(e.get("stress", 0) > 65 for e in emotions[-5:] if isinstance(e, dict))
        if stress_high:
            chain.append({"observation": "Elevated stress correlating with sleep issues", "confidence": 75})

        anxiety_high = any(e.get("anxiety", 0) > 60 for e in emotions[-5:] if isinstance(e, dict))
        if anxiety_high:
            chain.append({"observation": "Anxiety may be interfering with sleep onset or quality", "confidence": 70})

        energy_low = any(e.get("energy", 50) < 30 for e in emotions[-5:] if isinstance(e, dict))
        if energy_low:
            chain.append({"observation": "Low daytime energy consistent with poor sleep", "confidence": 65})

        if not chain:
            chain.append({"observation": "Limited sleep data collected", "confidence": 40})
        return chain

    def _build_stress_chain(self, facts, emotions, habits):
        chain = []
        for f in facts:
            if "stress" in f.get("key", ""):
                chain.append({"observation": f"Stress indicator: {f.get('value', 'elevated')}", "confidence": f.get("confidence", 60)})

        recent_stress = [e.get("stress", 0) for e in emotions[-7:] if isinstance(e, dict)]
        if recent_stress:
            avg_stress = sum(recent_stress) / len(recent_stress)
            if avg_stress > 60:
                chain.append({"observation": f"Consistently elevated stress (avg {avg_stress:.0f}/100)", "confidence": 80})

        if not chain:
            chain.append({"observation": "Limited stress data collected", "confidence": 40})
        return chain

    def _build_relationship_chain(self, facts, emotions, habits):
        chain = []
        for f in facts:
            if "relation" in f.get("key", "") or "lonely" in f.get("key", ""):
                chain.append({"observation": f"Relationship signal: {f.get('value', 'mentioned')}", "confidence": f.get("confidence", 60)})

        lonely_scores = [e.get("loneliness", 0) for e in emotions[-7:] if isinstance(e, dict)]
        if lonely_scores and sum(lonely_scores) / len(lonely_scores) > 50:
            chain.append({"observation": "Persistent loneliness signals", "confidence": 70})

        if not chain:
            chain.append({"observation": "Limited relationship data collected", "confidence": 40})
        return chain

    def _build_exercise_chain(self, facts, emotions, habits):
        chain = []
        for f in facts:
            if "exercise" in f.get("key", "") or "movement" in f.get("key", ""):
                chain.append({"observation": f"Exercise: {f.get('value', 'mentioned')}", "confidence": f.get("confidence", 60)})

        energy_low = any(e.get("energy", 50) < 30 for e in emotions[-5:] if isinstance(e, dict))
        if energy_low:
            chain.append({"observation": "Low energy may be linked to exercise patterns", "confidence": 60})

        if not chain:
            chain.append({"observation": "Limited exercise data collected", "confidence": 40})
        return chain

    def _build_work_chain(self, facts, emotions, habits):
        chain = []
        for f in facts:
            if "work" in f.get("key", "") or "job" in f.get("key", ""):
                chain.append({"observation": f"Work: {f.get('value', 'mentioned')}", "confidence": f.get("confidence", 60)})

        burnout_scores = [e.get("burnout", 0) for e in emotions[-7:] if isinstance(e, dict)]
        if burnout_scores and sum(burnout_scores) / len(burnout_scores) > 50:
            chain.append({"observation": "Elevated burnout signals detected", "confidence": 75})

        stress_high = any(e.get("stress", 0) > 70 for e in emotions[-5:] if isinstance(e, dict))
        if stress_high:
            chain.append({"observation": "Work-related stress likely contributing factor", "confidence": 78})

        if not chain:
            chain.append({"observation": "Limited work data collected", "confidence": 40})
        return chain

    def _build_mood_chain(self, facts, emotions, habits):
        chain = []
        for f in facts:
            if "mood" in f.get("key", "") or "emotion" in f.get("key", ""):
                chain.append({"observation": f"Mood: {f.get('value', 'mentioned')}", "confidence": f.get("confidence", 60)})

        if emotions:
            sad_count = sum(1 for e in emotions[-10:] if isinstance(e, dict) and e.get("primary_emotion") == "sad")
            if sad_count >= 3:
                chain.append({"observation": f"Recurring sadness ({sad_count}/{min(10, len(emotions))} recent turns)", "confidence": 72})

            recent_hope = [e.get("hope", 50) for e in emotions[-5:] if isinstance(e, dict)]
            if recent_hope and sum(recent_hope) / len(recent_hope) < 35:
                chain.append({"observation": "Low hope signals — may indicate need for support", "confidence": 65})

        if not chain:
            chain.append({"observation": "Limited mood data collected", "confidence": 40})
        return chain

    def _build_motivation_chain(self, facts, emotions, habits):
        chain = []
        for f in facts:
            if "motivation" in f.get("key", ""):
                chain.append({"observation": f"Motivation: {f.get('value', 'mentioned')}", "confidence": f.get("confidence", 60)})

        recent_motivation = [e.get("motivation", 50) for e in emotions[-5:] if isinstance(e, dict)]
        if recent_motivation and sum(recent_motivation) / len(recent_motivation) < 35:
            chain.append({"observation": "Consistently low motivation scores", "confidence": 70})

        if not chain:
            chain.append({"observation": "Limited motivation data collected", "confidence": 40})
        return chain

    def _build_routine_chain(self, facts, emotions, habits):
        chain = []
        for f in facts:
            if "routine" in f.get("key", ""):
                chain.append({"observation": f"Routine: {f.get('value', 'mentioned')}", "confidence": f.get("confidence", 60)})

        sleep_fact = next((f for f in facts if "sleep" in f.get("key", "")), None)
        if sleep_fact:
            chain.append({"observation": "Sleep disruption affecting daily routine", "confidence": 65})

        if not chain:
            chain.append({"observation": "Limited routine data collected", "confidence": 40})
        return chain

    def _build_nutrition_chain(self, facts, emotions, habits):
        chain = []
        for f in facts:
            if "nutrition" in f.get("key", "") or "eat" in f.get("key", "") or "food" in f.get("key", ""):
                chain.append({"observation": f"Nutrition: {f.get('value', 'mentioned')}", "confidence": f.get("confidence", 60)})

        if not chain:
            chain.append({"observation": "Limited nutrition data collected", "confidence": 40})
        return chain

    def _build_generic_chain(self, facts, emotions, habits):
        chain = []
        for f in facts[:3]:
            chain.append({"observation": f"Signal: {f.get('value', 'observed')}", "confidence": f.get("confidence", 50)})
        if not chain:
            chain.append({"observation": "Limited data for this pillar", "confidence": 40})
        return chain

    def _determine_root_cause(self, pillar, chain, emotion_history):
        root_causes = {
            "sleep": ("Sleep disruption likely driven by [identified factor]", 70),
            "stress": ("Chronic stress accumulation from [sources]", 75),
            "relationships": ("Social connection gap affecting wellbeing", 65),
            "exercise": ("Sedentary pattern contributing to low energy and mood", 60),
            "work": ("Work-related pressure contributing to overall stress load", 72),
            "mood": ("Mood fluctuations linked to [contributing factors]", 68),
            "motivation": ("Motivation dip potentially connected to broader wellbeing factors", 62),
            "routine": ("Routine disruption creating cascade effect on other pillars", 65),
            "nutrition": ("Nutrition patterns may be impacting energy and mood", 55),
        }

        cause, prob = root_causes.get(pillar, ("Patterns identified for further exploration", 50))

        if chain:
            avg_conf = sum(c.get("confidence", 50) for c in chain) / len(chain)
            prob = int((prob + avg_conf) / 2)

        key_factors = [c["observation"] for c in chain[:3] if c.get("confidence", 0) > 60]
        if key_factors:
            cause = cause.replace("[identified factor]", key_factors[0].lower())
            cause = cause.replace("[sources]", ", ".join(f.lower() for f in key_factors[:2]))
            cause = cause.replace("[contributing factors]", ", ".join(f.lower() for f in key_factors[:2]))

        cause = cause.replace("[identified factor]", "the available data")
        cause = cause.replace("[sources]", "identified patterns")
        cause = cause.replace("[contributing factors]", "observed patterns")

        return cause, min(95, prob)
