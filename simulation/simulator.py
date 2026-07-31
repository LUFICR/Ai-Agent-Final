"""Conversation Simulation Engine.

Generates realistic multi-turn conversations for a persona and drives them
through the REAL production AI (Orchestrator.process_message). No production
code is touched — this module only consumes the public pipeline API.

Persona dynamics modeled:
  * emotions drift and spike (change emotions)
  * contradictions of earlier claims
  * forgetting ("oh right, I forgot…")
  * goal changes mid-conversation
  * frustration that builds and can end in an outburst or leaving
  * happiness shifts after progress/acknowledgment
  * leaving conversations and returning after days
  * missed routines
  * occasional lies (false positive reports)
  * sarcasm, especially when advice repeats

Every turn stores the conversation, reasoning context, engine outputs,
self-evaluation, and memory changes.
"""

import os
import random
import re
import time
from datetime import datetime

from .personas import PERSONAS

TOPIC_KEYWORDS = {
    "sleep": ["sleep", "bed", "night", "rest", "insomnia", "nap"],
    "stress": ["stress", "pressure", "overwhelm", "anxious", "anxiety", "burnout"],
    "work": ["work", "job", "boss", "office", "team", "meeting", "deadline",
             "project", "school", "class", "exam", "study", "deadline"],
    "mood": ["mood", "feel", "sad", "down", "happy", "depressed", "low"],
    "energy": ["energy", "tired", "exhausted", "fatigue"],
    "exercise": ["exercise", "workout", "gym", "run", "train", "movement",
                 "walk", "sport", "stretch"],
    "motivation": ["motivat", "goal", "routine", "habit", "plan", "consisten"],
    "relationships": ["friend", "family", "relationship", "partner", "lonely",
                      "alone", "social", "roommate", "parent"],
}

RANGES = {"sleep_hours": (4.0, 9.0), "stress": (20, 95), "exercise_days": (0, 5)}

_PRAISE_WORDS = ("great", "progress", "well done", "proud", "improving",
                 "keep it up", "nice", "that helps", "you're doing", "good job")
_NEGATIVE_WORDS = ("skip", "missed", "can't", "can't", "failing", "worst", "hate", "useless")

# ─── Message pools (templates; {topic}, {n}, {goal}, {habit}, {detail}, {filler}) ───

