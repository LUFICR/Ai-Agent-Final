"""Intent Resolver 2.0 — deterministic IntentGraph engine (RFC-001 Ch2).

The Intent Resolution System (RFC-001 Ch2.1) is the first decision-making
component executed after every user message. This engine replaces the old
single-intent detection with an adaptive resolver that:

- gives free text higher priority than UI buttons (Principle 1)
- detects multiple simultaneous intents and returns an IntentGraph
  (Ch2.3, ADR-002) instead of a single label
- never resets the conversation unnecessarily: branch continuity is the
  default and only explicit topic changes request a switch (Algorithm 7/8)
- respects the active branch (context matching boosts same-branch intent)
- detects topic changes, corrections, interruptions and emotional shifts
  as first-class signals
- separates emotional intent from task intent (Ch2.2 Intent 8)
- returns per-intent confidence scores (Algorithm 2) and reasoning metadata
- is fully deterministic: the same message always produces the same graph
  (Ch2.4: the LLM may assist semantics, the orchestrator owns routing)

The engine SHALL NEVER modify RuntimeContext: it reads only its engine
input and returns one immutable EngineUpdate whose data owns the
`intent_graph` runtime field (M8 ownership: intent_resolver).

Safety: crisis detection reuses the rule-based RISK_PATTERNS
(nlp_utils.detect_risk) — never the LLM (project safety convention).
"""

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from ..utils.nlp_utils import EMOTION_KEYWORDS, detect_risk, \
    extract_numeric_value
from .diagnostics import Diagnostic
from .engine_update import EngineUpdate
from .runtime_engine import BaseEngine, EngineCategory, EngineMetadata

# ─── Intent priority table (RFC-001 Ch2.2 Intent Priority) ─────────────
# Lower number = higher priority. meta/unknown are appended (not in the RFC
# table): meta sits between rejection and greeting; unknown is last.
INTENT_PRIORITIES = {
    "crisis": 1,
    "correction": 2,
    "commitment": 3,
    "goal_update": 4,
    "answer": 5,
    "confirmation": 5,
    "emotional_expression": 6,
    "topic_change": 7,
    "clarification": 8,
    "additional_information": 9,
    "question": 10,
    "success": 11,
    "failure": 12,
    "rejection": 13,
    "meta": 14,
    "greeting": 15,
    "small_talk": 16,
    "goodbye": 17,
    "unknown": 20,
}

# Confidence levels (RFC-001 Ch2.2): >=0.80 high, 0.60-0.79 medium,
# 0.40-0.59 low (clarify), <0.40 unknown (ask).
PRIMARY_THRESHOLD = 0.60          # below this, clarification is required
AMBIGUITY_GAP = 0.10              # Ch2.2: <10% gap between top candidates

# Topic vocabulary aligned with the existing category tree
# (mental/productivity/physical sub-categories in _generate_response).
# Words that are pure emotion labels ("sad", "tired", ...) are NOT listed as
# topic keywords — they resolve to emotional_expression instead, keeping
# emotional intent separate from task intent (Ch2.2 Intent 8).
_TOPIC_KEYWORDS = {
    "sleep": ["sleep", "sleeping", "slept", "insomnia", "nap", "bedtime",
              "can't sleep", "cant sleep", "tossing and turning",
              "wake up", "waking up", "sleep hours", "hours of sleep"],
    "energy": ["energy", "energetic", "fatigue", "exhausted", "drained",
               "worn out", "lethargic", "tired out", "no energy",
               "low energy", "burned out", "burnt out", "burnout"],
    "stress": ["stress", "stressed", "pressure", "overwhelm", "overwhelmed",
               "burnout", "burned out", "burnt out", "anxiety", "anxious",
               "worry", "worried", "panic", "tense", "racing"],
    "work": ["work", "working", "job", "career", "boss", "colleague",
             "deadline", "workload", "office", "coworker", "layoff",
             "promotion", "work thing", "my team"],
    "relationships": ["relationship", "partner", "boyfriend", "girlfriend",
                      "husband", "wife", "marriage", "married", "family",
                      "friend", "friends", "mom", "dad", "mother", "father",
                      "sister", "brother", "lonely", "alone", "isolated",
                      "disconnected"],
    "mood": ["depressed", "depression", "hopeless", "crying", "tearful",
             "low mood", "unhappy", "miserable", "gloomy", "sorrow",
             "heartbroken"],
    "anxiety": ["anxiety", "anxious", "worried", "nervous", "panic",
                "racing thoughts", "overthinking", "restless", "on edge",
                "fear", "dread"],
    "motivation": ["motivation", "motivated", "unmotivated", "procrastin",
                   "can't start", "cant start", "no drive", "stuck",
                   "no motivation"],
    "focus": ["focus", "focused", "distract", "concentration",
              "can't focus", "cant focus", "attention", "scattered"],
    "productivity": ["productivity", "productive", "procrastination",
                     "wasting time", "unproductive"],
    "exercise": ["exercise", "exercising", "workout", "gym", "running",
                 "walking", "walk", "yoga", "training", "work out",
                 "working out", "movement", "active"],
    "nutrition": ["nutrition", "food", "eating", "diet", "meal", "meals",
                  "eating habits", "caffeine", "coffee", "drinking"],
    "physical": ["physical", "health", "body", "pain", "headache", "sick",
                 "ill", "aching"],
    "work_life_balance": ["work-life", "work life", "balance", "boundaries",
                          "burning the candle"],
}

# Strong topic keywords raise single-hit confidence; weak ones (overlapping
# with emotion vocabulary) stay medium and allow ambiguity detection.
_STRONG_TOPIC_WORDS = frozenset({
    "sleep", "sleeping", "slept", "insomnia", "nap", "bedtime",
    "energy", "fatigue", "stress", "stressed", "anxiety", "anxious",
    "work", "working", "job", "career", "deadline",
    "relationship", "partner", "marriage", "married", "family",
    "depressed", "depression", "panic", "procrastin", "focus",
    "exercise", "workout", "gym", "running", "nutrition", "diet",
})

# Branch families: a topic belongs to the active branch's family when it
# shares a family set — used for branch continuity (Algorithm 7) and to
# prevent unnecessary switches (secondary intents never switch branches).
_BRANCH_FAMILIES = {
    "sleep": frozenset({"sleep", "energy"}),
    "energy": frozenset({"energy", "sleep", "exercise"}),
    "stress": frozenset({"stress", "anxiety", "work", "burnout"}),
    "work": frozenset({"work", "productivity", "work_life_balance", "stress",
                       "burnout"}),
    "relationships": frozenset({"relationships", "loneliness", "mood"}),
    "loneliness": frozenset({"loneliness", "relationships", "mood"}),
    "mood": frozenset({"mood", "loneliness", "anxiety"}),
    "anxiety": frozenset({"anxiety", "stress", "mood", "sleep"}),
    "motivation": frozenset({"motivation", "productivity", "focus"}),
    "focus": frozenset({"focus", "productivity", "motivation"}),
    "productivity": frozenset({"productivity", "work", "focus",
                               "motivation", "work_life_balance"}),
    "exercise": frozenset({"exercise", "energy", "physical"}),
    "nutrition": frozenset({"nutrition", "physical", "exercise"}),
    "physical": frozenset({"physical", "exercise", "nutrition", "sleep"}),
    "work_life_balance": frozenset({"work_life_balance", "work",
                                    "productivity", "stress"}),
}

_NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                 "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
                 "eleven": 11, "twelve": 12}

_NEGATION_RE = re.compile(
    r"\b(not|never|no|don't|dont|doesn't|doesnt|didn't|didnt|can't|cant|"
    r"won't|wont|isn't|isnt|aren't|arent|wasn't|wasnt|without|hardly|"
    r"barely)\b")

# Idioms that must never be treated as their surface topic.
_IDIOM_BLOCKLIST = (
    "sleep on it", "sleeping on it", "slept on it", "sleep it off",
)

_GREETING_RE = re.compile(
    r"^(hi|hii+|hello|hey|heyy+|yo|good morning|good afternoon|"
    r"good evening|hiya|howdy|greetings)[\s,.!]*$|"
    r"\b(i'?m back|i am back|good to be back|nice to see you again|"
    r"long time no see)\b", re.IGNORECASE)

_GOODBYE_RE = re.compile(
    r"\b(bye|goodbye|good night|see you|talk (to you )?later|catch you "
    r"later|i'?m (going|off) now|that'?s all for today|gotta go|"
    r"got to go|take care now|have a good (day|night))\b", re.IGNORECASE)

_QUESTION_RE = re.compile(
    r"\?|^(why|how|what|when|where|who|which|can you|could you|do you|"
    r"does it|is it|are you|should i|should we|will it|would it|am i|"
    r"is that|what'?s|how'?s|what do you|how do i|tell me about)\b",
    re.IGNORECASE)

_CLARIFICATION_RE = re.compile(
    r"\b(what do you mean|what does that mean|can you explain|"
    r"could you explain|i don'?t understand|i dont understand|"
    r"i'?m confused|im confused|say that again|rephrase|"
    r"i'?m not sure what you mean|huh\??)\b", re.IGNORECASE)

_CORRECTION_RE = re.compile(
    r"\b(actually|correction|i meant|i mean|wait|no wait|hold on|"
    r"that'?s (not|wrong)|that was wrong|i changed|not anymore|"
    r"no longer|used to think|i take that back|forget what i said|"
    r"scratch that|my mistake|i was wrong)\b", re.IGNORECASE)

_STRONG_CORRECTION_RE = re.compile(
    r"\b(anymore|no longer|not anymore|i was wrong|my mistake|that'?s not|"
    r"i changed|correction)\b", re.IGNORECASE)

_TOPIC_CHANGE_RE = re.compile(
    r"\b(let'?s (talk|switch|move|change|discuss)|i (?:really|actually|"
    r"just|now|instead|also)? ?want to talk about|"
    r"i'?d like to talk about|i'?d rather talk|switch (to|topics)|"
    r"change the subject|different topic|forget (about )?(it|that|this|"
    r"sleep|stress|work)|never mind (that|this|it)|not talk about (it|that|"
    r"this) anymore|i don'?t want to talk about|i dont want to talk about|"
    r"moving on|let'?s move on|drop it|leave it)\b", re.IGNORECASE)

_COMMITMENT_RE = re.compile(
    r"\b(i'?ll|i will|i'?m going to|i am going to|i'?m gonna|i promis\w*|"
    r"i'?ll try|i will try|i'?ll start|i will start|i'?m starting|"
    r"i decided to|i'?ve decided to|starting (today|tomorrow|monday))\b",
    re.IGNORECASE)

_GOAL_UPDATE_RE = re.compile(
    r"\b(my (new )?goal (is|now)|i want to focus on|i want to work on|"
    r"i'?m focusing on|im focusing on|i'?ve decided my goal|"
    r"i decided to focus)\b", re.IGNORECASE)

_SUCCESS_RE = re.compile(
    r"\b(slept well|slept great|slept better|"
    r"slept (?:one|two|three|four|five|six|seven|eight|nine|ten|\d+) hours|"
    r"i did it|i managed|managed to|improved|improvement|"
    r"getting better|feeling better|i exercised|went to the gym|"
    r"stuck to|i finished|worked out|did my (workout|walk|run|yoga)|"
    r"three times this week|made progress|progress today|celebrat\w*)\b",
    re.IGNORECASE)

_FAILURE_RE = re.compile(
    r"\b(i failed|failed again|i couldn'?t|could not|i skipped|"
    r"skipped (everything|again)|gave up|relapse\w*|i missed|"
    r"i didn'?t do|didn'?t do anything|did not do anything|nothing again|"
    r"fell off (the )?wagon|i fell off|messed up again|messed up)\b",
    re.IGNORECASE)

_REJECTION_RE = re.compile(
    r"\b(i don'?t want to|i dont want to|i won'?t|i will not|i'?m not "
    r"interested|im not interested|no thanks|not for me|i'?d rather not|"
    r"that doesn'?t work|that wont work|i'?m not doing|im not doing|"
    r"i refuse)\b", re.IGNORECASE)

_SMALL_TALK_RE = re.compile(
    r"\b(how are you|how are ya|how'?s it going|how is it going|what'?s up|"
    r"whats up|how are things|how'?s your day|how is your day|"
    r"how have you been|what'?s new|whats new|long time|just checking in|"
    r"how do you do)\b", re.IGNORECASE)

_QUESTION_START_RE = re.compile(
    r"^(why|what|how|when|where|who|which|does|do|did|is|are|was|were|"
    r"can|could|would|should|will)\b", re.IGNORECASE)

_QUESTION_YOU_RE = re.compile(
    r"\b(do|does|did|can|could|would|should|will|are|is|am)\s+"
    r"(you|it|that|there|this)\b", re.IGNORECASE)

_META_RE = re.compile(
    r"\b(who are you|what are you|what can you do|how do you work|"
    r"are you (a )?(robot|human|real|ai)|are you real|are you human|"
    r"is this anonymous|do you (remember|store|keep|share)|"
    r"can you (do )?(anything|cook)|what'?s your name|what is your name|"
    r"are you listening)\b", re.IGNORECASE)

_SLOT_PATTERNS = {
    "sleep_hours": re.compile(
        r"\b((?:about|around|only|usually|roughly)?\s*"
        r"(\d+|one|two|three|four|five|six|seven|eight|nine|ten|twelve)"
        r"(?:\s*[-~to]\s*\d+)?\s*hours)\b", re.IGNORECASE),
    "duration": re.compile(
        r"\bfor\s+(?:about|around|roughly|the last|the past)?\s*"
        r"(\d+|a few|a couple|one|two|three|four|five|six|seven|eight|nine|"
        r"ten)\s*(day|days|week|weeks|month|months|year|years)\b",
        re.IGNORECASE),
    "stress_level": re.compile(
        r"\b(high|severe|extreme|moderate|medium|mild|low|a lot of|"
        r"a ton of)\s*(?:stress|pressure|anxiety)\b", re.IGNORECASE),
    "energy_level": re.compile(
        r"\b(low|no|zero)\s+(?:energy|motivation|drive)\b|"
        r"\benergy\s+(?:is\s+)?(low|high|zero)\b", re.IGNORECASE),
    "exercise_times": re.compile(
        r"\b(\d+)\s*(?:times?|x)\s*(?:a|per|this)\s*week\b|"
        r"\b(exercised|worked out|went to the gym)\s+(\d+)\s*times\b",
        re.IGNORECASE),
}

