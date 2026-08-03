from enum import Enum


class PlannerAction(str, Enum):
    ASK_QUESTION = "ask_question"
    ANSWER_DIRECT_QUESTION = "answer_direct_question"
    ANSWER_CAPABILITY = "answer_capability"
    PROVIDE_INSIGHT = "provide_insight"
    PROVIDE_RECOMMENDATION = "provide_recommendation"
    EXPLORE_TOPIC = "explore_topic"
    CLARIFY = "clarify"
    CONFIRM_UNDERSTANDING = "confirm_understanding"
    CREATE_COMMITMENT = "create_commitment"
    SCHEDULE_ACTION = "schedule_action"
    CHECK_PROGRESS = "check_progress"
    RESUME_TOPIC = "resume_topic"
    SWITCH_TOPIC = "switch_topic"
    CASUAL_CHAT = "casual_chat"
    REFLECT = "reflect"
    SUMMARIZE = "summarize"
    CLOSE_CONVERSATION = "close_conversation"
    ESCALATE = "escalate"
    WAIT = "wait"


_ASKING_ACTIONS = (PlannerAction.ASK_QUESTION, PlannerAction.EXPLORE_TOPIC,
                   PlannerAction.CLARIFY)