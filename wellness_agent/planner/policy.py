import re
from .modes import ConversationMode
from .actions import _ASKING_ACTIONS


_UNCERTAINTY_RE = re.compile(
    r"\bi don'?t know\b|\bidk\b|\bnot sure\b|\bunsure\b|\bhard to say\b|"
    r"\bcan'?t decide\b|\bcannot decide\b|\bconfus|"
    r"\bi'?m not sure\b|\bdunno\b|\bno idea\b|\bno clue\b",
    re.IGNORECASE,
)

_QUESTION_LADDER = ("reflective", "clarifying", "narrowing", "action",
                     "commitment")

_QUICK_REPLY_TYPE_CONVERSATION_ENTRY = "conversation_entry"

_QUICK_REPLY_ENTRY_BUTTONS = [
    "\U0001f4bc Work",
    "\U0001f468\U0001f469\U0001f467 Relationships",
    "\U0001f9e0 Mental health",
    "\U0001f3c3 Physical health",
]

_QUICK_REPLY_ENTRY_PILLARS = {
    "mental health": "mood",
    "physical health": "exercise",
}

_QUICK_REPLY_SUPPRESSED_MODES = {
    ConversationMode.COMMITMENT,
    ConversationMode.COACHING,
    ConversationMode.REFLECTION,
    ConversationMode.CASUAL_CHAT,
    ConversationMode.SUMMARIZATION,
    ConversationMode.CLOSURE,
    ConversationMode.FOLLOW_UP,
    ConversationMode.QUESTION_ANSWERING,
    ConversationMode.ESCALATION,
}

_QUICK_REPLY_OPEN_STATES = {"greeting", "guided_discovery", "pillar_selection",
                              "soft_exploration", "free_conversation"}


def _is_rich_input(ctx):
    message = (ctx.get("message") or "").strip()
    words = message.split()
    if not words:
        return False
    if len(words) >= 8:
        return True
    if len(words) < 3:
        return False
    return bool(ctx.get("has_emotion_keyword") or ctx.get("has_topic_signal"))


def _button_mode(ctx):
    if _is_rich_input(ctx):
        return "free"
    message = (ctx.get("message") or "").strip()
    if _UNCERTAINTY_RE.search(message):
        return "choice"
    ig = ctx.get("intent_graph") or {}
    confidence = (ig.get("confidence_scores") or {}).get("overall_confidence")
    if confidence is None:
        confidence = ig.get("overall_confidence")
    if isinstance(confidence, (int, float)) and confidence < 0.60:
        return "choice"
    if (ctx.get("avoidance_count") or 0) >= 2:
        return "choice"
    state = ctx.get("state") or ""
    if state in ("guided_discovery", "pillar_selection") and \
            not ctx.get("minimal_input"):
        return "choice"
    return "free"


def _next_ladder_stage(planner):
    stage = _QUESTION_LADDER[min(planner._ladder_idx, len(_QUESTION_LADDER) - 1)]
    planner._ladder_idx += 1
    return stage


def _reset_ladder(planner):
    planner._ladder_idx = 0


def _attach_quick_replies(decision, planner):
    if decision is None or decision.action not in _ASKING_ACTIONS:
        return
    ctx = planner._ctx or {}
    if planner.mode in _QUICK_REPLY_SUPPRESSED_MODES:
        return
    if planner._pending_recommendation:
        return
    if ctx.get("current_pillar"):
        return
    if ctx.get("has_topic_signal"):
        return
    if _is_rich_input(ctx):
        return
    meta = decision.metadata or {}
    if meta.get("quick_tree") or meta.get("force_choice"):
        return

    def _do_attach():
        decision.show_quick_replies = True
        decision.quick_replies = list(_QUICK_REPLY_ENTRY_BUTTONS)
        decision.quick_reply_type = _QUICK_REPLY_TYPE_CONVERSATION_ENTRY

    state = ctx.get("state") or ""
    if state in _QUICK_REPLY_OPEN_STATES or meta.get("greeting"):
        _do_attach()
        return
    message = (ctx.get("message") or "").strip()
    ig = ctx.get("intent_graph") or {}
    confidence = (ig.get("confidence_scores") or {}).get("overall_confidence")
    if confidence is None:
        confidence = ig.get("overall_confidence")
    low_confidence = isinstance(confidence, (int, float)) and confidence < 0.60
    if _UNCERTAINTY_RE.search(message) or low_confidence:
        _do_attach()