_ADDITIVE_MARKERS = re.compile(r"\b(also|too|and|plus|additionally|"
                               r"in addition|on top of that|as well)\b",
                               re.IGNORECASE)

_TEMPORAL_EXTENT_RE = re.compile(
    r"\b(all week|for weeks|for months|for days|for a while|every day|"
    r"lately|recently|this week|these days|since (last|the) week|"
    r"for the last|for the past|nowadays|all the time)\b", re.IGNORECASE)

_CONCRETE_QUESTION_RE = re.compile(
    r"\b(how many|how much|how often|how long|what time|when do|hours|"
    r"times a week|times per week|minutes|per night)\b", re.IGNORECASE)


# ─── Graph structures (RFC-001 Ch2.2 Intent Object, Ch2.3 Intent Graph) ─

@dataclass(frozen=True)
class Intent:
    """One detected intent (RFC-001 Ch2.2 Intent Object)."""

    intent: str
    confidence: float
    priority: int
    level: str = "secondary"           # primary / secondary / background
    requires_branch_change: bool = False
    requires_clarification: bool = False
    slot_updates: tuple = ()
    notes: str = ""
    evidence: tuple = ()               # signal descriptions

    def to_dict(self) -> dict:
        return {
            "intent": self.intent,
            "confidence": round(self.confidence, 3),
            "priority": self.priority,
            "level": self.level,
            "requires_branch_change": self.requires_branch_change,
            "requires_clarification": self.requires_clarification,
            "slot_updates": list(self.slot_updates),
            "notes": self.notes,
            "evidence": list(self.evidence),
        }


@dataclass(frozen=True)
class IntentRelationship:
    """Relationship between two intents (RFC-001 Ch2.3)."""

    type: str                            # cause/effect/dependency/conflict/
    source: str = ""                     # reinforcement/independent
    target: str = ""
    confidence: float = 0.5

    def to_dict(self) -> dict:
        return {"type": self.type, "source": self.source,
                "target": self.target, "confidence": round(self.confidence, 3)}


@dataclass(frozen=True)
class IntentGraph:
    """Structured representation of all intents in one message (Ch2.3).

    Ephemeral by design: the graph exists only during orchestration and is
    never stored as long-term memory.
    """

    primary_intent: Intent
    secondary_intents: tuple = ()
    background_intents: tuple = ()
    relationships: tuple = ()
    overall_confidence: float = 0.0
    continue_branch: bool = True
    branch_change_requested: bool = False
    answered_current_question: bool = False
    new_slots_detected: tuple = ()
    topic_shift: bool = False
    emotion_shift: bool = False
    interruption: bool = False
    correction: bool = False
    requires_clarification: bool = False
    reason: str = ""
    reasoning: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "primary_intent": self.primary_intent.to_dict(),
            "secondary_intents": [i.to_dict() for i in self.secondary_intents],
            "background_intents": [i.to_dict() for i in self.background_intents],
            "relationships": [r.to_dict() for r in self.relationships],
            "overall_confidence": round(self.overall_confidence, 3),
            "continue_branch": self.continue_branch,
            "branch_change_requested": self.branch_change_requested,
            "answered_current_question": self.answered_current_question,
            "new_slots_detected": list(self.new_slots_detected),
            "topic_shift": self.topic_shift,
            "emotion_shift": self.emotion_shift,
            "interruption": self.interruption,
            "correction": self.correction,
            "requires_clarification": self.requires_clarification,
            "reason": self.reason,
            "reasoning": self.reasoning,
        }


# ─── Deterministic classification core ─────────────────────────────────

def _normalize(message: str) -> str:
    return re.sub(r"\s+", " ", (message or "").strip().lower())


def _words_with_positions(text: str) -> List[Tuple[str, int, int]]:
    return [(m.group(0), m.start(), m.end())
            for m in re.finditer(r"[a-z']+|\d+", text)]


def _is_negated(text: str, tokens: List[Tuple[str, int, int]],
                target_start: int, window: int = 4) -> bool:
    """True when a negation word appears within `window` tokens before a
    matched word — handles 'not stressed', 'never sad', "don't want", etc.
    """
    target_index = None
    for index, (word, start, end) in enumerate(tokens):
        if start == target_start:
            target_index = index
            break
    if target_index is None:
        return False
    target_start_pos = tokens[target_index][1]
    barriers = [m.start() for m in re.finditer(
        r"[,.;!?()]|\b(?:but|yet|however|although|though|while|because|"
        r"so|instead|anyway)\b", text)]
    for index in range(max(0, target_index - window), target_index):
        word, start, end = tokens[index]
        if any(start < b < target_start_pos for b in barriers):
            continue
        if _NEGATION_RE.match(word):
            return True
    return False


def _negated_spans(text: str) -> List[Tuple[int, int]]:
    """Word spans covered by a nearby negation (used to skip negated
    topic/emotion keywords — adversarial-safe, e.g. 'I'm NOT stressed').

    Clause boundaries (',', 'but', 'yet', 'however', ...) stop the negation
    window so 'I am not stressed but my sleep is broken' keeps 'sleep'."""
    tokens = _words_with_positions(text)
    barriers = [m.start() for m in re.finditer(
        r"[,.;!?()]|\b(?:but|yet|however|although|though|while|because|"
        r"so|instead|anyway)\b", text)]
    spans = []
    for index, (word, start, end) in enumerate(tokens):
        for prev_index in range(max(0, index - 4), index):
            prev_word, prev_start, prev_end = tokens[prev_index]
            if any(prev_start < b < start for b in barriers):
                continue
            if _NEGATION_RE.match(prev_word):
                spans.append((start, end))
                break
    return spans


def _detect_emotions(text: str, negated_spans) -> List[Intent]:
    # Negation-aware counts: keywords inside a negated span ("not stressed",
    # "I am not tired") are dropped (adversarial-safe).
    intents = []
    for label, keywords in EMOTION_KEYWORDS.items():
        if not keywords:
            continue
        hits = _keyword_hits(text, keywords, negated_spans)
        count = len(hits)
        if not count:
            continue
        confidence = min(0.95, 0.50 + 0.08 * count)
        if label in ("stressed", "tired") and count == 1:
            confidence = 0.55  # single-word fatigue emotion: ambiguous (F1)
        intents.append(Intent(
            intent="emotional_expression",
            confidence=confidence,
            priority=INTENT_PRIORITIES["emotional_expression"],
            notes="emotion=%s" % label,
            evidence=["emotion keyword '%s' x%d" % (label, count)],
        ))
    return intents


def _keyword_hits(text: str, keywords, negated_spans):
    """Boundary-aware keyword matching with overlap dedupe.

    Each keyword is matched as a whole word (so "ill" never matches inside
    "still" and "sleep" never double-counts inside "can't sleep"); when two
    matches overlap, the longest one wins.
    """
    tokens = _words_with_positions(text)
    matches = []
    for kw in keywords:
        for m in re.finditer(r"\b(?:%s)\b" % re.escape(kw), text):
            start, end = m.start(), m.end()
            if any(s <= start < e for s, e in negated_spans):
                continue
            if _is_negated(text, tokens, start):
                continue
            matches.append((start, end, kw))
    matches.sort(key=lambda m: (m[1] - m[0], m[0]), reverse=True)
    kept = []
    for start, end, kw in matches:
        if any(start < other_end and other_start < end
               for other_start, other_end, _ in kept):
            continue
        kept.append((start, end, kw))
    kept.sort(key=lambda m: m[0])
    return [kw for _start, _end, kw in kept]