POOLS = {
    "ack": [
        "okay",
        "yeah that makes sense",
        "sure",
        "thanks, that's helpful",
        "mmhmm",
        "i see what you mean",
    ],
    "answer_yes": [
        "yeah, that's right",
        "yes, exactly",
        "definitely",
        "yeah i think so",
        "yes, for sure",
        "honestly yes",
    ],
    "answer_no": [
        "no, not really",
        "not exactly",
        "no, it's more like the opposite",
        "hmm no",
        "not really, no",
        "no, i don't think so",
    ],
    "answer_maybe": [
        "maybe, i'm not sure yet",
        "kinda, sometimes",
        "i don't know, maybe",
        "possibly, hard to say",
        "sometimes, depends on the day",
    ],
    "state_stress_high": [
        "honestly my {topic} is stressing me out a lot right now",
        "i'm really stressed about {topic} these days",
        "{topic} has been on my mind constantly, i can't switch off",
        "i feel like {topic} is pushing me past my limit",
        "my stress around {topic} has been through the roof",
    ],
    "state_stress_ok": [
        "i'm doing okay right now, {topic} is manageable",
        "stress has come down a bit, {topic} is calmer this week",
        "i feel more relaxed lately, not much to complain about",
    ],
    "state_sleep_bad": [
        "i only slept about {n} hours last night",
        "my sleep has been terrible, {n} hours is a good night for me",
        "i can't fall asleep, i was up until late and got {n} hours",
        "i slept badly again, maybe {n} hours total",
    ],
    "state_sleep_ok": [
        "i actually slept {n} hours last night, that felt good",
        "sleep was fine this time, around {n} hours",
        "i slept okay last night, better than usual",
    ],
    "state_mood_low": [
        "i've been feeling really down lately, {topic} gets to me",
        "my mood is pretty low at the moment",
        "i feel sad a lot of the time lately, i don't know why",
        "i'm just feeling low, everything feels harder",
    ],
    "state_mood_ok": [
        "my mood is better today, actually",
        "i feel lighter this week, things are looking up",
        "i'm in a good mood today, which is nice",
    ],
    "state_energy_low": [
        "i'm exhausted, i have no energy at all",
        "i feel drained constantly, even after resting",
        "my energy is so low lately, everything takes effort",
    ],
    "state_anxiety_high": [
        "i keep feeling anxious about {topic}, it's hard to calm down",
        "my anxiety has been high, especially around {topic}",
        "i get anxious about {topic} even when there's no reason",
    ],
    "state_exercise_missed": [
        "i skipped my {habit} this week, i feel bad about it",
        "i haven't {habit} in days, i keep putting it off",
        "i missed {habit} again, my consistency is gone",
    ],
    "state_exercise_ok": [
        "i kept up with {habit} this week, that feels good",
        "i managed to {habit} a few times, proud of myself",
        "i've been consistent with {habit} lately",
    ],
    "progress": [
        "i actually did something about {goal} this week, small win",
        "i've been more consistent lately, {goal} is going better",
        "i stuck to my plan for {goal}, that's progress for me",
        "small win: i handled {topic} better than before",
    ],
    "open_up": [
        "i don't usually tell people this, but i've been struggling a lot",
        "can i be honest? i feel like i'm falling apart inside",
        "i've been pretending to be fine, but i'm really not okay",
        "this is hard to admit, but i feel pretty lost right now",
    ],
    "smalltalk": [
        "how does this normally go?",
        "is it normal to feel this way?",
        "i've never talked to an AI about this before",
        "do people actually find this helpful?",
        "i didn't think i'd say this, but talking is kind of nice",
    ],
    "sarcasm": [
        "oh sure, sleeping 8 hours is totally realistic for me, great advice",
        "wow, thanks, i'll just stop being stressed, never thought of that",
        "yes, let me just add that to my endless list of impossible tasks",
        "oh right, because relaxing is famous for working on me",
        "sure, i'll just fix my whole life with that one tip",
    ],
    "frustration_mild": [
        "we've kind of been over this already, haven't we",
        "i feel like i keep saying the same thing",
        "is there anything different we could try?",
        "i don't feel like we're getting anywhere with this",
    ],
    "frustration_outburst": [
        "this isn't helping at all, i keep getting the same advice",
        "ugh, i'm so frustrated right now, nothing is working",
        "i came here for help and i feel like i'm talking in circles",
        "i'm honestly about to give up on this whole thing",
    ],
    "forget": [
        "oh right, i completely forgot to mention my {topic}",
        "sorry, i forgot to say earlier — about {topic}…",
        "wait, i never told you about {topic}, did i?",
        "i almost forgot, but {topic} has been a thing too",
    ],
    "contradict": [
        "actually, i've changed my mind about {topic}",
        "hmm, wait — i said earlier X, but honestly it's more like the opposite now",
        "actually, forget what i said about {topic}, it's not like that at all",
        "you know what, i think i was wrong earlier about {topic}",
    ],
    "lie": [
        "oh i've actually been sleeping great, like {n} hours a night",
        "i'm totally fine, nothing is wrong really",
        "honestly my {topic} is going great, no stress at all",
        "i've been super consistent lately, everything is under control",
        "i'm doing great, thanks, no complaints",
    ],
    "leave": [
        "sorry, gotta go now, talk later",
        "i have to run, this got too much",
        "brb, someone's at the door — actually, let's leave it here",
        "i need to go, i'll be back another time",
        "okay i have to leave now, bye",
    ],
    "return": [
        "sorry it's been a few days, things got busy",
        "hey, it's been a while — i disappeared for a few days",
        "i'm back, sorry for the silence, work got crazy",
        "been a few days, i needed a break from everything",
    ],
    "goal_shift": [
        "actually, what i really want to focus on now is {goal}",
        "i've been thinking — maybe my real goal should be {goal}",
        "forget my old plan, i think {goal} matters more right now",
        "you know what, i want to change direction: {goal} is what i need",
    ],
    "miss_routine": [
        "i completely missed my {habit} this week, i feel awful",
        "my {habit} fell apart, i skipped it all week",
        "i broke my {habit} streak, missed it twice already",
    ],
    "positive_shift": [
        "this actually helped, i feel a bit better than before",
        "talking about this helped more than i expected",
        "i feel a little lighter now, thanks",
        "okay, this is helping, let's keep going",
    ],
    "close_accept": [
        "good for today, thanks",
        "yeah, that's a good place to stop, thanks for listening",
        "okay, let's leave it here for today, that helped",
        "i'm good for today, thanks a lot",
    ],
    "close_decline": [
        "one more thing actually",
        "wait, before i go — one more thing",
        "not yet, i want to keep talking for a bit",
    ],
}

