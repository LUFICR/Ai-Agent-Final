import re
import math

EMOTION_KEYWORDS = {
    "sad": ["sad", "unhappy", "down", "blue", "depressed", "miserable", "heartbroken", "gloomy", "sorrow", "tearful", "crying", "cry", "hopeless", "sucks", "awful", "terrible", "horrible"],
    "anxious": ["anxious", "worried", "nervous", "fearful", "panicked", "dread", "uneasy", "restless", "on edge", "tense", "cant sleep", "racing", "overthinking", "what if"],
    "angry": ["angry", "frustrated", "irritated", "annoyed", "furious", "mad", "livid", "resentful", "agitated", "pissed", "hate", "fed up", "sick of", "wasting my time", "pissed off", "fuming", "sick and tired", "so sick of"],
    "stressed": ["stressed", "overwhelmed", "burned out", "burnt out", "swamped", "exhausted", "drained", "pressure", "strain", "drowning", "piling", "deadline", "too much", "can't keep up", "so much", "need to do", "hectic"],
    "happy": ["happy", "glad", "great", "wonderful", "good", "joyful", "excited", "content", "grateful", "positive", "hopeful", "okay", "fine", "alright", "amazing"],
    "lonely": ["lonely", "alone", "isolated", "disconnected", "nobody", "no one", "abandoned", "left out", "by myself"],
    "tired": ["tired", "sleepy", "fatigued", "drowsy", "worn out", "weary", "lethargic", "low energy", "no energy", "exhausted", "drained", "burned out"],
    "motivated": ["motivated", "determined", "driven", "focused", "inspired", "committed", "ready", "productive"],
    "neutral": []
}

STRESS_KEYWORDS = ["deadline", "overwork", "pressure", "too much", "can't keep up", "behind", "stressed", "overwhelmed",
                   "anxious", "worry", "panic", "racing", "tense", "tight", "heavy", "sleepless", "insomnia"]

AVOIDANCE_PATTERNS = [
    r"\bi'm?\s*(fine|okay|ok|alright|good)\b",
    r"\bnothing\b",
    r"\bi don't know\b",
    r"\bi don't want to talk about it\b",
    r"\bnot really\b",
    r"\bit doesn't matter\b",
    r"\bleave me alone\b",
    r"\bi'm?\s*tired\s*(of|with)",
]

RISK_PATTERNS = [
    r"\b(kill(?:ing|s|ed)?\s*(?:myself|me))\b",
    r"\b(end\s*(?:my|the)\s*life)\b",
    r"\b(take\s*(?:my|the)\s*life)\b",
    r"\b(suicide|suicidal)\b",
    r"\b((?:don't|do not|doesn't|does not)\s*want\s*(?:to\s*)?live)\b",
    r"\b(better off dead)\b",
    r"\b(want\s*(?:to\s*)?die|wish\s*(?:i|I)\s*was\s*dead)\b",
    r"\b(harm\s*(?:myself|me))\b",
    r"\b(hurt\s*(?:myself|me))\b",
    r"\bself.harm\b",
    r"\bcutting\b",
    r"\b(no reason to live|nothing to live for)\b",
    r"\bcan't go on\b",
    r"\b(i'm?\s*going\s*to\s*end\s*(?:it|everything))\b",
    r"\b(end\s+it\s+all)\b",
    r"\b(want\s*(?:to\s*)?end\s+it\s+all)\b",
    r"\b(have\s+a\s+plan\b.*\b(end|kill|die))\b",
    r"\b((?:the|those|these)\s*pills?\s+(?:are\s+)?(?:right\s+)?(?:there|here))\b",
    r"\b(i'm?\s*(?:done|finished|giving up))\b",
    r"\b(can'?t\s+breathe|cannot\s+breathe)\b",
    r"\b(hyperventilat\w*)\b",
    r"\b(panic\s*attack)\b",
    r"\b(can'?t\s+catch\s+(?:my\s+)?breath)\b",
]


def extract_emotion_keywords(text):
    text_lower = text.lower()
    scores = {}
    for emotion, keywords in EMOTION_KEYWORDS.items():
        if not keywords:
            continue
        count = sum(1 for kw in keywords if kw in text_lower)
        scores[emotion] = count
    return scores


def detect_avoidance(text):
    text_lower = text.lower().strip()
    for pattern in AVOIDANCE_PATTERNS:
        if re.search(pattern, text_lower):
            return True
    words = text_lower.split()
    if len(words) <= 3 and not any(w in ["yes", "no", "maybe"] for w in words):
        return True
    if len(words) <= 2:
        return True
    return False


def detect_risk(text):
    text_lower = text.lower()
    for pattern in RISK_PATTERNS:
        if re.search(pattern, text_lower):
            return True, f"Risk keyword match: {pattern}"
    return False, None


def compute_sentiment(text):
    positive_words = {"good", "great", "happy", "glad", "wonderful", "love", "nice", "fantastic",
                      "amazing", "better", "best", "positive", "hopeful", "excited", "grateful",
                      "peaceful", "calm", "rested", "energetic", "motivated", "proud", "joyful",
                      "content", "okay", "fine", "alright"}
    negative_words = {"bad", "terrible", "awful", "horrible", "sad", "angry", "frustrated",
                      "stressed", "anxious", "worried", "depressed", "lonely", "tired",
                      "exhausted", "overwhelmed", "hopeless", "miserable", "hate", "worst",
                      "dreadful", "painful", "difficult", "hard", "struggle", "suffering",
                      "upset", "disappointed", "regret", "guilty", "ashamed", "hurt"}

    words = set(re.findall(r'\b[a-z]+\b', text.lower()))
    pos_count = len(words & positive_words)
    neg_count = len(words & negative_words)
    total = pos_count + neg_count
    if total == 0:
        return 0.5
    return pos_count / total


def softmax(scores, temperature=1.0):
    exp_scores = [math.exp(s / temperature) for s in scores]
    total = sum(exp_scores)
    return [s / total for s in exp_scores]


def extract_numeric_value(text):
    numbers = re.findall(r'\b\d+(?:\.\d+)?\b', text)
    if numbers:
        return float(numbers[0])
    return None
