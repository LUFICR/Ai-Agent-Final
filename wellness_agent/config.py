import os
from pathlib import Path

APP_NAME = "Wellness Companion"

PRODUCT_CONTEXT = """
You are one component of an AI wellness companion system called {APP_NAME}.

BUSINESS GOAL: Build daily engagement through genuine insight, not novelty — retention comes from users feeling understood, not from features.
USER GOAL: Understand themselves better, build sustainable habits, feel supported without judgment or lecturing.
AI GOAL: Narrow down the real root cause of what a user is experiencing through structured, adaptive conversation — never generic advice, never a survey.
WELLNESS GOAL: Strictly non-clinical and non-diagnostic. This is a wellness companion, not a therapist, doctor, or crisis service.
SUCCESS METRICS: session depth (turns to insight), 7/30-day return rate, per-topic resolution rate, user-reported clarity, D7/D30/D90 retention.

HARD BOUNDARIES:
1. Never diagnose a mental health condition (no "you have depression/anxiety/ADHD").
2. Never suggest starting, stopping, or changing medication.
3. Never provide medical, legal, or financial advice beyond wellness habit guidance.
4. If any signal of self-harm, suicidal ideation, or risk to others appears, immediately flag risk=true and hand off to the Risk Detection protocol.
5. Speak like a grounded, warm human coach — never clinical, never saccharine, never robotic.
6. Never invent user data. If a fact isn't in memory or the current message, don't assume it.
"""

PILLARS = [
    "sleep", "stress", "relationships", "exercise",
    "work", "mood", "motivation", "routine",
    "nutrition", "finances"
]

STATES = [
    "greeting", "free_conversation", "rapport_building",
    "avoidance_detection", "soft_exploration", "guided_discovery",
    "pillar_selection", "deep_investigation", "insight_generation",
    "routine_planning", "reflection", "weekly_review", "follow_up"
]

STATE_TRANSITIONS = {
    "greeting": {"next": "free_conversation", "fallback": "greeting"},
    "free_conversation": {"next": "guided_discovery", "fallback": "free_conversation", "max_turns": 4},
    "rapport_building": {"next": "free_conversation", "fallback": "rapport_building"},
    "avoidance_detection": {"next": "soft_exploration", "fallback": "free_conversation"},
    "soft_exploration": {"next": "guided_discovery", "fallback": "free_conversation"},
    "guided_discovery": {"next": "pillar_selection", "fallback": "free_conversation"},
    "pillar_selection": {"next": "deep_investigation", "fallback": "guided_discovery"},
    "deep_investigation": {"next": "insight_generation", "fallback": "deep_investigation", "max_questions": 5},
    "insight_generation": {"next": "routine_planning", "fallback": "insight_generation"},
    "routine_planning": {"next": "reflection", "fallback": "routine_planning"},
    "reflection": {"next": None, "fallback": "reflection"},
    "weekly_review": {"next": "free_conversation", "fallback": "free_conversation"},
    "follow_up": {"next": "free_conversation", "fallback": "free_conversation"},
}

AGENTS = [
    "emotion_detection", "memory_manager", "root_cause_engine",
    "recommendation_engine", "question_planner", "routine_generator",
    "report_generator", "reflection_agent"
]

EMOTION_DIMENSIONS = [
    "primary_emotion", "secondary_emotion", "emotional_intensity",
    "confidence", "avoidance", "stress", "motivation", "hope",
    "energy", "engagement", "trust", "loneliness", "frustration",
    "burnout", "anxiety", "depression_risk", "self_esteem",
    "risk_flag", "risk_reason"
]

MEMORY_CATEGORIES = ["identity", "goals", "habits", "emotional_history", "personality"]

DATA_DIR = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) / "data"

def get_data_dir(subdir=None):
    path = DATA_DIR
    if subdir:
        path = path / subdir
    os.makedirs(path, exist_ok=True)
    return path

def get_user_memory_path(user_id="default"):
    return get_data_dir("memory") / f"{user_id}_memory.json"

def get_user_session_path(user_id="default"):
    return get_data_dir("sessions") / f"{user_id}_session.json"

def get_report_path(user_id="default", period="daily"):
    return get_data_dir("reports") / f"{user_id}_{period}.json"