_TOPIC_PRONOUN = {"work": "it", "stress": "it", "sleep": "it", "mood": "it"}


def detect_topic(text):
    text_l = (text or "").lower()
    for topic, words in TOPIC_KEYWORDS.items():
        if any(w in text_l for w in words):
            return topic
    return None


def _render(template, ctx):
    try:
        return template.format(**ctx)
    except (KeyError, IndexError, ValueError):
        return template


def _cleanup_stores(user_id):
    from wellness_agent.config import get_data_dir
    for sub in ("memory", "sessions", "behaviors", "hypotheses", "whys",
                "evaluations", "beliefs"):
        name = "session" if sub == "sessions" else sub
        p = get_data_dir(sub) / f"{user_id}_{name}.json"
        if p.exists():
            try:
                os.remove(p)
            except OSError:
                pass


class PersonaRuntime:
    """Per-conversation persona state and message generation."""

    def __init__(self, persona, seed, target_turns):
        self.rng = random.Random(seed)
        self.p = persona
        self.target_turns = target_turns
        tend = persona["emotional_tendencies"]

        def jitter(base):
            return max(5, min(95, int(base + self.rng.randint(-8, 8))))

        self.emotion = {
            "stress": jitter(tend.get("stress", 50)),
            "anxiety": jitter(tend.get("anxiety", 40)),
            "mood": jitter(tend.get("mood", 50)),
            "energy": jitter(tend.get("energy", 50)),
            "loneliness": jitter(tend.get("loneliness", 30)),
            "engagement": 45,
            "avoidance": 25,
        }
        self.openness = int(persona["willingness_to_open_up"] * 100)
        self.current_goal = self.rng.choice(persona["goals"])
        self.goal_history = [self.current_goal]
        self.claims = []
        self.lied_claims = []
        self.habit_adherence = {h["name"]: h["adherence"] for h in persona["habits"]}
        self.day_offset = 0
        self.turns = 0
        self.frustration = int(tend.get("frustration", 20))
        self.positive_streak = 0
        self.last_assistant_text = ""
        self.asked_questions = 0

    # ─── Dynamics ────────────────────────────────────────────

    def maybe_advance_day(self, force=False):
        if force or (self.day_offset < 14 and self.rng.random() < 0.10):
            self.day_offset += 1
            for name in self.habit_adherence:
                self.habit_adherence[name] = max(0, self.habit_adherence[name] - 3)
            self.emotion["mood"] = max(5, self.emotion["mood"] - 2)
            return True
        return False

    def react_to_turn(self, assistant_text, turn_result):
        text = (assistant_text or "").lower()
        eval_ = (turn_result or {}).get("self_evaluation") or {}

        if any(w in text for w in _PRAISE_WORDS) or eval_.get("objective_completed"):
            self.emotion["mood"] = min(95, self.emotion["mood"] + 6)
            self.emotion["engagement"] = min(95, self.emotion["engagement"] + 6)
            self.frustration = max(0, self.frustration - 8)
            self.positive_streak += 1
        if any(w in text for w in ("gotta", "try", "you should", "recommend", "habit", "routine")):
            self.asked_questions += 1

        if assistant_text and assistant_text == self.last_assistant_text:
            self.frustration = min(95, self.frustration + 10)
        elif self.rng.random() < 0.08:
            self.frustration = min(95, self.frustration + 4)

        if self.frustration > 50 and self.rng.random() < 0.25:
            self.emotion["mood"] = max(5, self.emotion["mood"] - 5)

        if eval_:
            if eval_.get("objective_completed"):
                self.asked_questions = 0
            elif eval_.get("next_strategy") == "simplify_question" and self.rng.random() < 0.4:
                self.frustration = min(95, self.frustration + 6)

        # openness grows with good rapport, shrinks with frustration
        if self.positive_streak > 0 and self.rng.random() < 0.3:
            self.openness = min(95, self.openness + 3)
        if self.frustration > 60 and self.rng.random() < 0.3:
            self.openness = max(10, self.openness - 4)

        # drift toward persona baseline
        tend = self.p["emotional_tendencies"]
        for k in ("stress", "anxiety", "mood", "energy", "loneliness"):
            target = tend.get(k, 50)
            self.emotion[k] = int(self.emotion[k] + (target - self.emotion[k]) * 0.15
                                  + self.rng.randint(-3, 3))
            self.emotion[k] = max(5, min(95, self.emotion[k]))
        self.last_assistant_text = assistant_text

    def _voice(self, text):
        if self.rng.random() < 0.25:
            filler = self.rng.choice(self.p["fillers"])
            first = text.split(" ", 1)[0].strip("'\".,!?")
            stop = set(self.p["fillers"]) | {"i", "my", "it", "the", "a", "an", "this",
                                             "hey", "wait", "oh", "sorry", "okay", "you",
                                             "we", "actually", "honestly", "like", "literally",
                                             "hmm", "brb", "yeah", "no", "yes", "so"}
            if first not in stop:
                return f"{filler}, {text}"
        return text

    # ─── Event selection ─────────────────────────────────────

    def _roll(self, rate):
        return self.rng.random() < rate

    def pick_event(self):
        p = self.p
        if self.turns >= 3 and self.frustration >= 70 and self._roll(0.45):
            return ("outburst", {})
        if self.frustration >= 50 and self._roll(p["sarcasm_rate"] * 1.5):
            return ("sarcasm", {})
        if self.turns >= 2 and self._roll(p["leave_rate"] * (1 + self.frustration / 200)):
            return ("leave", {})
        if self.claims and self._roll(p["contradiction_rate"]):
            return ("contradiction", {})
        if self._roll(max(0.02, 1.0 - p["truthfulness"])):
            return ("lie", {})
        if self.turns >= 2 and self._roll(p["forget_rate"]):
            return ("forget", {})
        if self.turns >= 3 and self._roll(p["goal_change_rate"]):
            return ("goal_change", {})
        if self._roll(p["miss_habit_rate"] * 0.35) and any(v < 45 for v in self.habit_adherence.values()):
            return ("miss_routine", {})
        if self.positive_streak >= 2 and self._roll(0.4):
            return ("positive_shift", {})
        if self.emotion["mood"] >= 65 and self._roll(0.15):
            return ("positive_shift", {})
        if self.openness >= 65 and self._roll(0.12):
            return ("open_up", {})
        return (None, {})

    # ─── Message generation ──────────────────────────────────

    def _ctx(self, topic=None):
        return {
            "topic": topic or self.rng.choice(self.p["topics"]),
            "goal": self.current_goal,
            "habit": self._pick_habit(),
        }

    def _pick_habit(self):
        weak = [h for h, v in self.habit_adherence.items() if v < 50]
        pool = weak or list(self.habit_adherence)
        return self.rng.choice(pool)

    def _claim(self, topic, value):
        self.claims.append({"topic": topic, "value": value, "turn": self.turns})

    def next_user_message(self, assistant_text, turn_result, day_advanced):
        self.turns += 1
        tags = []
        event, params = self.pick_event()
        topic = detect_topic(assistant_text)
        ctx = self._ctx(topic)

        # ── return after days ──
        if day_advanced and self.day_offset >= 2 and self._roll(0.6) and self.turns > 1:
            text = _render(self.rng.choice(POOLS["return"]), {})
            tags.append("return")
            return self._voice(text), tags, {"event": "return", "day": self.day_offset}

        if event == "leave":
            text = _render(self.rng.choice(POOLS["leave"]), {})
            tags.append("leave")
            return self._voice(text), tags, {"event": "leave"}

        if event == "outburst":
            text = _render(self.rng.choice(POOLS["frustration_outburst"]), {})
            tags.append("frustration")
            return self._voice(text), tags, {"event": "outburst", "frustration": self.frustration}

        if event == "sarcasm":
            text = _render(self.rng.choice(POOLS["sarcasm"]), {})
            tags.append("sarcasm")
            self.frustration = min(95, self.frustration - 4)
            return self._voice(text), tags, {"event": "sarcasm"}

        if event == "contradiction":
            claim = self.rng.choice(self.claims)
            flip = self._flip(claim)
            text = _render(self.rng.choice(POOLS["contradict"]), {"topic": claim["topic"]})
            text = text.replace("X", f"{claim['topic']} was {claim['value']}")
            self._claim(claim["topic"], flip)
            tags.append("contradiction")
            return self._voice(text), tags, {"event": "contradiction", "about": claim["topic"]}

        if event == "lie":
            lie_topic = topic or self.rng.choice(["sleep", "work", "mood", "exercise"])
            text = _render(self.rng.choice(POOLS["lie"]), {"topic": lie_topic, "n": 8})
            self._claim(lie_topic, "claimed_great")
            self.lied_claims.append({"topic": lie_topic, "turn": self.turns})
            tags.append("lie")
            return self._voice(text), tags, {"event": "lie", "about": lie_topic}

        if event == "forget":
            forgotten = topic or self.rng.choice(self.p["topics"])
            text = _render(self.rng.choice(POOLS["forget"]), {"topic": forgotten})
            tags.append("forget")
            return self._voice(text), tags, {"event": "forget", "about": forgotten}

        if event == "goal_change":
            candidates = [g for g in self.p["goals"] if g != self.current_goal]
            new_goal = self.rng.choice(candidates or self.p["goals"])
            self.goal_history.append(new_goal)
            self.current_goal = new_goal
            text = _render(self.rng.choice(POOLS["goal_shift"]), {"goal": new_goal})
            tags.append("goal_change")
            return self._voice(text), tags, {"event": "goal_change", "to": new_goal}

        if event == "miss_routine":
            habit = self._pick_habit()
            text = _render(self.rng.choice(POOLS["miss_routine"]), {"habit": habit})
            self.habit_adherence[habit] = max(0, self.habit_adherence[habit] - 10)
            tags.append("missed_routine")
            return self._voice(text), tags, {"event": "miss_routine", "habit": habit}

        if event == "positive_shift":
            text = _render(self.rng.choice(POOLS["positive_shift"]), {})
            tags.append("positive_shift")
            self.positive_streak = 0
            return self._voice(text), tags, {"event": "positive_shift"}

        if event == "open_up":
            text = _render(self.rng.choice(POOLS["open_up"]), {})
            tags.append("open_up")
            return self._voice(text), tags, {"event": "open_up"}

        # ── natural replies ──
        is_question = "?" in (assistant_text or "")
        if is_question:
            kind = self.rng.choices(["answer_yes", "answer_no", "answer_maybe", "state_share"],
                                    weights=[35, 25, 15, 25])[0]
            if kind == "state_share":
                text = self._share_state(topic, ctx, tags)
            else:
                text = _render(self.rng.choice(POOLS[kind]), {})
        elif self.rng.random() < 0.45 and topic:
            text = self._share_state(topic, ctx, tags)
        elif self.rng.random() < 0.15:
            text = _render(self.rng.choice(POOLS["smalltalk"]), {})
        else:
            text = self._share_state(topic, ctx, tags)
        return self._voice(text), tags, {"event": "share" if not tags else tags[0]}

    def _share_state(self, topic, ctx, tags):
        e = self.emotion
        stress_high = e["stress"] >= 60
        mood_low = e["mood"] < 45
        sleep_bad = self.habit_adherence.get("sleep", 50) < 45

        pool_choice = self.rng.random()
        if stress_high and pool_choice < 0.45:
            text = _render(self.rng.choice(POOLS["state_stress_high"]), ctx)
            self._claim("stress", "high")
        elif sleep_bad and pool_choice < 0.65:
            n = round(self.rng.uniform(*RANGES["sleep_hours"]), 1)
            text = _render(self.rng.choice(POOLS["state_sleep_bad"]), {"n": n, "topic": ctx["topic"]})
            self._claim("sleep", f"{n} hours")
        elif mood_low and pool_choice < 0.8:
            text = _render(self.rng.choice(POOLS["state_mood_low"]), ctx)
            self._claim("mood", "low")
        elif e["anxiety"] >= 60 and pool_choice < 0.9:
            text = _render(self.rng.choice(POOLS["state_anxiety_high"]), ctx)
            self._claim("anxiety", "high")
        else:
            variants = [POOLS["state_exercise_missed"], POOLS["state_exercise_ok"]]
            pool = self.rng.choice(variants)
            text = _render(self.rng.choice(pool), ctx)
            if pool is POOLS["state_exercise_missed"]:
                tags.append("missed_routine")
        return text

    @staticmethod
    def _flip(claim):
        topic = claim["topic"]
        if topic == "sleep":
            value = claim["value"]
            try:
                n = float(re.search(r"\d+\.?\d*", value).group(0))
            except (AttributeError, ValueError):
                return "7 hours"
            return f"{min(9.0, max(4.0, 12 - n)):.1f} hours"
        if topic in ("stress", "anxiety"):
            return "low" if "high" in claim["value"] else "high"
        if topic == "mood":
            return "good" if "low" in claim["value"] else "low"
        return "different"


