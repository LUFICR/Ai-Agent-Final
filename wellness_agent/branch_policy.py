"""Branch Completion Policy — deterministic per-branch slot completion engine.

Each branch (Sleep, Mental Health, Productivity, Physical Health,
Relationships) declares:
  - required_slots        : slots that define "investigation complete"
  - optional_slots        : bonus detail; never required for completion
  - completion_threshold  : how many required slots must be filled before the
                            branch completes (may be lower than the full set)
  - next_actions          : the terminal sequence once the branch completes
                            (PROVIDE_INSIGHT -> PROVIDE_RECOMMENDATION ->
                            CREATE_COMMITMENT -> ...)

evaluate_branch_completion() is the engine: it is called after EVERY user
message. It is deterministic (pure regex + intent-graph slot detection, never
the LLM) and state-free — the ConversationPlanner keeps the running "filled"
set across messages.

Branch completion means: no more discovery questions. The planner switches
to the branch's next_actions sequence, and the active topic is kept until the
user switches topics or the conversation ends.
"""

import re


# ─── Branch definitions ────────────────────────────────────────────────

BRANCH_DEFINITIONS = {
    "sleep": {
        "required_slots": ["duration", "quality", "consistency"],
        "optional_slots": [],
        "completion_threshold": 2,
        "next_actions": ["provide_insight", "provide_recommendation",
                         "create_commitment"],
    },
    "mental_health": {
        "required_slots": ["predominant_emotion", "duration", "impact"],
        "optional_slots": ["trigger", "severity"],
        "completion_threshold": 3,
        "next_actions": ["provide_insight", "provide_recommendation",
                         "create_commitment", "summarize"],
    },
    "productivity": {
        "required_slots": ["overwhelm", "procrastination", "focus"],
        "optional_slots": ["workload"],
        "completion_threshold": 2,
        "next_actions": ["provide_insight", "provide_recommendation",
                         "create_commitment"],
    },
    "physical_health": {
        "required_slots": ["activity", "frequency", "barrier"],
        "optional_slots": ["intensity", "goal"],
        "completion_threshold": 2,
        "next_actions": ["provide_insight", "provide_recommendation",
                         "create_commitment"],
    },
    "relationships": {
        "required_slots": ["relationship", "emotion", "duration"],
        "optional_slots": ["support", "trigger"],
        "completion_threshold": 2,
        "next_actions": ["provide_insight", "provide_recommendation",
                         "create_commitment"],
    },
}

PILLAR_BRANCH = {
    "sleep": "sleep",
    "stress": "mental_health",
    "mood": "mental_health",
    "work": "productivity",
    "motivation": "productivity",
    "routine": "productivity",
    "exercise": "physical_health",
    "nutrition": "physical_health",
    "relationships": "relationships",
    "finances": "mental_health",
}


def branch_for_pillar(pillar):
    if not pillar:
        return None
    return PILLAR_BRANCH.get(str(pillar).strip().lower())


# ─── Slot detection (deterministic regex, never the LLM) ───────────────

_DURATION_RE = re.compile(
    r"\bfor\s+(?:about|around|roughly|the\s+last|the\s+past)?\s*"
    r"(?:\d+\s+)?(?:day|days|week|weeks|month|months|year|years)\b|"
    r"\b(?:lately|recently|these\s+days|for\s+a\s+while|for\s+ages|"
    r"all\s+(?:the\s+)?time|since\s+(?:last|the)\s+week)\b",
    re.IGNORECASE,
)

_SLEEP_HOURS_RE = re.compile(
    r"\b\d+\s*(?:[-~to]\s*\d+)?\s*hours?\b|"
    r"\b(?:one|two|three|four|five|six|seven|eight|nine|ten)\s+hours?\b",
    re.IGNORECASE,
)

_TRIGGER_RE = re.compile(
    r"\b(?:because|coz|cause|since)\b|\btrigger(?:ed|s)?\b|"
    r"\bstarted\s+(?:when|after)\b|\bwhen\s+(?:i|it|work)\b|"
    r"\bafter\s+(?:i|work|that)\b",
    re.IGNORECASE,
)

