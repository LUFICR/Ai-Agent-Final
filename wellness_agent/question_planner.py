import random

ESCAPE_HATCH = ["Something else", "Let me explain"]

STATE_OPTION_RULES = {
    "greeting":             {"mode": "options",     "free_slots": 0},
    "free_conversation":    {"mode": "free",        "free_slots": 0},
    "rapport_building":     {"mode": "options",     "free_slots": 0},
    "avoidance_detection":  {"mode": "options",     "free_slots": 0},
    "soft_exploration":     {"mode": "options",     "free_slots": 0},
    "guided_discovery":     {"mode": "options",     "free_slots": 0},
    "pillar_selection":     {"mode": "options",     "free_slots": 0},
    "deep_investigation":   {"mode": "options",     "free_slots": 1},  # 1 open/narrative slot per 5 questions
    "insight_generation":   {"mode": "delivery",    "free_slots": 0},  # no question, just delivery + confirm
    "routine_planning":     {"mode": "options",     "free_slots": 0},
    "reflection":           {"mode": "options",     "free_slots": 0},
    "weekly_review":        {"mode": "options",     "free_slots": 0},
    "follow_up":            {"mode": "options",     "free_slots": 0},
}

STATE_OPTIONS = {
    "greeting": {
        "text": "How are you feeling right now?",
        "options": ["😊 Good", "😐 Okay", "😔 Rough", "😴 Tired"]
    },
    "free_conversation_cap": {
        "text": "A few things on your mind, or one thing in particular?",
        "options": ["😴 Sleep", "💼 Work", "💛 Relationships", "🌫️ Hard to say"]
    },
    "rapport_building": {
        "text": "How's your day been, genuinely?",
        "options": ["🙂 Good", "😑 Meh", "Rough one"]
    },
    "avoidance_detection": {
        "text": "No pressure — want to keep talking, switch topics, or just check in later?",
        "options": ["Keep talking", "Switch topics", "Check in later"]
    },
    "pillar_selection": {
        "text": "Which of these feels most relevant right now?",
        "options": None  # filled dynamically
    },
    "insight_generation_confirm": {
        "text": "Does that land, or does something feel off?",
        "options": ["Yes, that's it", "Partly", "Not quite"]
    },
    "routine_planning": {
        "text": "Here's what I'd suggest — want all of them, or start with just one?",
        "options": ["All of them", "Just one", "Not right now"]
    },
    "reflection": {
        "text": "Anything else on your mind before we wrap, or good for today?",
        "options": ["Good for today", "One more thing"]
    },
    "follow_up": {
        "text": "How's your week been since we talked?",
        "options": ["Better", "Same", "Rougher"]
    },
    "soft_exploration": {
        "text": "Sometimes it's hard to put into words. Want to start anywhere?",
        "options": ["A specific thing", "Just talking helps", "Not sure yet"]
    },
    "weekly_review": {
        "text": "How was your week overall?",
        "options": ["Good week", "Mixed", "Tough week"]
    },
}


