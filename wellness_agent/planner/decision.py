from .modes import ConversationMode
from .actions import PlannerAction


class PlannerDecision:
    """The planner's output: exactly one action + the reasoning behind it."""

    __slots__ = ("action", "reason", "confidence", "next_state", "metadata",
                 "mode", "show_quick_replies", "quick_replies", "quick_reply_type")

    def __init__(self, action, reason, confidence=0.80, next_state=None,
                 metadata=None, mode=None):
        self.action = action
        self.reason = reason
        self.confidence = confidence
        self.next_state = next_state
        self.metadata = metadata or {}
        self.mode = mode
        self.show_quick_replies = False
        self.quick_replies = []
        self.quick_reply_type = ""

    def to_dict(self):
        return {
            "action": self.action.value if isinstance(self.action, PlannerAction) else self.action,
            "reason": self.reason,
            "confidence": round(self.confidence, 3),
            "next_state": (self.next_state.value if isinstance(self.next_state, ConversationMode) else self.next_state),
            "metadata": dict(self.metadata or {}),
            "mode": (self.mode.value if isinstance(self.mode, ConversationMode) else self.mode),
            "showQuickReplies": bool(self.show_quick_replies),
            "quickReplies": list(self.quick_replies or []),
            "quickReplyType": self.quick_reply_type or "",
        }