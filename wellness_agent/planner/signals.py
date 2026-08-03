import re
from .modes import ConversationMode
from .actions import PlannerAction, _ASKING_ACTIONS


_WELLNESS_TOPIC_WORDS = [
    "work", "sleep", "stress", "relation", "friend", "family", "exercise",
    "health", "mood", "feel", "anxious", "worry", "happy", "sad", "lonely",
    "tired", "eat", "food", "routine", "focus", "energy", "overwhelm",
    "burnout", "motivation", "procrastination", "nutrition", "money",
    "finances", "anxiety", "depressed",
]

_TOPIC_PATTERNS = {
    "sleep": [r"\bsleep", r"\binsomnia", r"\bbedtime\b", r"\btired", r"\bnap\b", r"\bnight\b"],
    "stress": [r"\bstress", r"\boverwhelm", r"\bpressure\b", r"\bburnout", r"\bdread\b"],
    "work": [r"\bwork\b", r"\bjob\b", r"\bcareer\b", r"\bboss\b", r"\bcolleague", r"\bdeadline", r"\boffice\b"],
    "relationships": [r"\brelationship", r"\bfriend", r"\bpartner\b", r"\bfamily\b", r"\blonely", r"\balone\b"],
    "mood": [r"\bmood\b", r"\bsad\b", r"\bdepressed\b", r"\banxious\b", r"\bworry\b", r"\bdown\b"],
    "motivation": [r"\bmotivation", r"\bdrive\b", r"\bprocrastinat", r"\bfocus\b", r"\bgoal\b"],
    "exercise": [r"\bexercise\b", r"\bworkout\b", r"\bgym\b", r"\bwalk", r"\byoga\b", r"\bfitness\b"],
    "nutrition": [r"\bnutrition\b", r"\bdiet\b", r"\bmeal\b", r"\bfood\b", r"\beat\b", r"\bhungry\b"],
    "routine": [r"\broutine\b", r"\bhabit\b", r"\bschedule\b", r"\bmorning\b", r"\bevening\b"],
    "finances": [r"\bfinance", r"\bmoney\b", r"\bbudget\b", r"\bdebt\b", r"\bbill\b"],
}

_CAPABILITY_RE = re.compile(
    r"\bwhat can you (?:do|help(?: me)?(?: with)?|assist|recommend|offer)\b|"
    r"\bwhat are you (?:able|capable) to do\b|"
    r"\bhow can you help\b|\bhow do you work\b|\bwhat do you do\b|"
    r"\bwhat (?:are|who is) you\b|\bare you a (?:robot|bot|ai|chatbot|human)\b|"
    r"\btell me about yourself\b|\bwhat'?s your (?:purpose|role|name)\b|"
    r"\bwhat can (?:this|the) (?:app|bot|companion) do\b|\byour (?:features|capabilities)\b|"
    r"\bwhat should i use (?:this|you) for\b",
    re.IGNORECASE,
)

_CASUAL_RE = re.compile(
    r"\btell me a joke\b|\bmake me laugh\b|\banother joke\b|\bhow'?s your day\b|"
    r"\bhow is your day going\b|"
    r"\bwhat (?:movies|music|books|songs|films|tv shows?) do you (?:like|enjoy|watch|listen to)\b|"
    r"\bwho'?s your favorite\b|\bdo you like (?:movies|music|games)\b|"
    r"\blet'?s (?:just )?chat\b|\bjust chatting\b|\bchat (?:casually|about anything)\b|"
    r"\bsmall talk\b|\btell me a (?:story|riddle|fun fact)\b|\bwhat did you do today\b|"
    r"\b(?:the )?weather\b|\bthe game last night\b",
    re.IGNORECASE,
)

_GOODBYE_RE = re.compile(
    r"\b(bye|goodbye|good night|see you|talk (to you )?later|catch you "
    r"later|i'?m (going|off) now|that'?s all for today|gotta go|"
    r"got to go|take care now|have a good (day|night))\b", re.IGNORECASE)

_QUESTION_START_RE = re.compile(
    r"^(?:why|what|how|when|where|which|who|can|could|would|should|"
    r"do|does|did|is|are|will|am)\b",
    re.IGNORECASE,
)