class QuestionPlanner:
    def __init__(self, memory_system=None):
        self.memory = memory_system
        self.used_questions = set()
        self._open_slots_used = 0
        self._deep_q_count = 0

    def generate_question(self, target_pillar, current_state, preferred_type_hint=None, memory_context=None):
        rule = STATE_OPTION_RULES.get(current_state, {"mode": "options", "free_slots": 0})

        # State-specific canned options (for states without pillar context)
        if current_state in STATE_OPTIONS:
            q = dict(STATE_OPTIONS[current_state])
            if current_state == "pillar_selection":
                q["options"] = self._pillar_options(target_pillar, memory_context or {})
            elif current_state == "routine_planning":
                q["options"] = self._ensure_escape(q.get("options"))
            else:
                q["options"] = self._ensure_escape(q.get("options"))
            q["question_type"] = "choice"
            return q

        # Deep Investigation: cycle types, enforce 1 open slot
        if current_state == "deep_investigation":
            q_type, is_open = self._deep_type()
            question_data = self._get_question_for_pillar(target_pillar, q_type, current_state)
            if is_open:
                question_data["response_options"] = self._ensure_escape(
                    question_data.get("response_options") or ["Let me explain"]
                )
            else:
                question_data["response_options"] = self._ensure_escape(
                    question_data.get("response_options") or self._fallback_options(target_pillar, q_type)
                )
            question_data["question_type"] = q_type
            return question_data

        # Free Conversation — always open text
        if current_state == "free_conversation":
            q_data = self._get_question_for_pillar(target_pillar, "open", current_state)
            q_data["response_options"] = None
            return q_data

        # All other states: pillar questions with options
        q_type = self._type_for_state(current_state)
        question_data = self._get_question_for_pillar(target_pillar, q_type, current_state)
        question_data["response_options"] = self._ensure_escape(
            question_data.get("response_options") or self._fallback_options(target_pillar, q_type)
        )
        question_data["question_type"] = q_type
        if current_state == "rapport_building":
            question_data["question_text"] = self._soften_tone(question_data["question_text"])
        return question_data

    def _type_for_state(self, state):
        mapping = {
            "guided_discovery": "clarifying",
            "pillar_selection": "choice",
            "insight_generation": "reflective",
            "routine_planning": "future",
            "reflection": "reflective",
            "rapport_building": "reflective",
            "avoidance_detection": "choice",
            "soft_exploration": "open",
            "follow_up": "motivational",
            "weekly_review": "reflective",
        }
        return mapping.get(state, "open")

    def _deep_type(self):
        types = ["clarifying", "scaling", "clarifying", "reflective", "narrative"]
        idx = self._deep_q_count % len(types)
        self._deep_q_count += 1
        is_open = types[idx] in ("narrative", "open")
        return types[idx], is_open

    def _pillar_options(self, detected_pillar, context):
        base = [p.title() for p in [detected_pillar] if p]
        alternates = ["Sleep", "Work", "Stress", "Relationships", "Mood", "Exercise"]
        others = [a for a in alternates if a.lower() != detected_pillar][:2]
        options = base + others + ESCAPE_HATCH
        return options

    def _fallback_options(self, pillar, q_type):
        fallbacks = {
            "sleep": ["Not enough hours", "Poor quality", "Can't fall asleep", "Waking up"],
            "stress": ["Work", "Relationships", "Health", "Money", "Everything"],
            "relationships": ["Partner", "Family", "Friend", "Coworker"],
            "exercise": ["Too tired", "No time", "Not motivated", "Injured"],
            "work": ["Workload", "Environment", "Meaning", "Balance"],
            "mood": ["Up and down", "Mostly low", "Flat", "Good actually"],
            "motivation": ["Can't start", "Can't finish", "Don't care", "Burnout"],
            "routine": ["Mornings", "Evenings", "Work hours", "Weekends"],
            "nutrition": ["Meal prep", "Skipping meals", "Cravings", "Hydration"],
            "finances": ["Budgeting", "Debt", "Saving", "Income"],
        }
        base = fallbacks.get(pillar, ["A lot", "Some", "Not much"])
        return base[:4]

    def _ensure_escape(self, options):
        if options is None:
            return ESCAPE_HATCH[:]
        if isinstance(options, list):
            has_escape = any(e.lower() in ("something else", "let me explain", "other", "none", "not sure") for e in options)
            if not has_escape:
                options = list(options) + ESCAPE_HATCH
            return options
        return ESCAPE_HATCH[:]

    # ─── Pillar question templates (keep existing, add escape hatches) ───

    def _get_question_for_pillar(self, pillar, q_type, state):
        questions = {
            "sleep": {
                "open": [
                    {"text": "How have you been sleeping lately?", "options": ["Great", "Okay", "Not great", "Terrible"]},
                    {"text": "What's been on your mind about sleep recently?", "options": ["Falling asleep", "Staying asleep", "Waking early", "Not enough time"]},
                    {"text": "Tell me about your sleep routine.", "options": ["Consistent", "Irregular", "Non-existent", "Could improve"]},
                ],
                "reflective": [
                    {"text": "You mentioned sleep hasn't been great — what do you think is affecting it most?", "options": ["Stress", "Screen time", "Late nights", "Racing thoughts"]},
                    {"text": "When you say you're tired, is it physical or mental exhaustion?", "options": ["Physical", "Mental", "Both"]},
                    {"text": "What's the biggest difference between nights you sleep well and nights you don't?", "options": ["Bedtime routine", "Stress level", "What I ate", "Room environment"]},
                ],
                "clarifying": [
                    {"text": "Roughly how many hours of sleep are you getting on average?", "options": ["Less than 5", "5-6", "6-7", "7+"]},
                    {"text": "Do you have trouble falling asleep, staying asleep, or both?", "options": ["Falling asleep", "Staying asleep", "Both"]},
                    {"text": "How long does it usually take you to fall asleep?", "options": ["15 min or less", "30 min", "1 hour", "2+ hours"]},
                ],
                "scaling": [
                    {"text": "On a scale of 1-10, how rested do you feel when you wake up?", "options": ["1-3", "4-5", "6-7", "8-10"]},
                    {"text": "On a scale of 1-10, how much does sleep affect your daytime energy?", "options": ["1-3", "4-5", "6-7", "8-10"]},
                ],
                "narrative": [
                    {"text": "Walk me through your evening before bed — what does that wind-down look like?", "options": None},
                ],
                "future": [
                    {"text": "What would a good night's sleep look like for you?", "options": ["7+ hours", "Uninterrupted", "Falling asleep fast", "Waking refreshed"]},
                    {"text": "If you could change one thing about your sleep, what would it be?", "options": ["Earlier bedtime", "Less screen time", "Less stress", "Consistent schedule"]},
                ],
                "choice": [
                    {"text": "What feels most off about your sleep right now?", "options": ["Can't fall asleep", "Wake up too early", "Not enough hours", "Poor quality", "Actually it's fine"]},
                ],
                "soft_exploration": [
                    {"text": "Sometimes sleep is hard to talk about. Is there anything small you've noticed about it?", "options": ["A pattern", "A feeling", "Not really"]},
                ],
            },
            "stress": {
                "open": [
                    {"text": "How's your stress level been this week?", "options": ["Low", "Moderate", "High", "Through the roof"]},
                    {"text": "What's been taking up most of your mental energy lately?", "options": ["Work", "Relationships", "Finances", "Health"]},
                ],
                "reflective": [
                    {"text": "You mentioned feeling stressed — can you put your finger on the biggest source?", "options": ["Work", "Relationships", "Health", "Finances"]},
                    {"text": "When stress builds up, how does it usually show up for you?", "options": ["Irritability", "Withdrawal", "Overthinking", "Physical symptoms"]},
                    {"text": "What's the first thing that starts to slip when stress gets high?", "options": ["Sleep", "Eating", "Patience", "Focus"]},
                ],
                "clarifying": [
                    {"text": "Is this stress coming from one area or multiple?", "options": ["One area", "Multiple areas", "Hard to tell"]},
                    {"text": "Have you noticed any physical signs when stress spikes?", "options": ["Headaches", "Tension", "Fatigue", "Digestive issues", "None"]},
                ],
                "scaling": [
                    {"text": "On a scale of 1-10, how would you rate your stress right now?", "options": ["1-3", "4-5", "6-7", "8-10"]},
                    {"text": "On a scale of 1-10, how well are you coping with it?", "options": ["1-3", "4-5", "6-7", "8-10"]},
                ],
                "narrative": [
                    {"text": "Describe a recent moment when stress felt highest — what was happening around you?", "options": None},
                ],
                "future": [
                    {"text": "If stress dropped to a 3 tomorrow, what would be different about your day?", "options": ["I'd sleep better", "I'd be calmer", "I'd enjoy things", "I'd get more done"]},
                ],
            },
            "relationships": {
                "open": [
                    {"text": "How are things with the important people in your life?", "options": ["Good", "Complicated", "Strained", "Distant"]},
                    {"text": "Tell me about your social life lately — has it felt full or empty?", "options": ["Full", "Okay", "Empty", "I prefer solitude"]},
                ],
                "reflective": [
                    {"text": "You mentioned a relationship that's been on your mind — want to explore that?", "options": ["Yes", "Maybe later", "Not really"]},
                    {"text": "How supported do you feel by the people around you?", "options": ["Very", "Somewhat", "Not much", "Alone"]},
                ],
                "choice": [
                    {"text": "Which relationship feels most pressing to talk about?", "options": ["Partner", "Family", "Friend", "Coworker", "Myself"]},
                ],
            },
            "exercise": {
                "open": [
                    {"text": "How's your movement and exercise routine going?", "options": ["Consistent", "Sporadic", "Non-existent", "Good"]},
                    {"text": "What's your relationship with exercise like these days?", "options": ["Enjoy it", "Tolerate it", "Avoid it", "Miss it"]},
                ],
                "motivational": [
                    {"text": "What kind of movement feels good to you right now?", "options": ["Walking", "Gym", "Yoga", "Sports", "Nothing sounds good"]},
                    {"text": "What's one small step you could take to move more?", "options": ["Walk daily", "Stretch", "Dance", "Take stairs"]},
                ],
                "future": [
                    {"text": "What would an ideal week of movement look like for you?", "options": ["3 walks", "2 gym sessions", "Daily stretching", "A sport"]},
                ],
            },
            "work": {
                "open": [
                    {"text": "How's work been treating you?", "options": ["Good", "Stressful", "Boring", "Overwhelming"]},
                    {"text": "What's the work vibe like right now?", "options": ["Healthy", "Tense", "Chaotic", "Quiet"]},
                ],
                "reflective": [
                    {"text": "You said work has been heavy — heavy how?", "options": ["Too much volume", "Too complex", "Emotionally draining", "Politically difficult"]},
                    {"text": "Does work feel meaningful to you, or is it just draining?", "options": ["Meaningful", "Draining", "Mix of both"]},
                    {"text": "When work gets stressful, what's your usual way of coping?", "options": ["Push through", "Take breaks", "Talk it out", "Withdraw"]},
                ],
                "clarifying": [
                    {"text": "Is it the workload itself, or something about the environment?", "options": ["Workload", "Environment/people", "Both"]},
                    {"text": "Has this been building up gradually or did something specific change?", "options": ["Gradual buildup", "Specific event", "Both"]},
                ],
                "scaling": [
                    {"text": "On a scale of 1-10, how much does work stress spill into the rest of your life?", "options": ["1-3", "4-5", "6-7", "8-10"]},
                ],
                "narrative": [
                    {"text": "Walk me through a typical workday — where do you feel the most tension?", "options": None},
                ],
                "future": [
                    {"text": "If work stress disappeared tomorrow, what would you do with the extra energy?", "options": ["Sleep better", "Be more present", "Pursue hobbies", "Connect with people"]},
                ],
            },
            "mood": {
                "open": [
                    {"text": "How would you describe your overall mood lately?", "options": ["Good", "Up and down", "Low", "Flat"]},
                    {"text": "What's been the predominant feeling this week?", "options": ["Sad", "Anxious", "Irritable", "Numb", "Okay"]},
                ],
                "reflective": [
                    {"text": "You mentioned your mood has been low — when did you notice that shift?", "options": ["Recently", "A few weeks ago", "Months ago", "Hard to pinpoint"]},
                    {"text": "What's one thing that's lifted your mood recently, even a little?", "options": ["A conversation", "Being outside", "Accomplishing something", "Rest"]},
                ],
                "scaling": [
                    {"text": "On a scale of 1-10, where has your mood been averaging this week?", "options": ["1-3", "4-5", "6-7", "8-10"]},
                ],
                "narrative": [
                    {"text": "Walk me through a typical day this week — how did your mood shift throughout?", "options": None},
                ],
            },
            "motivation": {
                "open": [
                    {"text": "How's your motivation these days?", "options": ["High", "Okay", "Low", "Non-existent"]},
                    {"text": "What's been hard to get yourself to do lately?", "options": ["Work tasks", "Self-care", "Socializing", "Household stuff"]},
                ],
                "challenge": [
                    {"text": "You've mentioned feeling unmotivated a few times — what do you think is underneath that?", "options": ["Burnout", "Not knowing where to start", "Fear of failure", "Don't care anymore"]},
                    {"text": "Is it that you don't want to do things, or that you want to but can't?", "options": ["Don't want to", "Want to but can't", "Both"]},
                ],
                "future": [
                    {"text": "What would make you feel more motivated tomorrow?", "options": ["A clear plan", "Less pressure", "Accountability", "Rest"]},
                ],
            },
            "routine": {
                "open": [
                    {"text": "How does your typical day look right now?", "options": ["Structured", "Messy", "Same thing every day", "Different each day"]},
                    {"text": "Are you happy with your daily rhythm?", "options": ["Yes", "No", "Could improve"]},
                ],
                "reflective": [
                    {"text": "You mentioned your routine feels off — what part feels most disrupted?", "options": ["Morning", "Workday", "Evening", "Weekend"]},
                ],
                "future": [
                    {"text": "If you could design your ideal morning routine, what would it include?", "options": ["Quiet time", "Exercise", "Good breakfast", "Planning the day"]},
                ],
            },
            "nutrition": {
                "open": [
                    {"text": "How's your eating been lately?", "options": ["Good", "Could be better", "Struggling", "Fine"]},
                    {"text": "What does a typical day of eating look like for you?", "options": ["3 meals", "2 meals", "Grazing", "Irregular"]},
                ],
                "reflective": [
                    {"text": "You mentioned your eating habits have changed — what's driving that?", "options": ["Stress", "Schedule", "Mood", "No particular reason"]},
                ],
            },
            "finances": {
                "open": [
                    {"text": "You mentioned finances — how's that weighing on you?", "options": ["Heavily", "Moderately", "Slightly", "Not much"]},
                    {"text": "How much headspace do finances take up for you?", "options": ["A lot", "Some", "Not much"]},
                ],
            },
        }

        pillar_questions = questions.get(pillar, questions.get("mood"))
        type_questions = pillar_questions.get(q_type, pillar_questions.get("open", []))
        if not type_questions:
            type_questions = [{"text": "Tell me more about that.", "options": ["Okay", "Not sure", "Let me think"]}]

        available = [q for q in type_questions if q["text"] not in self.used_questions]
        if not available:
            available = type_questions
            self.used_questions.clear()

        chosen = random.choice(available)
        self.used_questions.add(chosen["text"])

        return {
            "question_type": q_type,
            "question_text": chosen["text"],
            "response_options": chosen.get("options")
        }

    def _soften_tone(self, question):
        openers = ["I'd love to hear — ", "I'm curious — ", "If you're up for sharing — "]
        if any(question.startswith(o) for o in openers):
            return question
        return random.choice(openers) + question[0].lower() + question[1:]

    def reset_deep_count(self):
        self._deep_q_count = 0
        self._open_slots_used = 0