# ─── Simulation runner ────────────────────────────────────────

def _slim_ctx(ctx):
    if ctx is None:
        return {}
    get = ctx.get if isinstance(ctx, dict) else lambda k, d=None: getattr(ctx, k, d)
    memory_summary = get("memory_summary") or {}
    beliefs = [{"belief": b.get("belief"), "confidence": b.get("confidence")}
               for b in (memory_summary.get("beliefs") or [])]
    patterns = [{"human": p.get("human") or p.get("pattern"),
                 "confidence": p.get("confidence")}
                for p in (get("top_patterns") or [])]
    inter = get("recommended_intervention") or {}
    return {
        "objective": get("conversation_objective"),
        "mode": get("conversation_mode"),
        "style": get("response_style"),
        "behavior_traits": get("behavior_traits") or [],
        "beliefs": beliefs,
        "top_patterns": patterns,
        "intervention": {"title": inter.get("title") or inter.get("intervention"),
                         "confidence": inter.get("confidence")},
        "confidence_summary": get("confidence_summary") or {},
    }


def _slim_traits(traits):
    return {t: {"confidence": e.get("confidence", 0), "status": e.get("status"),
                "trend": e.get("trend"), "evidence_count": len(e.get("evidence") or [])}
            for t, e in (traits or {}).items()}