def _detect_topics(text: str, negated_spans,
                   skip_labels: frozenset) -> List[Tuple[str, Intent]]:
    """Detect topic intents; returns (topic_name, intent) pairs.

    `skip_labels`: bare emotion-label words already covered by
    emotional_expression (e.g. 'sad') are not topic evidence, keeping
    emotional intent separate from task intent.
    """
    matches = {}
    for topic, keywords in _TOPIC_KEYWORDS.items():
        hits = [kw for kw in keywords
                if kw not in skip_labels and
                kw in _keyword_hits(text, keywords, negated_spans)]
        if hits:
            single = len(hits) == 1
            strong = any(word in _STRONG_TOPIC_WORDS
                         for word in hits[0].replace("'", "").split())
            base = 0.72 if (single and strong) else 0.61
            confidence = min(0.95, base + 0.05 * (len(hits) - 1))
            matches[topic] = Intent(
                intent="additional_information",
                confidence=confidence,
                priority=INTENT_PRIORITIES["additional_information"],
                notes="topic=%s" % topic,
                evidence=["topic keyword '%s'" % hits[0]] + hits[1:],
            )
    return sorted(matches.items(), key=lambda kv: -kv[1].confidence)


def _detect_answer(message: str, previous_question: str
                   ) -> Tuple[Optional[Intent], str]:
    """Answer detection (Principle 1 + Algorithm 7): free text answering
    the previous AI question advances without any button selection.

    Concrete questions ("how many hours...") need slots or topic overlap;
    open questions ("what area...") accept any substantive topic message.
    """
    q = _normalize(previous_question)
    if not q or "?" not in q or not message.strip():
        return None, ""
    if _QUESTION_RE.match(message.strip()):
        return None, ""          # the user is asking, not answering
    if _CLARIFICATION_RE.search(message) or _GREETING_RE.search(message):
        return None, ""
    if _TOPIC_CHANGE_RE.search(message):
        return None, ""

    slots = _extract_slots(message, previous_question)
    text = _normalize(message)
    tokens = [w for w, s, e in _words_with_positions(text)]
    topics = [t for t, i in _detect_topics(text, [], frozenset())]
    concrete = bool(_CONCRETE_QUESTION_RE.search(q))
    overlap = False
    answered = False
    reason = ""
    if slots:
        answered = True
        reason = "slot values extracted: %s" % ",".join(
            sorted(s["slot"] for s in slots))
    elif concrete:
        overlap = any(t in q for t in topics)
        if overlap:
            answered = True
            reason = "topic overlaps the pending question"
        elif len(tokens) <= 4 and any(t in q for t in
                                      ("hours", "times", "level", "often")):
            answered = True
            reason = "short response to concrete question"
    else:  # open question
        if topics:
            answered = True
            reason = "open question answered with a topic"
        elif len(tokens) <= 4 and not _SMALL_TALK_RE.search(message):
            answered = True
            reason = "short response to open question"

    if answered:
        confidence = 0.80 if slots else 0.74
        if concrete and overlap:
            confidence = min(0.94, confidence + 0.10)
        intent = Intent(
            intent="answer",
            confidence=confidence,
            priority=INTENT_PRIORITIES["answer"],
            notes="answered previous question",
            evidence=["pending question in context", reason],
        )
        return intent, reason
    return None, ""


def _detect_interruption(message: str, previous_question: str,
                         answered: bool) -> bool:
    """A pending question existed, the user did not answer it, and the
    message carries different content (RFC-001 Ch2.1: detect interruptions).
    """
    text = _normalize(message)
    q = _normalize(previous_question)
    if not q or "?" not in q or answered:
        return False
    if not message.strip() or len(text.split()) < 3:
        return False
    if (_QUESTION_RE.match(message.strip()) or _GREETING_RE.search(message)
            or _GOODBYE_RE.search(message) or _CLARIFICATION_RE.search(message)
            or _SMALL_TALK_RE.search(message) or _TOPIC_CHANGE_RE.search(message)):
        return False
    return True


def _find_fact_contradiction(text: str, memory_facts: List[dict]) -> Optional[str]:
    """Detect a contradiction between the message and a stored numeric fact.

    Example: memory says sleep_hours=5, message says "seven hours now".
    Only facts with extractable numbers are compared; the message must carry
    a different number for the same fact key.
    """
    number_map = re.findall(
        r"\b(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s*"
        r"(hours|hrs|times|weeks|days|months|kg|minutes)?\b", text)
    message_numbers = []
    for raw, unit in number_map:
        if raw.isdigit():
            value = float(raw)
        elif raw in _NUMBER_WORDS:
            value = float(_NUMBER_WORDS[raw])
        else:
            continue
        message_numbers.append((value, unit))
    if not message_numbers:
        return None
    for fact in memory_facts or []:
        key = str(fact.get("key", ""))
        raw_value = fact.get("value")
        if raw_value is None:
            continue
        fact_value = str(raw_value)
        fact_number = extract_numeric_value(fact_value)
        if fact_number is None:
            word_match = re.search(
                r"\b(one|two|three|four|five|six|seven|eight|nine|ten)\b",
                fact_value)
            fact_number = (_NUMBER_WORDS[word_match.group(1)]
                           if word_match else None)
        if fact_number is None:
            continue
        for msg_number, _unit in message_numbers:
            if abs(msg_number - fact_number) > 0.01:
                return key
    return None


def _detect_correction(message: str, memory_facts: List[dict],
                       topic_change_active: bool) -> Tuple[Optional[Intent], bool]:
    """Correction detection (RFC-001 Ch2.2 Intent 4): explicit correction
    markers and/or contradictions with previously stored facts.

    'Actually, I want to talk about work' is a topic change, not a
    correction — marker-based correction is suppressed while an explicit
    topic change or goal update is present.
    """
    marked = bool(_CORRECTION_RE.search(message))
    if marked and (topic_change_active or _GOAL_UPDATE_RE.search(message)):
        marked = False
    contradiction = _find_fact_contradiction(_normalize(message), memory_facts)
    if not marked and not contradiction:
        return None, False
    confidence = 0.50
    evidence = []
    if marked:
        confidence += 0.12 if _STRONG_CORRECTION_RE.search(message) else 0.08
        evidence.append("correction marker")
    if contradiction:
        confidence += 0.14
        evidence.append("contradicts memory fact '%s'" % contradiction)
    intent = Intent(
        intent="correction",
        confidence=min(0.95, confidence),
        priority=INTENT_PRIORITIES["correction"],
        notes="correcting previous information",
        evidence=evidence,
    )
    return intent, contradiction


