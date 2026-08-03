from .modes import ConversationMode

_VALID_TRANSITIONS = {
    ConversationMode.DISCOVERY: {ConversationMode.INVESTIGATION},
    ConversationMode.INVESTIGATION: {ConversationMode.COACHING},
    ConversationMode.COACHING: {ConversationMode.COMMITMENT, ConversationMode.SUMMARIZATION},
    ConversationMode.COMMITMENT: {ConversationMode.FOLLOW_UP, ConversationMode.CLOSURE},
    ConversationMode.FOLLOW_UP: {ConversationMode.CLOSURE},
    ConversationMode.REFLECTION: {ConversationMode.CLOSURE, ConversationMode.FOLLOW_UP},
    ConversationMode.SUMMARIZATION: {ConversationMode.CLOSURE},
    ConversationMode.CLOSURE: set(),
    ConversationMode.ESCALATION: set(),
}

_TEMPORARY_MODES = {ConversationMode.QUESTION_ANSWERING, ConversationMode.CASUAL_CHAT}