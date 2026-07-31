class RoutineGenerator:
    def __init__(self, memory_system=None):
        self.memory = memory_system

    def generate(self, root_cause_or_goal, memory_facts=None, past_adherence=None, constraints=None):
        memory_facts = memory_facts or []
        past_adherence = past_adherence or {}
        constraints = constraints or {}

        topic = self._classify_topic(root_cause_or_goal)
        actions = self._build_actions(topic, memory_facts, constraints)
        routine_type = topic

        return {
            "routine_type": routine_type,
            "actions": actions,
            "review_after_days": 7
        }

    def _classify_topic(self, text):
        text_lower = text.lower()
        topics = {
            "sleep": ["sleep", "insomnia", "rest", "tired", "fatigue", "bedtime"],
            "morning": ["morning", "wake up", "start the day", "breakfast"],
            "work": ["work", "job", "career", "burnout", "overwork", "deadline", "productivity"],
            "stress": ["stress", "overwhelm", "anxiety", "calm", "relax", "tense"],
            "exercise": ["exercise", "workout", "gym", "fitness", "movement", "active", "walk"],
            "meditation": ["meditation", "mindfulness", "breathe", "calm", "focus", "present"],
            "recovery": ["recovery", "rest", "break", "pause", "recharge", "weekend"],
            "nutrition": ["nutrition", "eat", "food", "diet", "meal", "water", "hydration"],
            "relationships": ["relation", "social", "friend", "family", "connect", "lonely"],
            "mood": ["mood", "emotion", "feel", "sad", "happy", "flat"],
            "motivation": ["motivation", "drive", "goal", "purpose", "energy", "productive"],
        }

        scores = {}
        for topic, keywords in topics.items():
            scores[topic] = sum(1 for kw in keywords if kw in text_lower)

        best = max(scores, key=scores.get)
        return best if scores[best] > 0 else "morning"

    def _build_actions(self, routine_type, facts, constraints):
        templates = {
            "sleep": [
                {"action": "Set a consistent bedtime within the same 30-minute window every night",
                 "why": "Consistency trains your circadian rhythm",
                 "time_of_day": "evening",
                 "difficulty": "easy"},
                {"action": "Create a 15-minute wind-down routine without screens before bed",
                 "why": "Blue light suppresses melatonin production",
                 "time_of_day": "evening",
                 "difficulty": "easy"},
                {"action": "Write down 3 things on your mind before closing your eyes",
                 "why": "Externalizing thoughts reduces racing mind at bedtime",
                 "time_of_day": "evening",
                 "difficulty": "easy"},
            ],
            "morning": [
                {"action": "Wake up at the same time each day, even on weekends",
                 "why": "Regular wake time anchors your entire circadian system",
                 "time_of_day": "morning",
                 "difficulty": "medium"},
                {"action": "Drink a full glass of water within 30 minutes of waking",
                 "why": "Rehydrates after sleep and kickstarts metabolism",
                 "time_of_day": "morning",
                 "difficulty": "easy"},
                {"action": "Spend 5 minutes outside or by a window within the first hour",
                 "why": "Morning light exposure sets your body clock for the day",
                 "time_of_day": "morning",
                 "difficulty": "easy"},
            ],
            "work": [
                {"action": "Block 90 minutes of focused work each morning before checking messages",
                 "why": "Deep work done early avoids decision fatigue",
                 "time_of_day": "morning",
                 "difficulty": "medium"},
                {"action": "Take a 5-minute break every hour — step away from your screen",
                 "why": "Regular micro-breaks prevent cognitive accumulation of stress",
                 "time_of_day": "throughout_day",
                 "difficulty": "easy"},
                {"action": "Set a hard stop time for work and transition with a short walk",
                 "why": "Physical boundary between work and rest prevents burnout",
                 "time_of_day": "evening",
                 "difficulty": "medium"},
            ],
            "stress": [
                {"action": "Take 3 deep breaths (4s in, 6s out) whenever you notice tension rising",
                 "why": "Extended exhale activates the parasympathetic nervous system",
                 "time_of_day": "as_needed",
                 "difficulty": "easy"},
                {"action": "Dedicate 10 minutes to something you enjoy, completely guilt-free",
                 "why": "Dedicated pleasure time counterbalances stress accumulation",
                 "time_of_day": "evening",
                 "difficulty": "easy"},
                {"action": "Write down what's stressing you — naming it reduces its grip",
                 "why": "Externalizing stress reduces its cognitive load",
                 "time_of_day": "evening",
                 "difficulty": "easy"},
            ],
            "exercise": [
                {"action": "Start with a 10-minute walk each day — no pressure to do more",
                 "why": "Starting small builds momentum without triggering avoidance",
                 "time_of_day": "morning_or_afternoon",
                 "difficulty": "easy"},
                {"action": "Schedule movement at the same time each day to build the habit",
                 "why": "Habit stacking on time of day increases adherence",
                 "time_of_day": "same_time_daily",
                 "difficulty": "easy"},
                {"action": "Stretch for 5 minutes after waking up or before bed",
                 "why": "Gentle movement improves circulation and reduces muscle tension",
                 "time_of_day": "morning_or_evening",
                 "difficulty": "easy"},
            ],
            "meditation": [
                {"action": "Start with 3 minutes of quiet breathing after waking up",
                 "why": "Morning stillness sets a calmer tone for the day",
                 "time_of_day": "morning",
                 "difficulty": "easy"},
                {"action": "Use a 60-second grounding exercise during stressful moments",
                 "why": "Brief mindfulness resets attention and reduces reactivity",
                 "time_of_day": "as_needed",
                 "difficulty": "easy"},
            ],
            "nutrition": [
                {"action": "Add one serving of vegetables to one meal each day",
                 "why": "Small nutritional upgrades are more sustainable than overhauling your diet",
                 "time_of_day": "any_meal",
                 "difficulty": "easy"},
                {"action": "Keep a water bottle at your desk and aim to refill it twice",
                 "why": "Mild dehydration is often mistaken for fatigue or brain fog",
                 "time_of_day": "throughout_day",
                 "difficulty": "easy"},
            ],
            "recovery": [
                {"action": "Take one 15-minute completely unstructured break today",
                 "why": "Unstructured time allows your brain to actually rest",
                 "time_of_day": "afternoon",
                 "difficulty": "easy"},
                {"action": "Do one thing this week that you used to enjoy but haven't done lately",
                 "why": "Reconnecting with past joys can reveal what's been missing",
                 "time_of_day": "flexible",
                 "difficulty": "medium"},
            ],
            "relationships": [
                {"action": "Reach out to one person you trust this week — even a short message counts",
                 "why": "Small social connections combat isolation more effectively than waiting for big ones",
                 "time_of_day": "flexible",
                 "difficulty": "easy"},
                {"action": "Practice saying one honest thing about how you feel to someone close",
                 "why": "Vulnerability in safe relationships deepens connection",
                 "time_of_day": "flexible",
                 "difficulty": "medium"},
            ],
            "mood": [
                {"action": "Track one moment of genuine positive feeling each day — however small",
                 "why": "Noticing positive moments counteracts the brain's negativity bias",
                 "time_of_day": "evening",
                 "difficulty": "easy"},
                {"action": "Do one small thing that future-you will thank you for",
                 "why": "Acting in your own interest builds self-trust and lifts mood",
                 "time_of_day": "any_time",
                 "difficulty": "easy"},
            ],
            "motivation": [
                {"action": "Pick the smallest possible version of one task and do it for 2 minutes",
                 "why": "Starting is the hardest part — momentum builds from motion, not planning",
                 "time_of_day": "morning",
                 "difficulty": "easy"},
                {"action": "Remind yourself why this matters — connect the task to a value, not an obligation",
                 "why": "Values-based motivation outlasts discipline-based motivation",
                 "time_of_day": "morning",
                 "difficulty": "easy"},
            ],
        }

        actions = templates.get(routine_type, templates["morning"])
        max_actions = min(4, len(facts) + 2) if facts else 3
        selected = actions[:max_actions]

        return selected