def _detect_question(message: str) -> Optional[Intent]:
    """User question (RFC Ch2.1 Principle 5 — every message resolves to an
    action; asking a question resolves to 'answer the user')."""
    text = _normalize(message).strip()
    if not text or not re.search(r"[a-z]", text):
        return None  # pure punctuation ("??") is noise, not a question
    qmark = message.strip().endswith("?")
    starts = bool(_QUESTION_START_RE.match(text))
    you = bool(_QUESTION_YOU_RE.search(text))
    if not (qmark or starts or you):
        return None
    confidence = 0.85 if (qmark and starts) else (
        0.80 if (qmark or starts) else 0.72)
    return Intent(
        intent="question",
        confidence=confidence,
        priority=INTENT_PRIORITIES["question"],
        evidence=["interrogative marker"],
    )


def _detect_topic_change(message: str
                         ) -> Tuple[Optional[Intent], str]:
    """Explicit topic change (RFC-001 Ch2.2 Intent 7, Algorithm 8)."""
    m = _TOPIC_CHANGE_RE.search(message)
    if not m or _GOODBYE_RE.search(message):
        return None, ""
    text = _normalize(message)
    confidence = 0.66
    target = ""
    for topic in _TOPIC_KEYWORDS:
        if re.search(r"\b%s\b" % topic, text):
            target = topic
            break
    if target:
        confidence += 0.16
    intent = Intent(
        intent="topic_change",
        confidence=min(0.95, confidence),
        priority=INTENT_PRIORITIES["topic_change"],
        requires_branch_change=True,
        notes="target_topic=%s" % (target or "unspecified"),
        evidence=["explicit topic change marker", m.group(0)],
    )
    return intent, target


def _detect_commitment(message: str) -> Optional[Intent]:
    m = _COMMITMENT_RE.search(message)
    if not m:
        return None
    text = _normalize(message)
    if any(idiom in text for idiom in _IDIOM_BLOCKLIST):
        return None
    tail = text[m.end():m.end() + 60]
    action_words = ("sleep", "walk", "exercise", "workout", "gym", "meditat",
                    "journal", "run", "yoga", "eat", "drink", "read", "talk",
                    "call", "start", "stop", "try", "go to", "cook", "plan",
                    "schedule", "wake", "bed")
    has_action = any(w in tail for w in action_words)
    if not has_action and len(text.split()) <= 5:
        return None              # "I'll be honest" is not a commitment
    return Intent(
        intent="commitment",
        confidence=0.72 if has_action else 0.52,
        priority=INTENT_PRIORITIES["commitment"],
        notes=tail.strip()[:60] or "unspecified action",
        evidence=["commitment marker '%s'" % m.group(0),
                  "action context: %s" % ("yes" if has_action else "weak")],
    )


def _detect_goal_update(message: str) -> Optional[Intent]:
    if not _GOAL_UPDATE_RE.search(message):
        return None
    return Intent(
        intent="goal_update",
        confidence=0.74,
        priority=INTENT_PRIORITIES["goal_update"],
        evidence=["goal update marker"],
    )


def _detect_success(message: str) -> Optional[Intent]:
    if not _SUCCESS_RE.search(message):
        return None
    return Intent(
        intent="success",
        confidence=0.70,
        priority=INTENT_PRIORITIES["success"],
        evidence=["success marker"],
    )


def _detect_failure(message: str) -> Optional[Intent]:
    if not _FAILURE_RE.search(message):
        return None
    return Intent(
        intent="failure",
        confidence=0.70,
        priority=INTENT_PRIORITIES["failure"],
        evidence=["failure marker"],
    )


def _detect_rejection(message: str) -> Optional[Intent]:
    if not _REJECTION_RE.search(message):
        return None
    return Intent(
        intent="rejection",
        confidence=0.68,
        priority=INTENT_PRIORITIES["rejection"],
        evidence=["rejection marker"],
    )


def _detect_confirmation(message: str) -> Optional[Intent]:
    text = _normalize(message)
    if re.fullmatch(r"(yes|yep|yeah|yup|sure|ok|okay|alright|right|"
                    r"correct|that'?s right|exactly|indeed|of course)",
                    text):
        return Intent(
            intent="confirmation",
            confidence=0.9,
            priority=INTENT_PRIORITIES["confirmation"],
            evidence=["bare confirmation"],
        )
    return None


def _detect_small_talk(message: str) -> Optional[Intent]:
    if not _SMALL_TALK_RE.search(message):
        return None
    return Intent(
        intent="small_talk",
        confidence=0.72,
        priority=INTENT_PRIORITIES["small_talk"],
        evidence=["small talk marker"],
    )


def _detect_meta(message: str) -> Optional[Intent]:
    if not _META_RE.search(message):
        return None
    return Intent(
        intent="meta",
        confidence=0.78,
        priority=INTENT_PRIORITIES["meta"],
        evidence=["meta marker"],
    )


def _extract_slots(message: str, previous_question: str) -> List[dict]:
    """Slot extraction (RFC-001 Ch2.4 Algorithm 9)."""
    text = _normalize(message)
    slots = []
    sleep_match = _SLOT_PATTERNS["sleep_hours"].search(text)
    if sleep_match:
        raw = sleep_match.group(2)
        value = float(_NUMBER_WORDS.get(raw, raw)) if raw in _NUMBER_WORDS \
            else float(raw)
        slots.append({"slot": "sleep_hours", "value": value,
                      "confidence": 0.85})
    duration = _SLOT_PATTERNS["duration"].search(text)
    if duration:
        raw = duration.group(1)
        value = float(_NUMBER_WORDS.get(raw, raw)) if raw in _NUMBER_WORDS \
            else (float(raw) if raw.isdigit() else raw)
        slots.append({"slot": "duration", "value": value,
                      "confidence": 0.8})
    stress = _SLOT_PATTERNS["stress_level"].search(text)
    if stress:
        slots.append({"slot": "stress_level", "value": stress.group(1),
                      "confidence": 0.8})
    energy = _SLOT_PATTERNS["energy_level"].search(text)
    if energy:
        slots.append({"slot": "energy_level", "value": energy.group(1),
                      "confidence": 0.8})
    exercise = _SLOT_PATTERNS["exercise_times"].search(text)
    if exercise:
        value = exercise.group(1) or exercise.group(2)
        slots.append({"slot": "exercise_times", "value": float(value),
                      "confidence": 0.8})
    # Number-only answer to a sleep question ("About five" → sleep_hours).
    if not sleep_match and previous_question and "?" in previous_question:
        q = _normalize(previous_question)
        if "sleep" in q or "hour" in q:
            num = re.search(
                r"\b(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\b",
                text)
            if num and len(text.split()) <= 8:
                raw = num.group(1)
                value = float(_NUMBER_WORDS.get(raw, raw)) if raw in _NUMBER_WORDS \
                    else float(raw)
                slots.append({"slot": "sleep_hours", "value": value,
                              "confidence": 0.75})
    return slots


def _dedupe_intents(candidates: List[Intent]) -> List[Intent]:
    """Merge duplicate (intent, notes) candidates, boosting confidence
    (RFC-001 Ch2.3 Intent Merging)."""
    merged = {}
    for candidate in candidates:
        key = (candidate.intent, candidate.notes)
        if key in merged:
            old = merged[key]
            merged[key] = Intent(
                intent=old.intent,
                confidence=min(0.98, old.confidence + 0.05),
                priority=old.priority,
                level=old.level,
                requires_branch_change=old.requires_branch_change,
                requires_clarification=old.requires_clarification,
                slot_updates=old.slot_updates,
                notes=old.notes,
                evidence=tuple(dict.fromkeys(list(old.evidence)
                                             + list(candidate.evidence))),
            )
        else:
            merged[key] = candidate
    return list(merged.values())