_RHETORICAL_QUESTION_RE = re.compile(
    r"\b(?:right|right there|eh|huh|isn'?t it|don'?t you think|"
    r"do you even care|who cares|does it matter|what difference does it make|"
    r"why bother|what'?s the (?:point|use))\??\s*$|"
    r"^who needs\b.*\?$",
    re.IGNORECASE,
)

_PROCESS_COMPLAINT_RE = re.compile(
    r"\bwhy do you keep\b|\b(?:same|the same|new|different) questions?\b|"
    r"\bkeep asking me\b|\bkeep asking the same\b|\bstop asking\b|\b(?:always|keep) asking\b|"
    r"\bare you (?:even )?(?:listening|real|human)\b|\bwhat'?s the point\b|"
    r"\b(?:this|it) (?:isn'?t|is not|ain'?t) helping\b|\byou'?re not helping\b|"
    r"\bwasting my time\b|\bi hate this\b|\bi'?m fed up\b|\bthis app\b",
    re.IGNORECASE,
)

_SWITCH_RE = re.compile(
    r"\b(?:let'?s|could we|can we|how about|what about|switch|change|"
    r"move on|talk about|discuss|i want to talk about|i'?d like to talk about|"
    r"i want to focus on|let'?s move to)\b.*\b"
    r"(?:work|sleep|stress|anxiety|mood|relationships?|family|friends?|"
    r"exercise|health|energy|motivation|focus|routine|nutrition|food|"
    r"finances|money|overwhelm|burnout|productivity|procrastination)\b",
    re.IGNORECASE,
)

_ACCEPT_RE = re.compile(
    r"^\s*(?:yes|yeah|yep|yup|sure|ok|okay|fine|alright|definitely|"
    r"absolutely|sounds good|sounds great|that works|that'?s great|"
    r"good idea|deal|let'?s do it|let'?s try|i'?m in|i'?ll try|i'?ll do it|"
    r"i will|works for me|good)\b",
    re.IGNORECASE,
)

_REJECT_RE = re.compile(
    r"^\s*(?:no|nah|nope|not really|not now|not right now|maybe later|"
    r"i don'?t think so|not for me|no thanks|skip|can'?t|i can'?t|"
    r"won'?t|don'?t want)\b",
    re.IGNORECASE,
)

_TIME_RE = re.compile(
    r"\b(?:tomorrow|tonight|today|this (?:week|weekend|morning|evening|"
    r"afternoon)|next week|monday|tuesday|wednesday|thursday|friday|"
    r"saturday|sunday|morning|afternoon|evening|after work|before bed|"
    r"weekend|at \d{1,2}(?::\d{2})?\s*(?:am|pm)?)\b",
    re.IGNORECASE,
)


def _is_capability(message):
    return bool(message) and bool(_CAPABILITY_RE.search(message))


def _is_casual(message):
    return bool(message) and bool(_CASUAL_RE.search(message))


def _is_goodbye(message):
    return bool(message) and bool(_GOODBYE_RE.search(message))


def _is_topic_switch(message, ig):
    if (ig.get("topic_shift") or ig.get("branch_change_requested")):
        return True
    if not message:
        return False
    lower = message.lower()
    if re.search(r"\b(?:back to|get back|go back|return to|back on)\b", lower):
        return False
    return bool(_SWITCH_RE.search(message))


def _is_direct_question(message):
    if not message:
        return False
    if len(message) <= 1:
        return False
    stripped = message.strip()
    if _CAPABILITY_RE.search(stripped) or _CASUAL_RE.search(stripped) \
            or _SWITCH_RE.search(stripped):
        return False
    if _PROCESS_COMPLAINT_RE.search(stripped) or _RHETORICAL_QUESTION_RE.search(stripped):
        return False
    if stripped.endswith("?"):
        return True
    return bool(_QUESTION_START_RE.match(stripped))


def _is_wellness_concern(message, ig):
    primary = (ig.get("primary_intent") or {}).get("intent", "")
    if primary in ("commitment", "goal_update", "correction", "crisis"):
        return True
    if not message:
        return False
    lower = message.lower()
    return any(word in lower for word in _WELLNESS_TOPIC_WORDS)


def _extract_target_topic(message):
    if not message:
        return None
    lower = message.lower()
    for pillar, patterns in _TOPIC_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, lower):
                return pillar
    return None