_BRANCH_SLOT_PATTERNS = {
    "sleep": {
        "duration": re.compile(_DURATION_RE.pattern + "|" + _SLEEP_HOURS_RE.pattern,
                               re.IGNORECASE),
        "quality": re.compile(
            r"\bquality\b|\bpoor(?:ly)?\b|"
            r"\b(?:bad|terrible|horrible|awful)\s+sleep\b|\bnot\s+restful\b|"
            r"\brestless\b|\btoss(?:ing)?\s+(?:and|&)\s+turn(?:ing)?\b|"
            r"\bshallow\b|\blight\s+(?:sleep|sleeper)\b|\bnot\s+deep\b|"
            r"\bunrefreshing\b",
            re.IGNORECASE),
        "consistency": re.compile(
            r"\bwake(?:s|d|ing)?\s+up\b|\bwaking\s+up\b|\binterrupt(?:ed|s)?\b|"
            r"\bwake(?:s|d)?\s+at\b|\bevery\s+night\b|"
            r"\bcan'?t\s+(?:fall|get\s+to)\s+(?:asleep|sleep)\b|"
            r"\b(?:hard|difficulty)\s+(?:falling|getting)\s+asleep\b|"
            r"\bup\s+at\s+night\b|\b3\s*am\b|"
            r"\bearly\s+morning\s+(?:waking|awake)\b",
            re.IGNORECASE),
    },
    "mental_health": {
        "predominant_emotion": re.compile(
            r"\bsad\b|\bdepressed?\b|\bdepression\b|\bdown\b|\banxious?\b|"
            r"\banxiety\b|\bworr(?:y|ied|ies)\b|\boverwhelmed?\b|"
            r"\bstress(?:ed)?\b|\blonely?\b|\balone\b|\bangry\b|"
            r"\bfrustrated?\b|\bfrustration\b|\bflat\b|\bempty\b|"
            r"\bhopeless\b|\bunmotivated\b|\bunhappy\b",
            re.IGNORECASE),
        "duration": _DURATION_RE,
        "impact": re.compile(
            r"\baffect(?:s|ing|ed)?\b|\bimpact(?:s|ing|ed)?\b|\bruin(?:s|ing|ed)?\b|"
            r"\bcan'?t\s+(?:focus|concentrate|function|work|get\s+through|sleep|do\s+anything)\b|"
            r"\bhard\s+to\s+(?:function|work|focus|get\s+through)\b|"
            r"\bfalling\s+behind\b|\bsuffering\b|\bstruggling\s+to\b|"
            r"\bget\s+through\s+the\s+day\b|\b(?:barely|cant)\s+(?:function|cope)\b|"
            r"\bnot\s+enjoy(?:ing)?\b",
            re.IGNORECASE),
        "trigger": _TRIGGER_RE,
        "severity": re.compile(
            r"\bsevere\b|\bextreme\b|\bcrippling\b|\bunbearable\b|\bintense\b|"
            r"\breally\s+(?:bad|hard|tough|rough|awful)\b|\bcan'?t\s+cope\b|"
            r"\bworst\b|\bawful\b|\bterrible\b",
            re.IGNORECASE),
    },
    "productivity": {
        "overwhelm": re.compile(
            r"\boverwhelm(?:ed|ing)?\b|\btoo\s+much\b|\bdrowning\b|"
            r"\bcan'?t\s+keep\s+up\b|\bswamped\b|\bburn(?:ed|t)?\s*out\b|"
            r"\bburnt\s+out\b",
            re.IGNORECASE),
        "procrastination": re.compile(
            r"\bprocrastinat\b|\bput(?:ting)?\s+(?:\w+\s+)?off\b|\bavoid(?:ing)?\b|"
            r"\bcan'?t\s+start\b|\bdelay(?:ing)?\b|\blast\s+minute\b|\bstuck\b",
            re.IGNORECASE),
        "focus": re.compile(
            r"\bfocus\b|\bconcentrat\b|\battention\b|\bscattered\b|"
            r"\bcan'?t\s+focus\b|\bdistract(?:ed|ion)?\b|\bwandering\b",
            re.IGNORECASE),
        "workload": re.compile(
            r"\bworkload\b|\bdeadline(?:s)?\b|\btasks?\b|\bmeetings?\b|"
            r"\bto-do\b|\bstack(?:s)?\b",
            re.IGNORECASE),
    },
    "physical_health": {
        "activity": re.compile(
            r"\bgym\b|\bwork\s*out\b|\bworkout(?:s)?\b|\bexercis(?:e|ing|es)\b|"
            r"\brun(?:ning)?\b|\bjog(?:ging)?\b|\bwalk(?:ing)?\b|\byoga\b|"
            r"\bcycl(?:e|ing)\b|\bswim(?:ming)?\b|\bstrength\b|\btraining\b|"
            r"\blift(?:ing)?\b|\beat(?:ing)?\b|\bdiet\b|\bmeal(?:s)?\b|"
            r"\bfood\b|\bnutrition\b|\bsnack(?:ing)?\b",
            re.IGNORECASE),
        "frequency": re.compile(
            r"\b\d+\s*(?:times?|x|days?)\s*(?:a|per|this|every)\s*(?:week|day|month)\b|"
            r"\b(?:once|twice|three\s+times)\s+(?:a|per|this)\s+(?:week|day|month)\b|"
            r"\b(?:every|each)\s+day\b|\bdaily\b|\bweekly\b|\bmost\s+days\b",
            re.IGNORECASE),
        "barrier": re.compile(
            r"\bno\s+time\b|\btoo\s+tired\b|\bno\s+energy\b|\bpain\b|\bhurt(?:s)?\b|"
            r"\blazy\b|\bno\s+motivation\b|\bcan'?t\s+afford\b|\bexpensive\b|"
            r"\b(?:knee|back|shoulder|ankle|hip)\b.{0,25}\b(?:hurt|pain|sore)\b|"
            r"\bbusy\b|\bweather\b",
            re.IGNORECASE),
        "intensity": re.compile(
            r"\bintense?\b|\bheavy\b|\bhigh\s+intensity\b|\bstrenuous\b|"
            r"\bmoderate\b|\bgentle\b",
            re.IGNORECASE),
        "goal": re.compile(
            r"\bwant\s+to\s+(?:lose|gain|build|improve|run|get\s+fit|be)\b|"
            r"\bgoal(?:s)?\b|\bfit\s+into\b|\btarget\b",
            re.IGNORECASE),
    },
    "relationships": {
        "relationship": re.compile(
            r"\bpartner\b|\bspouse\b|\bhusband\b|\bwife\b|\bgirlfriend\b|"
            r"\bboyfriend\b|\bfriend(?:s)?\b|\bfriendship(?:s)?\b|\bfamily\b|"
            r"\bcolleague(?:s)?\b|\bmom\b|\bmum\b|\bmother\b|\bdad\b|\bfather\b|"
            r"\bsibling(?:s)?\b|\bparent(?:s)?\b|\broommate(?:s)?\b|\bmarriage\b",
            re.IGNORECASE),
        "emotion": re.compile(
            r"\blonely?\b|\balone\b|\bisolated?\b|\bhurt(?:s|ing)?\b|"
            r"\bfrustrated?\b|\bresentful?\b|\bargu(?:e|ing|d|ment)\b|"
            r"\bfight(?:ing|s)?\b|\bignored?\b|\bunappreciated\b|\bdistant\b|"
            r"\bdisconnected\b|\bjealous\b|\bguilty\b|\bsad\b|\banxious?\b|"
            r"\bbetrayed\b|\bunsupported\b",
            re.IGNORECASE),
        "duration": _DURATION_RE,
        "support": re.compile(
            r"\bno\s+one\s+to\s+(?:talk|turn)\b|\bsupport(?:ive)?\b|"
            r"\bnot\s+there\s+for\b|\bunderstood\b|\bcare(?:s)?\b|\blistening?\b",
            re.IGNORECASE),
        "trigger": _TRIGGER_RE,
    },
}