def _with_conf(intent: Intent, confidence: float, extra: str = "") -> Intent:
    """Return a copy of `intent` with a new confidence (and optional
    evidence note). Deterministic re-scoring helper."""
    evidence = list(intent.evidence)
    if extra:
        evidence.append(extra)
    return Intent(
        intent=intent.intent,
        confidence=confidence,
        priority=intent.priority,
        level=intent.level,
        requires_branch_change=intent.requires_branch_change,
        requires_clarification=intent.requires_clarification,
        slot_updates=intent.slot_updates,
        notes=intent.notes,
        evidence=tuple(evidence),
    )


def _apply_context_confidence(intents: List[Intent], active_branch: str,
                              answered: bool) -> List[Intent]:
    """RFC-001 Ch2.4 Algorithm 2: adjust confidence with conversation,
    branch and memory context. The base scores already reflect semantic
    evidence; the weights stay deterministic constants."""
    adjusted = []
    branch_topic = active_branch or ""
    for intent in intents:
        confidence = intent.confidence
        evidence = list(intent.evidence)
        if intent.intent == "additional_information" and branch_topic:
            topic = intent.notes.replace("topic=", "")
            family = _BRANCH_FAMILIES.get(branch_topic, frozenset())
            if topic in family:
                confidence = min(0.97, confidence + 0.08)
                evidence.append("matches active branch '%s'" % branch_topic)
        if intent.intent == "answer" and answered:
            confidence = min(0.97, confidence + 0.05)
        adjusted.append(Intent(
            intent=intent.intent,
            confidence=confidence,
            priority=intent.priority,
            level=intent.level,
            requires_branch_change=intent.requires_branch_change,
            requires_clarification=intent.requires_clarification,
            slot_updates=intent.slot_updates,
            notes=intent.notes,
            evidence=tuple(evidence),
        ))
    return adjusted


def _primary_selection(candidates: List[Intent], crisis: bool,
                       answered: bool, token_count: int
                       ) -> Tuple[Intent, bool, dict]:
    """Algorithm 3/4/5: rank candidates, select primary, detect ambiguity.

    Returns (primary, requires_clarification, ambiguity_info). Crisis always
    becomes primary (Ch2.2 priority 1); content answers dominate; otherwise
    the primary is the most confident content-bearing intent. Ambiguity
    (Ch2.2 Clarification Rules) fires when the top two candidates are close
    AND the message is short or the top score is weak — rich compound
    messages with several confident topics are multi-intent, not ambiguous.
    """
    if not candidates:
        unknown = Intent(
            intent="unknown",
            confidence=0.35,
            priority=INTENT_PRIORITIES["unknown"],
            evidence=["no candidate intent matched"],
        )
        return unknown, True, {"detected": True, "reason": "no intent"}

    ranked = sorted(candidates, key=lambda i: (-i.confidence, i.priority))
    top = ranked[0]

    if crisis:
        return top, False, {"detected": False, "reason": "crisis overrides"}

    # Content-bearing intents compete for primary; administrative intents
    # (commitment, confirmation, meta, small talk) are primary only when
    # nothing else carries content (RFC Ch2.3 primary = dominant goal).
    content_types = {"answer", "emotional_expression", "additional_information",
                     "correction", "topic_change", "goal_update", "success",
                     "failure", "rejection", "clarification", "question",
                     "greeting", "goodbye"}
    content = [i for i in ranked if i.intent in content_types]
    if not content:
        content = ranked
    primary = content[0]

    ambiguity = {"detected": False, "reason": "", "top_candidates": []}
    distinct = [i for i in ranked if i.intent != primary.intent
                or i.notes != primary.notes]
    if distinct:
        runner_up = distinct[0]
        gap = primary.confidence - runner_up.confidence
        ambiguity["top_candidates"] = [
            {"intent": primary.intent, "confidence": round(primary.confidence, 3)},
            {"intent": runner_up.intent, "confidence": round(runner_up.confidence, 3)},
        ]
        if (gap < AMBIGUITY_GAP and primary.confidence < 0.75
                and (token_count <= 3 or primary.confidence < 0.65)):
            ambiguity["detected"] = True
            ambiguity["reason"] = ("gap %.2f < %.2f between '%s' and '%s'"
                                   % (gap, AMBIGUITY_GAP, primary.intent,
                                      runner_up.intent))

    requires_clarification = False
    if primary.confidence < 0.40:
        requires_clarification = True
        primary = Intent(intent="unknown", confidence=primary.confidence,
                         priority=INTENT_PRIORITIES["unknown"],
                         level=primary.level, notes="low confidence",
                         evidence=primary.evidence)
    elif ambiguity["detected"]:
        requires_clarification = True
    elif primary.confidence < PRIMARY_THRESHOLD and not answered:
        requires_clarification = True
    return primary, requires_clarification, ambiguity


