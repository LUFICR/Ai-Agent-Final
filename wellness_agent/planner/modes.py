from enum import Enum


class ConversationMode(str, Enum):
    DISCOVERY = "discovery"
    INVESTIGATION = "investigation"
    COACHING = "coaching"
    REFLECTION = "reflection"
    COMMITMENT = "commitment"
    FOLLOW_UP = "follow_up"
    QUESTION_ANSWERING = "question_answering"
    CASUAL_CHAT = "casual_chat"
    SUMMARIZATION = "summarization"
    CLOSURE = "closure"
    ESCALATION = "escalation"