import random
import json

CATEGORIES = [
    "work stress", "relationship problems", "burnout", "loneliness",
    "low mood", "anxiety patterns", "adhd-like symptoms", "sleep",
    "fitness", "productivity", "motivation", "grief", "career",
    "money", "family", "school", "routine", "medication adherence", "exercise"
]

USER_TURNS = {
    "work stress": [
        "I've been so overwhelmed at work lately. Deadlines are piling up and I can't catch a break.",
        "My boss keeps piling on more work but there's no recognition. I'm burning out fast.",
        "I dread Sunday nights because Monday is coming. The whole week feels like a grind.",
        "I used to love my job but now it just feels like an endless treadmill.",
        "There's this toxic coworker who makes everything harder. I'm so frustrated.",
        "I'm working 10 hour days and still falling behind. Something has to give.",
        "I feel like I'm one bad meeting away from quitting on the spot.",
    ],
    "burnout": [
        "I'm just so tired all the time. Not just physically — everything feels heavy.",
        "Nothing excites me anymore. I used to have hobbies. Now I just numb out on my phone.",
        "I can't remember the last time I felt genuinely rested.",
        "Even small tasks feel monumental. Making breakfast feels like climbing a mountain.",
        "I snapped at my partner over nothing yesterday. That's not who I am.",
        "Coffee doesn't even work anymore. I'm running on fumes.",
    ],
    "loneliness": [
        "I live alone and sometimes I realize I haven't spoken out loud in days.",
        "I have friends but I still feel completely disconnected from everyone.",
        "Everyone seems to have their people. I don't feel like I belong anywhere.",
        "I moved to a new city six months ago and still haven't made a real friend.",
        "Sometimes I just wish someone would check in on me without me having to ask.",
    ],
    "low mood": [
        "I've just been feeling flat. Nothing terrible, just... nothing.",
        "I can't remember the last time I genuinely laughed.",
        "Things that used to make me happy just don't land anymore.",
        "I don't feel sad exactly. More like everything is in grayscale.",
        "I keep canceling plans because I don't have the energy to pretend to be okay.",
    ],
    "sleep": [
        "I lie in bed for hours before I can fall asleep. My brain won't shut up.",
        "I wake up at 3am every night and can't get back to sleep for an hour.",
        "I'm getting 5 hours of sleep tops and I can feel it catching up with me.",
        "I fall asleep fine but I wake up exhausted like I didn't sleep at all.",
        "My sleep schedule is completely backwards. I'm awake all night, dead all day.",
        "I know I need more sleep but I can't seem to make myself go to bed earlier.",
    ],
    "anxiety patterns": [
        "I keep replaying conversations in my head wondering if I said something wrong.",
        "My heart starts racing randomly and I don't know why.",
        "I worry about things that haven't even happened yet. My mind goes to worst case scenarios.",
        "I feel like I'm waiting for something bad to happen all the time.",
        "Social situations exhaust me because I'm constantly monitoring everything I do and say.",
    ],
    "motivation": [
        "I have goals I care about but I just can't seem to start working on them.",
        "I procrastinate until the last minute and the anxiety is the only thing that gets me moving.",
        "I used to be so driven. Now I can barely get myself to do the basics.",
        "I start things with enthusiasm and then lose interest a week later.",
        "I know what I should be doing but I do the opposite. It's like I'm sabotaging myself.",
    ],
    "family": [
        "My parents don't understand me at all. Every conversation turns into an argument.",
        "I feel guilty all the time about not calling home enough.",
        "There's this family expectation that I'll follow a certain path and I'm not sure I want to.",
        "My sibling is going through something hard and I don't know how to help.",
    ],
}

RISK_FLAG_TURNS = [
    "I don't know how much longer I can do this. It all feels pointless.",
    "Sometimes I think everyone would be better off without me.",
    "I've been having thoughts about ending things. I'm scared.",
    "I don't want to be here anymore. I'm sorry.",
    "I've been researching ways to kill myself. I need help.",
]


class SyntheticDataGenerator:
    def __init__(self):
        self.generated = []

    def generate_conversation(self, category=None, num_turns=None):
        if category is None:
            category = random.choice(CATEGORIES)
        if num_turns is None:
            num_turns = random.randint(4, 8)

        turns = []
        user_turns = USER_TURNS.get(category, USER_TURNS["low mood"])

        system_prompts = {
            "work stress": "That sounds really draining. What part of work feels heaviest right now?",
            "burnout": "That exhaustion you're describing — is it more physical or mental?",
            "loneliness": "That sounds incredibly hard. When did you start feeling this disconnected?",
            "low mood": "I hear you. That flat feeling is worth paying attention to. How long has it been there?",
            "sleep": "Poor sleep affects everything. What do you think is interfering most with your rest?",
            "anxiety patterns": "That constant worrying must be exhausting. Do you notice any triggers?",
            "motivation": "That gap between wanting to do something and actually doing it is real. What's the hardest part?",
            "family": "Family dynamics can be so complex. What would you want them to understand about you?",
        }

        for i in range(num_turns):
            if i < len(user_turns):
                user_text = user_turns[i]
            else:
                user_text = random.choice(user_turns)

            if i == 0:
                assistant_text = "Thanks for sharing that with me. " + system_prompts.get(category, "Tell me more about what's going on.")
            elif i % 2 == 0:
                assistant_text = random.choice([
                    "I appreciate you being open with me. Can you tell me more?",
                    "That makes a lot of sense. How does that usually affect your day?",
                    "I hear you. What would you like to do differently?",
                    "That's a really important observation. When did you first notice this?",
                ])
            else:
                assistant_text = random.choice([
                    "Thank you for sharing. How are you feeling right now talking about this?",
                    "That sounds really difficult. What do you think you need most right now?",
                    "I'm glad you're talking about this. What would support look like for you?",
                    "Let's sit with that for a moment. What comes up when you read that back?",
                ])

            emotion_tag = {
                "primary_emotion": random.choice(["sad", "stressed", "anxious", "tired", "frustrated"]),
                "emotional_intensity": random.randint(40, 85),
                "avoidance": random.randint(10, 40),
                "stress": random.randint(40, 80),
            }

            turns.append({"role": "user", "text": user_text, "emotion_tag": emotion_tag, "risk_flag": False})
            turns.append({"role": "assistant", "text": assistant_text, "emotion_tag": None, "risk_flag": False})

        result = {"category": category, "turns": turns}
        self.generated.append(result)
        return result

    def generate_risk_conversation(self):
        turns = []
        user_text = random.choice(RISK_FLAG_TURNS)
        emotion_tag = {
            "primary_emotion": "sad",
            "emotional_intensity": 90,
            "avoidance": 10,
            "stress": 85,
            "risk_flag": True
        }

        turns.append({"role": "user", "text": user_text, "emotion_tag": emotion_tag, "risk_flag": True})
        turns.append({
            "role": "assistant",
            "text": "I'm really glad you told me this. What you're feeling matters, and you're not alone in this. Please reach out to a crisis service — they're trained to help right now. You can text or call 988 for immediate support. Would you like me to help you find additional resources?",
            "emotion_tag": None,
            "risk_flag": False
        })

        result = {"category": "crisis", "turns": turns}
        self.generated.append(result)
        return result

    def generate_batch(self, count=10, include_risk=True):
        results = []
        for _ in range(count):
            cat = random.choice(CATEGORIES)
            results.append(self.generate_conversation(category=cat))
        if include_risk:
            results.append(self.generate_risk_conversation())
        return results

    def export_json(self, filepath):
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(self.generated, f, indent=2, ensure_ascii=False)
        return filepath