def resolve_intents(message: str, *, active_branch: str = "",
                    previous_question: str = "",
                    last_turns: Optional[List[dict]] = None,
                    memory_facts: Optional[List[dict]] = None,
                    current_state: str = "") -> IntentGraph:
    """Deterministic Intent Resolution (RFC-001 Ch2.4 pipeline).

    Pure function of its inputs: the same message plus the same context
    always produces the identical IntentGraph.
    """
    last_turns = [t for t in (last_turns or []) if isinstance(t, dict)]
    memory_facts = list(memory_facts or [])
    text = _normalize(message)
    token_count = len(_words_with_positions(text))
    context_used = _context_used(active_branch, previous_question, last_turns,
                                 memory_facts, current_state)

    if not message or not text:
        unknown = Intent(
            intent="unknown",
            confidence=0.30,
            priority=INTENT_PRIORITIES["unknown"],
            evidence=["empty message"],
        )
        return IntentGraph(
            primary_intent=unknown,
            overall_confidence=0.30,
            continue_branch=True,
            reason="empty message; treated as an action-required signal",
            reasoning={"signals": [], "context_used": context_used,
                       "ambiguity": {"detected": True,
                                     "reason": "empty message",
                                     "top_candidates": []}},
        )

    signals = []

    # 1) Crisis first — rule-based safety, never LLM (project convention).
    risk_hit, risk_reason = detect_risk(message)
    crisis_intent = None
    if risk_hit:
        crisis_intent = Intent(
            intent="crisis",
            confidence=0.98,
            priority=INTENT_PRIORITIES["crisis"],
            notes="safety-critical content",
            evidence=["risk pattern matched", risk_reason or ""],
        )
        signals.append("risk_pattern")

    # 2) Candidate generation (Algorithm 1 — recall over precision).
    candidates: List[Intent] = []
    contradiction = None
    emotions: List[Intent] = []
    if crisis_intent:
        candidates.append(crisis_intent)

    if not crisis_intent and text:
        if _GREETING_RE.search(message):
            candidates.append(Intent(
                intent="greeting",
                confidence=0.9,
                priority=INTENT_PRIORITIES["greeting"],
                evidence=["greeting phrase"],
            ))
            signals.append("greeting")
        if _GOODBYE_RE.search(message):
            candidates.append(Intent(
                intent="goodbye",
                confidence=0.82,
                priority=INTENT_PRIORITIES["goodbye"],
                evidence=["goodbye phrase"],
            ))
            signals.append("goodbye")
        if _META_RE.search(message):
            candidates.append(_detect_meta(message))
            signals.append("meta")
        if _CLARIFICATION_RE.search(message):
            candidates.append(Intent(
                intent="clarification",
                confidence=0.78,
                priority=INTENT_PRIORITIES["clarification"],
                evidence=["clarification request marker"],
            ))
            signals.append("clarification_request")
        if _SMALL_TALK_RE.search(message):
            candidates.append(_detect_small_talk(message))
            signals.append("small_talk")
        question_intent = _detect_question(message)
        if question_intent:
            candidates.append(question_intent)
            signals.append("question")
        confirmation = _detect_confirmation(message)
        if confirmation:
            candidates.append(confirmation)
            signals.append("confirmation")

        # Negation-aware emotion & topic detection (adversarial-safe).
        negated_spans = _negated_spans(text)
        emotions = _detect_emotions(text, negated_spans)
        for intent in emotions:
            if intent.confidence >= 0.40:
                candidates.append(intent)
                signals.append("emotion.%s" % intent.notes)
        emotions = [i for i in emotions if i.confidence >= 0.40]

        topic_change, target_topic = _detect_topic_change(message)
        if topic_change:
            candidates.append(topic_change)
            signals.append("topic_change")

        label_words = frozenset(
            w for w in ("sad", "anxious", "angry", "lonely", "tired", "happy",
                        "motivated", "stressed")
            if re.search(r"\b%s\b" % w, text))
        topic_intents = []
        for topic, intent in _detect_topics(text, negated_spans, label_words):
            if topic_change and topic == target_topic:
                continue  # the target topic is part of the change request
            if _TEMPORAL_EXTENT_RE.search(text):
                intent = Intent(
                    intent=intent.intent,
                    confidence=min(0.95, intent.confidence + 0.12),
                    priority=intent.priority,
                    notes=intent.notes,
                    evidence=tuple(intent.evidence) + ("temporal extent",),
                )
            topic_intents.append(intent)
            signals.append("topic.%s" % topic)
        candidates.extend(topic_intents)

        answered, answer_reason = _detect_answer(message, previous_question)
        if answered:
            candidates.append(answered)
            signals.append("answer")

        correction, contradiction = _detect_correction(
            message, memory_facts, topic_change_active=bool(topic_change))
        if correction:
            candidates.append(correction)
            signals.append("correction")

        for detector, label in ((_detect_commitment, "commitment"),
                                (_detect_goal_update, "goal_update"),
                                (_detect_success, "success"),
                                (_detect_failure, "failure"),
                                (_detect_rejection, "rejection")):
            found = detector(message)
            if found:
                candidates.append(found)
                signals.append(label)

        # Commitment with a concrete action: the action's topic ("try
        # sleeping earlier") is part of the promise, not a new topic — drop
        # topic intents whose keywords appear in the commitment action tail
        # so the commitment can become primary (RFC Ch2.2 Intent 10).
        commitments = [c for c in candidates if c.intent == "commitment"]
        if commitments and commitments[0].confidence >= 0.70:
            tail = commitments[0].notes
            def _tail_topic(intent):
                topic = intent.notes.replace("topic=", "")
                return any(kw in tail for kw in _TOPIC_KEYWORDS.get(topic, ()))
            candidates = [c for c in candidates
                          if not (c.intent == "additional_information"
                                  and _tail_topic(c))]

        # Bare deflection words keep their existing conversational meaning
        # (RFC Ch2.1 Principle 5: every message resolves to an action).
        if not candidates and re.fullmatch(
                r"(ok|okay|fine|maybe|whatever|hmm|hm|huh|idk|i don't know|"
                r"i dont know|i dunno|not sure|no|nah|nope|not really|yes|"
                r"yep|yeah|\.\.\.)[.!?]*", text):
            candidates.append(Intent(
                intent="unknown",
                confidence=0.55,
                priority=INTENT_PRIORITIES["unknown"],
                notes="short deflection, no topic",
                evidence=["short deflection phrase"],
            ))
            signals.append("deflection")

    # 2b) Cause-clause re-ranking (RFC Ch2.3 L1-style): with a cause
    # connector ("because work has been stressful"), intents anchored in
    # the leading clause state the felt effect and dominate; trail-clause
    # intents state the cause and cap below them.
    cause_match = re.search(
        r"\b(because|since|due to|leads to|causing|caused by)\b", text)
    if cause_match and not crisis_intent:
        cause_pos = cause_match.start()

        def _first_keyword_span(intent):
            topic = intent.notes.replace("topic=", "")
            best = None
            for kw in _TOPIC_KEYWORDS.get(topic, ()):
                mm = re.search(r"\b%s\b" % re.escape(kw), text)
                if mm and (best is None or mm.start() < best):
                    best = mm.start()
            return best

        adjusted = []
        for c in candidates:
            if c.intent == "additional_information" \
                    and "topic=" in c.notes:
                span = _first_keyword_span(c)
                if span is not None and span < cause_pos:
                    c = _with_conf(c, min(0.95, c.confidence + 0.12),
                                   extra="leading clause")
                elif span is not None:
                    c = _with_conf(c, min(0.68, c.confidence),
                                   extra="cause clause")
            adjusted.append(c)
        candidates = adjusted

    # 3) Confidence with context (Algorithm 2) + dedupe (Intent Merging).
    answered_flag = bool(any(c.intent == "answer" for c in candidates))
    candidates = _apply_context_confidence(candidates, active_branch,
                                           answered_flag)
    candidates = _dedupe_intents(candidates)

    # 4) Rank & select primary (Algorithms 3-5).
    primary, requires_clarification, ambiguity = _primary_selection(
        candidates, crisis=bool(crisis_intent), answered=answered_flag,
        token_count=token_count)

    # 5) Build the graph (Ch2.3): secondary ≥ 0.40, background ≥ 0.25.
    rest = [c for c in candidates if c is not primary]
    rest.sort(key=lambda i: (-i.priority if i.confidence >= 0.60 else 0,
                             -i.confidence))
    secondaries = [_level(c, "secondary") for c in rest
                   if c.confidence >= 0.40]
    backgrounds = [_level(c, "background") for c in rest
                   if 0.25 <= c.confidence < 0.40]

    # 6) Relationships (Ch2.3): cause / conflict / reinforcement.
    relationships = []
    cause_match = re.search(r"\b(because|since|due to|from|leads to|"
                            r"causing|caused by)\b", text)
    if cause_match:
        topic_intents = [c for c in candidates
                         if c.intent == "additional_information"]
        emotion_intents = [c for c in candidates
                           if c.intent == "emotional_expression"]
        if topic_intents and emotion_intents:
            relationships.append(IntentRelationship(
                type="cause", source=topic_intents[0].notes, target="emotion",
                confidence=min(0.9, 0.6 + 0.05 * len(topic_intents))))
        elif len(topic_intents) >= 2:
            relationships.append(IntentRelationship(
                type="cause", source=topic_intents[0].notes,
                target=topic_intents[1].notes, confidence=0.65))
    if contradiction and any(c.intent == "correction" for c in candidates):
        relationships.append(IntentRelationship(
            type="conflict", source=contradiction, target="correction",
            confidence=0.8))
    if len(emotions) >= 2:
        relationships.append(IntentRelationship(
            type="reinforcement", source=emotions[0].notes,
            target=emotions[1].notes, confidence=0.6))

    # 7) Conversation flags (Ch2.1 output contract).
    correction_flag = any(c.intent == "correction" for c in candidates)
    topic_change_flag = any(c.intent == "topic_change" for c in candidates)
    interruption_flag = _detect_interruption(
        message, previous_question, answered_flag)

    topic_change_high = topic_change_flag and any(
        c.intent == "topic_change" and c.confidence >= 0.60
        for c in candidates)
    branch_change = bool(topic_change_high or crisis_intent)
    continue_branch = not (branch_change or any(
        c.intent == "goodbye" for c in candidates))

    # topic_shift: explicit change, or a dominant unrelated topic that is
    # neither an answer nor additive (Algorithm 7/8 conservative defaults).
    dominant_topic = None
    topic_candidates = [c for c in candidates
                        if c.intent == "additional_information"
                        and "topic=" in c.notes]
    if topic_candidates:
        dominant_topic = topic_candidates[0]
    topic_shift = bool(topic_change_high)
    if (not topic_shift and dominant_topic
            and not answered_flag
            and dominant_topic.confidence >= 0.72
            and not _ADDITIVE_MARKERS.search(message)
            and active_branch
            and dominant_topic.notes.replace("topic=", "") not in
            _BRANCH_FAMILIES.get(active_branch, frozenset())):
        topic_shift = True

    # emotion_shift: the message carries emotion different from the last
    # recorded turn's emotion (RFC-001 Ch2.1 detect emotional shifts).
    previous_emotion = ""
    for turn in reversed(last_turns):
        emo = turn.get("emotion") if isinstance(turn.get("emotion"), dict) \
            else None
        if emo and emo.get("primary_emotion"):
            previous_emotion = emo["primary_emotion"]
            break
    current_emotion = ""
    if emotions:
        notes = emotions[0].notes
        if "emotion=" in notes:
            current_emotion = notes.split("emotion=", 1)[1].split(",")[0]
    emotion_shift = bool(current_emotion and previous_emotion
                         and current_emotion != previous_emotion)

    if crisis_intent:
        requires_clarification = False
        reason = "crisis detected; all coaching suspended"
    elif answered_flag:
        reason = "answered current question (%s)" % answer_reason
    elif topic_change_flag:
        reason = "explicit topic change to '%s'" % (target_topic
                                                    or "unspecified")
    elif correction_flag:
        reason = "user correction of previous information"
    elif requires_clarification:
        reason = "ambiguous; clarification required (%s)" % ambiguity.get(
            "reason", "")
    elif interruption_flag:
        reason = "interruption: user did not answer the pending question"
    elif emotions:
        reason = "emotional expression (%s)" % current_emotion
    elif dominant_topic:
        reason = "additional information: %s" % dominant_topic.notes
    else:
        reason = "primary intent: %s" % primary.intent

    slots = _extract_slots(message, previous_question)
    primary = _level(primary, "primary",
                     slot_updates=tuple(slots) if slots else primary.slot_updates)

    overall = round(0.5 * primary.confidence
                    + 0.3 * (sum(i.confidence for i in secondaries) /
                             len(secondaries) if secondaries else 0.0)
                    + 0.2 * (sum(i.confidence for i in backgrounds) /
                             len(backgrounds) if backgrounds else 0.0), 3)

    return IntentGraph(
        primary_intent=primary,
        secondary_intents=tuple(secondaries),
        background_intents=tuple(backgrounds),
        relationships=tuple(relationships),
        overall_confidence=overall,
        continue_branch=continue_branch,
        branch_change_requested=branch_change,
        answered_current_question=answered_flag,
        new_slots_detected=tuple(slots),
        topic_shift=topic_shift,
        emotion_shift=emotion_shift,
        interruption=interruption_flag,
        correction=correction_flag,
        requires_clarification=requires_clarification,
        reason=reason,
        reasoning={
            "signals": signals,
            "context_used": context_used,
            "ambiguity": ambiguity,
        },
    )