# intent-graph slot names (IntentResolver) -> branch slot names
_IG_SLOT_MAP = {
    "sleep_hours": "duration",
    "duration": "duration",
    "stress_level": "predominant_emotion",
    "energy_level": "barrier",
    "exercise_times": "frequency",
}


def detect_slot_fills(message, pillar, intent_graph=None):
    """Deterministic slot fill detection for one message (never the LLM).

    Combines the IntentResolver's `new_slots_detected` entries with regex
    detection of the branch's own slots. Returns the set of filled slot
    names for the pillar's branch (empty when the message carries no
    evidence for that branch).
    """
    branch = branch_for_pillar(pillar)
    if branch is None:
        return set()
    patterns = _BRANCH_SLOT_PATTERNS.get(branch, {})
    fills = set()
    ig = intent_graph or {}
    for slot in ig.get("new_slots_detected") or []:
        name = slot.get("slot") if isinstance(slot, dict) else slot
        mapped = _IG_SLOT_MAP.get(name)
        if mapped and mapped in patterns:
            fills.add(mapped)
    text = (message or "").strip().lower()
    if text:
        for slot_name, pattern in patterns.items():
            if pattern.search(text):
                fills.add(slot_name)
    return fills


def evaluate_branch_completion(message, pillar, intent_graph=None, filled=None):
    """evaluateBranchCompletion() — pure evaluation of one message.

    `filled` is the running set of already-filled slots (the planner keeps
    it across messages). Returns a summary dict or None when the pillar has
    no branch:
      branch, pillar, filled, required_filled, missing,
      completed, threshold, next_actions
    """
    branch = branch_for_pillar(pillar)
    if branch is None:
        return None
    definition = BRANCH_DEFINITIONS[branch]
    running = set(filled or ())
    running.update(detect_slot_fills(message, pillar, intent_graph))
    required = set(definition["required_slots"])
    required_filled = required & running
    return {
        "branch": branch,
        "pillar": pillar,
        "filled": sorted(running),
        "required_filled": sorted(required_filled),
        "missing": sorted(required - running),
        "completed": len(required_filled) >= definition["completion_threshold"],
        "threshold": definition["completion_threshold"],
        "next_actions": list(definition["next_actions"]),
    }