def _slim_beliefs(beliefs):
    return [{"id": b.get("id"), "belief": b.get("belief"), "confidence": b.get("confidence"),
             "evidence_count": b.get("evidence_count")} for b in (beliefs or [])]


def _slim_whys(whys):
    return [{"human": w.get("human") or w.get("pattern"), "confidence": w.get("confidence"),
             "repeats": w.get("repeats")} for w in (whys or [])[:3]]


def _slim_hypotheses(hyps):
    items = (hyps or {}).values() if isinstance(hyps, dict) else (hyps or [])
    ranked = sorted(items, key=lambda h: h.get("confidence", 0), reverse=True)[:3]
    return [{"hypothesis": h.get("hypothesis"), "confidence": h.get("confidence"),
             "status": h.get("status")} for h in ranked]


def _slim_eval(ev):
    if not ev:
        return None
    return {"objective": ev.get("objective"), "completed": ev.get("objective_completed"),
            "confidence": ev.get("confidence"), "next_strategy": ev.get("next_strategy"),
            "reason": ev.get("reason")}


def run_simulation(persona_id, target_turns=10, seed=1, user_id=None,
                   keep_stores=False, max_days=21):
    persona = PERSONAS[persona_id]
    user_id = user_id or f"sim_{persona_id}_{seed}"
    _cleanup_stores(user_id)

    from wellness_agent.orchestrator import Orchestrator
    orch = Orchestrator(user_id=user_id, enable_learning=False)
    rt = PersonaRuntime(persona, seed, target_turns)
    turns = []
    started = time.time()

    while rt.turns < target_turns:
        day_advanced = rt.maybe_advance_day()
        assistant_text = turns[-1]["assistant_response"] if turns else ""
        turn_result = turns[-1] if turns else None
        message, tags, meta = rt.next_user_message(assistant_text, turn_result, day_advanced)

        memory_before = {f.get("key") for f in orch.agents.memory.get_all_facts()}
        res = orch.process_message(message)
        memory_after = orch.agents.memory.get_all_facts()
        added = [{"key": f.get("key"), "value": str(f.get("value"))[:60],
                  "confidence": f.get("confidence")}
                 for f in memory_after if f.get("key") not in memory_before]

        turn = {
            "n": len(turns) + 1,
            "day_offset": rt.day_offset,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "tags": tags,
            "event": meta,
            "user_message": message,
            "assistant_response": res.get("response"),
            "assistant_options": res.get("options"),
            "state": (res.get("state") or {}).get("current_state"),
            "route": res.get("route"),
            "emotion": (res.get("emotion") or {}).get("primary_emotion"),
            "llm_used": bool(res.get("llm_used")),
            "objective": (res.get("objective") or {}).get("objective"),
            "evaluation": _slim_eval(res.get("self_evaluation")),
            "reasoning_context": _slim_ctx(res.get("reasoning_context")),
            "engine_outputs": {
                "behaviors": _slim_traits(res.get("behaviors")),
                "beliefs": _slim_beliefs(res.get("beliefs")),
                "whys": _slim_whys(res.get("whys")),
                "hypotheses": _slim_hypotheses(res.get("hypotheses")),
                "interventions": [{"title": i.get("title") or i.get("intervention"),
                                   "confidence": i.get("confidence")}
                                  for i in (res.get("ranked_interventions") or [])[:3]],
            },
            "memory_changes": {
                "added": added[:8],
                "added_count": len(added),
                "facts_total": len(memory_after),
                "trust_score": orch.agents.memory.get_trust_score(),
            },
            "persona_state": {
                "emotion": dict(rt.emotion),
                "frustration": rt.frustration,
                "openness": rt.openness,
                "goal": rt.current_goal,
            },
        }
        turns.append(turn)
        rt.react_to_turn(turn["assistant_response"], res)

        if "leave" in tags:
            ended = "left"
            break
        if rt.day_offset > max_days:
            ended = "days_passed"
            break
    else:
        ended = "completed"

    elapsed = time.time() - started
    tag_counts = {}
    for t in turns:
        for tag in t["tags"]:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1

    evals = [t["evaluation"] for t in turns if t["evaluation"]]
    record = {
        "sim_id": user_id,
        "persona_id": persona_id,
        "persona_label": persona["label"],
        "target_turns": target_turns,
        "actual_turns": len(turns),
        "ended": ended,
        "seed": seed,
        "day_offsets": turns[-1]["day_offset"] if turns else 0,
        "duration_s": round(elapsed, 2),
        "tags": tag_counts,
        "summary": {
            "lied": len(rt.lied_claims),
            "contradictions": tag_counts.get("contradiction", 0),
            "goal_changes": len(rt.goal_history) - 1,
            "goal_history": rt.goal_history,
            "evaluations": len(evals),
            "avg_eval_confidence": round(sum(e["confidence"] for e in evals) / len(evals), 1) if evals else None,
            "objectives_completed": sum(1 for e in evals if e.get("completed")),
            "llm_turns": sum(1 for t in turns if t["llm_used"]),
            "trust_final": orch.agents.memory.get_trust_score(),
        },
        "memory_final": {
            "facts_count": len(orch.agents.memory.get_all_facts()),
            "pillars": orch.agents.memory.get_known_pillars(),
        },
        "turns": turns,
    }

    if not keep_stores:
        _cleanup_stores(user_id)
    return record