def _level(intent: Intent, level: str, slot_updates=None) -> Intent:
    return Intent(
        intent=intent.intent,
        confidence=intent.confidence,
        priority=intent.priority,
        level=level,
        requires_branch_change=intent.requires_branch_change,
        requires_clarification=intent.requires_clarification,
        slot_updates=intent.slot_updates if slot_updates is None
        else slot_updates,
        notes=intent.notes,
        evidence=intent.evidence,
    )


def _context_used(active_branch, previous_question, last_turns, memory_facts,
                  current_state) -> dict:
    return {
        "active_branch": active_branch or "",
        "previous_question": (previous_question or "")[:120],
        "last_turns": len(last_turns),
        "memory_facts": len(memory_facts),
        "current_state": current_state or "",
    }


# ─── Runtime engine (RFC-002 Ch4 contract) ─────────────────────────────

class IntentResolverEngine(BaseEngine):
    """Registered intent resolver engine (RFC-001 Ch2.1 execution order).

    Runs first in the pipeline, before every other orchestration component.
    Returns one EngineUpdate owning the `intent_graph` context field; it
    never reads or writes RuntimeContext directly (RFC-002:1760-1770).
    """

    category = EngineCategory.PLANNING
    timeout_ms = 5000

    @property
    def metadata(self):
        return EngineMetadata(
            id="intent_resolver",
            name="Intent Resolver 2.0",
            version="2.0.0",
            owner="wellness_agent.intent_resolver",
            description="Deterministic IntentGraph classification "
                        "(RFC-001 Ch2): multi-intent, confidence, "
                        "corrections, interruptions, topic changes.",
        )

    def _invoke(self, engine_input, context):
        engine_input = engine_input or {}
        graph = resolve_intents(
            engine_input.get("message", ""),
            active_branch=engine_input.get("active_branch", "") or "",
            previous_question=engine_input.get("previous_question", "") or "",
            last_turns=engine_input.get("last_turns") or [],
            memory_facts=engine_input.get("memory_facts") or [],
            current_state=engine_input.get("current_state", "") or "",
        )
        diagnostics = [Diagnostic(
            level="info",
            code="IntentGraphBuilt",
            engine=self.id,
            message="primary=%s confidence=%.2f reason=%s"
                    % (graph.primary_intent.intent, graph.overall_confidence,
                       graph.reason),
        )]
        if graph.requires_clarification:
            diagnostics.append(Diagnostic(
                level="warning",
                code="IntentAmbiguous",
                engine=self.id,
                message="clarification required for message",
            ))
        return EngineUpdate.success({"intent_graph": graph.to_dict()},
                                    diagnostics=diagnostics)


__all__ = [
    "INTENT_PRIORITIES",
    "Intent",
    "IntentGraph",
    "IntentRelationship",
    "IntentResolverEngine",
    "resolve_intents",
]
