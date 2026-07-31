"""AI Conversation Judge.

Scores a finished conversation on 13 dimensions (0-100, higher is better):

    coaching, empathy, curiosity, memory_usage, personalization,
    pattern_recognition, recommendation_quality, naturalness,
    objective_completion, hallucination_risk, contradictions, trust, return

Produces the compact schema requested by the product:

    {
      "overall_score": 0,
      "coaching": 0,
      "memory": 0,
      "conversation": 0,
      "issues": [],
      "recommendations": []
    }

plus a full "dimensions" breakdown (score + rationale + evidence) that is
stored alongside. Evaluations are persisted under data/evaluations and
indexed for leaderboards and cross-commit comparisons.

The judge is deterministic: it consumes only artifacts the pipeline itself
produces (turn records, memory facts, beliefs, trust score), so scores are
stable and reproducible across runs and commits. No LLM calls.
"""

import os
import re
import subprocess
from datetime import datetime

from .config import get_data_dir
from .utils.storage import load_json, save_json, now_iso

DIMENSIONS = [
    "coaching", "empathy", "curiosity", "memory_usage", "personalization",
    "pattern_recognition", "recommendation_quality", "naturalness",
    "objective_completion", "hallucination_risk", "contradictions",
    "trust", "return",
]

_EMPATHY_MARKERS = [
    "i'm here", "i hear you", "i understand", "that sounds", "that must be",
    "you're not alone", "it's okay", "it's ok", "i'm sorry", "i'm glad",
    "be kind to yourself", "that makes sense", "sounds tough", "sounds hard",
    "take it one step", "proud of you", "i'm listening", "that's hard",
    "isn't easy", "not easy", "we'll figure", "i've got you", "i'm with you",
]
_COACHING_MARKERS = [
    "try", "practice", "schedule", "start small", "plan", "routine", "strategy",
    "tool", "tip", "habit", "step", "goal", "exercise", "write down",
    "set a", "choose", "pick one", "track", "remind", "break it down",
    "gradually", "consistency", "morning walk", "wind down",
]
_COACHING_STATES = {"guided_discovery", "deep_investigation", "pillar_selection",
                    "insight_delivered", "routine_planning", "follow_up", "reflection"}
_ACTION_OBJECTIVES = {"support_decision", "recommend_habit", "routine_planning",
                      "build_habit", "insight_delivery", "recommendation"}
_ROBOTIC_PHRASES = ["as an ai", "i am an ai", "i'm an ai", "as a language model",
                    "i'm sorry, i can't", "i cannot provide", "i'm just a program",
                    "i don't have personal"]
_TOPIC_WORDS = {
    "sleep": ["sleep", "insomnia", "bedtime", "awake", "tired", "nap"],
    "stress": ["stress", "overwhelm", "pressure", "deadline", "burnout", "burned out"],
    "mood": ["mood", "sad", "depress", "down", "low", "cry", "hopeless"],
    "anxiety": ["anxiet", "worry", "panic", "nervous", "racing thoughts", "ruminat"],
    "work": ["work", "job", "office", "colleague", "boss", "project", "meeting"],
    "exercise": ["exercise", "gym", "run", "walk", "workout", "yoga", "movement"],
    "nutrition": ["eat", "meal", "diet", "food", "breakfast", "hungry"],
    "relationships": ["friend", "family", "partner", "roommate", "parent", "lonely", "relationship"],
    "screen": ["screen", "phone", "scrolling", "doom-scroll", "social media"],
    "goal": ["goal", "progress", "achieve", "revenue", "finals", "study", "exam"],
}
_CURIOUS_OBJECTIVES = {"discover_goal", "ask_question", "explore_topic",
                       "understand_habits", "discover_goal_refinement"}


def _clamp(v, lo=0.0, hi=100.0):
    return max(lo, min(hi, v))


_COMMIT_ID_CACHE = None


def detect_commit_id():
    """Best-effort commit id: git HEAD, then COMMIT_LABEL env, then unknown.

    Cached module-level: one subprocess per process, not per session.
    """
    global _COMMIT_ID_CACHE
    if _COMMIT_ID_CACHE is not None:
        return _COMMIT_ID_CACHE
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=5)
        if out.returncode == 0 and out.stdout.strip():
            _COMMIT_ID_CACHE = out.stdout.strip()
            return _COMMIT_ID_CACHE
    except Exception:
        pass
    _COMMIT_ID_CACHE = os.environ.get("COMMIT_LABEL", "unknown")
    return _COMMIT_ID_CACHE


class ConversationJudge:
    def __init__(self, user_id="default", commit_id=None):
        self.user_id = user_id
        self.commit_id = commit_id or detect_commit_id()
        self._eval_dir = get_data_dir("evaluations")

    # ─── Public API ───────────────────────────────────────────

    def evaluate(self, payload, meta=None, conversation_id=None):
        """payload: {"turns": [...], "memory": [facts], "trust_score": int,
                      "beliefs": [...], "reasoning_context": {...},
                      "ended": str}
           meta:    {"source", "session_id", "persona", "persona_label",
                     "batch", "seed", "target_turns", "actual_turns"}
           Returns the full evaluation record and persists it."""
        turns = [self._normalize_turn(t) for t in (payload.get("turns") or [])]
        payload = dict(payload)
        payload["turns"] = turns
        sig = self._signals(payload)
        dims = self._score_dimensions(sig)
        issues = self._issues(sig, dims)
        rec = self._record(conversation_id, payload, meta, sig, dims, issues)
        self._store(rec, meta)
        return rec

    def evaluate_record(self, record, meta=None, conversation_id=None):
        """Evaluate a full simulation record (as written by the simulator)."""
        payload = {
            "turns": record.get("turns", []),
            "memory": record.get("memory_final"),
            "trust_score": (record.get("summary") or {}).get("trust_final"),
            "beliefs": None,
            "reasoning_context": None,
            "ended": record.get("ended"),
            "day_offsets": record.get("day_offsets"),
            "tags": record.get("tags"),
        }
        meta = dict(meta or {})
        meta.setdefault("source", "simulation")
        meta.setdefault("persona", record.get("persona_id"))
        meta.setdefault("persona_label", record.get("persona_label"))
        meta.setdefault("seed", record.get("seed"))
        meta.setdefault("batch", record.get("batch_id"))
        meta.setdefault("actual_turns", record.get("actual_turns"))
        return self.evaluate(payload, meta=meta,
                             conversation_id=conversation_id or record.get("sim_id"))

    # ─── Normalization ────────────────────────────────────────

    def _normalize_turn(self, t):
        if not isinstance(t, dict):
            return {}
        state = t.get("state")
        if isinstance(state, dict):
            state = state.get("current_state")
        emotion = t.get("emotion") or t.get("emotion_summary") or {}
        if isinstance(emotion, dict):
            emotion = emotion.get("primary_emotion") or emotion.get("primary") or ""
        objective = t.get("objective") or {}
        if isinstance(objective, dict):
            objective = objective.get("objective")
        eval_info = t.get("evaluation") or t.get("self_evaluation") or {}
        if isinstance(eval_info, dict):
            completed = eval_info.get("completed", eval_info.get("objective_completed"))
        else:
            completed = None
        return {
            "user": str(t.get("user_message") or t.get("user") or ""),
            "assistant": str(t.get("assistant_response") or t.get("assistant")
                             or t.get("response") or ""),
            "state": state,
            "route": t.get("route") or [],
            "objective": objective,
            "emotion": str(emotion or "").lower(),
            "llm_used": bool(t.get("llm_used")),
            "options": t.get("assistant_options") or t.get("options") or [],
            "tags": list(t.get("tags") or []),
            "event": t.get("event"),
            "day_offset": t.get("day_offset"),
            "eval_completed": completed,
            "reasoning_context": t.get("reasoning_context"),
            "engine_outputs": t.get("engine_outputs") or {},
            "memory_changes": t.get("memory_changes") or {},
        }

    # ─── Signal extraction ────────────────────────────────────

    def _signals(self, payload):
        turns = payload.get("turns") or []
        s = {
            "n": len(turns),
            "questions": 0, "open_questions": 0,
            "empathy_turns": 0, "coaching_turns": 0,
            "states": set(), "objectives": set(),
            "repeats_assistant": 0, "repeats_user": 0,
            "placeholders": 0, "robotic": 0, "empty_short": 0,
            "memory_refs": 0, "fact_refs": 0,
            "added_total": 0, "facts_total": 0,
            "belief_count": 0, "whys": 0, "hypotheses": 0,
            "interventions": 0, "intervention_conf": 0.0,
            "routine_route": False, "question_route": 0, "root_route": False,
            "insight_delivered": False, "risk_handled": False,
            "tags": {}, "day_gaps": 0, "left_abrupt": False,
            "final_emotion": "", "end_state": "",
            "objective_completed": 0, "objectives_total": 0,
            "topic_misses": 0, "unsupported_numbers": 0,
            "conflicts": [], "contradiction_events": 0, "lie_events": 0,
            "sarcasm_events": 0, "open_up_events": 0, "positive_shift": 0,
            "trust_score": None,
            "user_topics": set(), "assistant_topics": set(), "conflicts": [],
            "ended": None,
        }
        n = s["n"]
        if n == 0:
            s["empty_conversation"] = True
            return s

        seen_assistant = set()
        seen_user = set()
        user_topics = set()
        facts = payload.get("memory") or []
        fact_texts = [str(f.get("value", "")) for f in facts if isinstance(f, dict)]
        fact_nums = [re.sub(r"[^0-9.]+", "", str(f.get("value")))
                     for f in facts if isinstance(f, dict)
                     and re.search(r"\d", str(f.get("value")))]

        for t in turns:
            u, a, state, route = t["user"], t["assistant"], t["state"], t["route"]
            a_low = a.lower()
            u_low = u.lower()

            if state:
                s["states"].add(state)
            if t["objective"]:
                s["objectives"].add(t["objective"])
                s["objectives_total"] += 1
            if t["eval_completed"] is True:
                s["objective_completed"] += 1

            if "?" in a:
                s["questions"] += 1
                if t["options"] or a.rstrip().endswith("?"):
                    s["open_questions"] += 1
            if "question_planner" in route:
                s["question_route"] += 1
            if "routine_generator" in route:
                s["routine_route"] = True
            if "root_cause" in route or "recommendation" in route or "insight" in route:
                s["root_route"] = True
            if state == "insight_delivered":
                s["insight_delivered"] = True

            if any(m in a_low for m in _EMPATHY_MARKERS):
                s["empathy_turns"] += 1
            if any(m in a_low for m in _COACHING_MARKERS):
                s["coaching_turns"] += 1

            if "{" in a or "}" in a:
                s["placeholders"] += 1
            if any(p in a_low for p in _ROBOTIC_PHRASES):
                s["robotic"] += 1
            if len(a) < 12 or len(a) > 800:
                s["empty_short"] += 1

            if a and a in seen_assistant:
                s["repeats_assistant"] += 1
            seen_assistant.add(a)
            if u and u in seen_user:
                s["repeats_user"] += 1
            seen_user.add(u)

            for phrase in ("you mentioned", "last time", "you said", "you told me",
                           "remember", "earlier you", "since we talked", "you shared",
                           "the other day", "you've been"):
                if phrase in a_low:
                    s["memory_refs"] += 1
                    break
            if fact_texts and any(v and len(v) > 2 and v in a_low for v in fact_texts):
                s["fact_refs"] += 1

            mc = t["memory_changes"] or {}
            s["added_total"] += int(mc.get("added_count") or 0)
            if mc.get("facts_total"):
                s["facts_total"] = max(s["facts_total"], int(mc["facts_total"]))
            if mc.get("trust_score") is not None:
                s["trust_score"] = mc["trust_score"]

            rctx = t["reasoning_context"] or {}
            ms = rctx.get("memory_summary") or {}
            bel = ms.get("beliefs") or rctx.get("beliefs") or []
            s["belief_count"] = max(s["belief_count"], len(bel))
            s["whys"] = max(s["whys"], len(rctx.get("top_patterns") or []))
            pat = rctx.get("conversation_patterns") or {}
            s["whys"] = max(s["whys"], len(pat.get("whys") or []))

            eo = t["engine_outputs"] or {}
            hyps = eo.get("hypotheses") or []
            s["hypotheses"] = max(s["hypotheses"], len(hyps))
            inter = eo.get("interventions") or []
            if inter:
                s["interventions"] = max(s["interventions"], len(inter))
                confs = [i.get("confidence") or 0 for i in inter]
                s["intervention_conf"] = max(s["intervention_conf"], max(confs))

            for tag in t["tags"]:
                s["tags"][tag] = s["tags"].get(tag, 0) + 1

            for w, words in _TOPIC_WORDS.items():
                if any(x in u_low for x in words):
                    user_topics.add(w)

            numbers = re.findall(r"\d+(?:\.\d+)?", a)
            if numbers:
                for num in numbers:
                    if num not in fact_nums:
                        s["unsupported_numbers"] += 1
                        break

        if payload.get("tags"):
            for k in ("lie", "contradiction", "sarcasm", "open_up", "positive_shift"):
                s["tags"][k] = s["tags"].get(k, 0) + payload["tags"].get(k, 0)
        s["lie_events"] = s["tags"].get("lie", 0)
        s["contradiction_events"] = s["tags"].get("contradiction", 0)
        s["sarcasm_events"] = s["tags"].get("sarcasm", 0)
        s["open_up_events"] = s["tags"].get("open_up", 0)
        s["positive_shift"] = s["tags"].get("positive_shift", 0)

        day_offsets = payload.get("day_offsets")
        if isinstance(day_offsets, int):
            day_offsets = [0, day_offsets]
        if not day_offsets:
            day_offsets = [t["day_offset"] for t in turns if t.get("day_offset") is not None]
        for a, b in zip(day_offsets, day_offsets[1:]):
            if isinstance(a, int) and isinstance(b, int) and b - a > 1:
                s["day_gaps"] += 1

        s["ended"] = payload.get("ended")
        s["left_abrupt"] = s["ended"] == "left"
        s["final_emotion"] = turns[-1]["emotion"]
        s["end_state"] = turns[-1]["state"] or ""

        if payload.get("trust_score") is not None:
            s["trust_score"] = payload["trust_score"]
        s["facts_total"] = max(s["facts_total"], len(facts))
        return s

    def _assistant_topics(self, turns, user_topics):
        topics = set()
        for t in turns:
            a_low = t["assistant"].lower()
            for w, words in _TOPIC_WORDS.items():
                if any(x in a_low for x in words):
                    topics.add(w)
        return topics - user_topics

    def _conflicting_facts(self, facts):
        by_key = {}
        for f in facts:
            if not isinstance(f, dict):
                continue
            k = f.get("key")
            if not k:
                continue
            v = str(f.get("value", ""))
            prev = by_key.get(k)
            if prev is not None and prev != v:
                return [(k, prev, v)]
            by_key[k] = v
        return []

    # ─── Scoring ──────────────────────────────────────────────

    def _score_dimensions(self, s):
        n = s["n"]
        d = {}
        if s.get("empty_conversation"):
            return {k: 0 for k in DIMENSIONS}

        # coaching ──────────────────────────────────────────────
        score = 50.0
        if s["states"] & _COACHING_STATES:
            score += 20
        ratio = (s["coaching_turns"] / n) if n else 0
        score += 15 if ratio >= 0.4 else (8 if ratio > 0 else 0)
        if s["interventions"]:
            score += 15 if s["intervention_conf"] >= 60 else 8
        if s["routine_route"]:
            score += 10
        if s["question_route"] >= 2:
            score += 10
        if s["insight_delivered"]:
            score += 10
        if s["objective_completed"]:
            score += 5
        if n >= 5:
            score += 5
        d["coaching"] = score

        # empathy ───────────────────────────────────────────────
        score = 10.0
        emp_ratio = (s["empathy_turns"] / n) if n else 0
        score += 30 * min(1.0, emp_ratio / 0.5)
        if s["final_emotion"] in ("calm", "joy", "relief", "gratitude", "content", "happy"):
            score += 10
        if s["risk_handled"]:
            score += 15
        if n >= 3:
            score += 10
        if s["open_up_events"]:
            score += 10
        d["empathy"] = score

        # curiosity ─────────────────────────────────────────────
        score = 30.0
        score += 50 * min(1.0, s["questions"] / max(1, n) / 0.6)
        if s["question_route"]:
            score += 15
        if n >= 5 and s["questions"] == 0:
            score -= 15
        d["curiosity"] = score

        # memory usage ──────────────────────────────────────────
        score = 20.0
        if s["facts_total"] >= 3:
            score += 30
        elif s["facts_total"] >= 1:
            score += 15
        if s["added_total"] >= 2:
            score += 20
        if s["belief_count"]:
            score += 15
        if s["memory_refs"]:
            score += 15
        if s["fact_refs"]:
            score += 10
        d["memory_usage"] = score

        # personalization ───────────────────────────────────────
        score = 20.0
        if s["fact_refs"]:
            score += 25
        if s["belief_count"]:
            score += 15
        if s["interventions"] and s["intervention_conf"] >= 60:
            score += 15
        if s["states"]:
            score += 15
        if n >= 5:
            score += 10
        d["personalization"] = score

        # pattern recognition ───────────────────────────────────
        score = 20.0
        if s["whys"]:
            score += 30
        if s["hypotheses"]:
            score += 20
        if s["belief_count"]:
            score += 15
        if s["insight_delivered"] or s["root_route"]:
            score += 15
        d["pattern_recognition"] = score

        # recommendation quality ────────────────────────────────
        score = 25.0
        if s["interventions"]:
            score += 20 if s["intervention_conf"] >= 65 else 10
        if s["routine_route"]:
            score += 20
        if s["interventions"] >= 2:
            score += 15
        if s["objectives"] & _ACTION_OBJECTIVES:
            score += 10
        d["recommendation_quality"] = score

        # naturalness ───────────────────────────────────────────
        score = 100.0
        score -= 25 * s["repeats_assistant"]
        score -= 10 * s["repeats_user"]
        score -= 30 * s["placeholders"]
        score -= 20 * s["robotic"]
        score -= 10 * s["empty_short"]
        d["naturalness"] = score

        # objective completion ──────────────────────────────────
        if s["objective_completed"]:
            score = 90.0
        elif s["objectives_total"] and s["end_state"] in ("reflection", "close", "goodbye"):
            score = 70.0
        elif s["objectives_total"]:
            score = 45.0
        else:
            score = 30.0
        d["objective_completion"] = score

        # hallucination risk (higher = safer) ───────────────────
        score = 100.0
        score -= 35 * s["placeholders"]
        score -= 20 * min(2, s["unsupported_numbers"])
        if s["assistant_topics"]:
            score -= 10 * min(2, len(s["assistant_topics"]))
        d["hallucination_risk"] = score

        # contradictions (higher = cleaner) ─────────────────────
        score = 100.0
        score -= 30 * min(2, s["lie_events"])
        score -= 25 * min(2, s["contradiction_events"])
        score -= 20 * min(2, len(s["conflicts"]))
        score -= 10 * min(1, s["sarcasm_events"])
        d["contradictions"] = score

        # trust ─────────────────────────────────────────────────
        t = s["trust_score"]
        if t is None:
            score = 55.0
        else:
            score = float(t)
        score += 10 * min(1, s["open_up_events"])
        score += 10 * min(1, s["positive_shift"])
        score -= 15 * min(1, s["lie_events"])
        score -= 10 * min(1, s["contradiction_events"])
        if s["left_abrupt"]:
            score -= 10
        if s["day_gaps"]:
            score += 10
        d["trust"] = score

        # return (retention likelihood) ─────────────────────────
        score = 50.0
        if s["ended"] == "completed":
            score += 20
        elif s["ended"] == "days_passed":
            score += 10
        elif s["left_abrupt"]:
            score -= 20
        if s["day_gaps"]:
            score += 15
        if s["final_emotion"] in ("calm", "joy", "relief", "gratitude", "content", "happy"):
            score += 10
        if s["final_emotion"] in ("anxious", "angry", "sad", "frustrated", "stressed", "overwhelmed"):
            score -= 10
        if s["trust_score"] is not None:
            score += 10 if s["trust_score"] >= 70 else (-10 if s["trust_score"] <= 50 else 0)
        if s["questions"]:
            score += 10
        if n >= 20:
            score += 10
        elif n <= 3:
            score -= 10
        d["return"] = score

        for k in DIMENSIONS:
            d[k] = int(round(_clamp(d[k])))
        return d

    # ─── Issues & recommendations ─────────────────────────────

    def _issues(self, s, dims):
        issues = []
        n = s["n"]
        if s.get("empty_conversation"):
            issues.append("Conversation is empty — nothing to judge")
            return issues
        if n <= 2:
            issues.append(f"Conversation is very short ({n} turns) — too little to coach on")
        if n >= 5 and s["questions"] == 0:
            issues.append("No questions were asked — the coach never probed or guided")
        if s["repeats_assistant"]:
            issues.append(f"Verbatim assistant repeat detected {s['repeats_assistant']}x — sounds scripted")
        if s["placeholders"]:
            issues.append("Assistant response contained template placeholder text")
        if s["robotic"]:
            issues.append("Assistant used robotic AI phrasing")
        if s["lie_events"]:
            issues.append(f"User underreported or fibbed {s['lie_events']}x — truthfulness gap")
        if s["contradiction_events"]:
            issues.append(f"User contradicted earlier statements {s['contradiction_events']}x")
        for k, a, b in s["conflicts"]:
            issues.append(f"Conflicting facts stored for '{k}': '{a}' vs '{b}'")
        if s["objectives_total"] and not s["objective_completed"]:
            issues.append("Objective was set but not completed")
        if s["facts_total"] == 0:
            issues.append("No facts were stored — memory was not used")
        if s["whys"] == 0 and s["hypotheses"] == 0:
            issues.append("No patterns or hypotheses inferred from the conversation")
        if s["left_abrupt"]:
            issues.append("User left abruptly — no graceful close")
        if s["unsupported_numbers"]:
            issues.append("Assistant referenced values not backed by memory — hallucination risk")
        if s["interventions"] == 0 and n >= 5:
            issues.append("No recommendations were offered")
        if dims["naturalness"] >= 90 and s["repeats_assistant"] == 0 and s["placeholders"] == 0 \
                and s["robotic"] == 0:
            pass
        return issues[:8]

    def _recommendations(self, issues, dims):
        recs = []
        for i in issues:
            if "short" in i:
                recs.append("Keep sessions longer than 3 turns so coaching can take shape")
            elif "questions" in i or "probed" in i:
                recs.append("Ask one open follow-up question after each user message")
            elif "repeat" in i:
                recs.append("Vary response templates; avoid cycling the same text")
            elif "placeholder" in i:
                recs.append("Add a fallback that replaces unfilled templates before sending")
            elif "robotic" in i:
                recs.append("Remove AI self-references; keep responses conversational")
            elif "fibbed" in i or "truthfulness" in i:
                recs.append("Gently validate reported states; ask for specifics when plausible")
            elif "contradict" in i:
                recs.append("Call out conflicting statements kindly and update stored facts")
            elif "not completed" in i:
                recs.append("Nudge the objective to closure before ending the session")
            elif "memory" in i:
                recs.append("Store key facts every turn and reference them in responses")
            elif "patterns" in i or "hypotheses" in i:
                recs.append("Feed observations into the why engine to surface patterns")
            elif "abruptly" in i:
                recs.append("Offer a graceful close and a clear return path when a user leaves")
            elif "hallucination" in i:
                recs.append("Ground numeric claims in stored memory facts before responding")
            elif "recommendations" in i:
                recs.append("Rank and offer 2-3 concrete interventions once enough context exists")
        if not recs and dims["coaching"] < 60:
            recs.append("Deepen coaching: discover a goal, then plan one concrete routine")
        if not recs and dims["memory"] < 60:
            recs.append("Use memory: recall user facts and confirm new ones explicitly")
        return recs[:8]

    # ─── Record & storage ─────────────────────────────────────

    def _record(self, conversation_id, payload, meta, s, dims, issues):
        conv_dims = [k for k in DIMENSIONS if k not in ("coaching", "memory_usage")]
        conversation = int(round(sum(dims[k] for k in conv_dims) / len(conv_dims)))
        coaching = dims["coaching"]
        memory = dims["memory_usage"]
        overall = int(round((coaching + memory + conversation) / 3))
        recommendations = self._recommendations(issues, dims)
        record = {
            "conversation_id": conversation_id or f"conv_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "commit_id": self.commit_id,
            "generated_at": now_iso(),
            "overall_score": overall,
            "coaching": coaching,
            "memory": memory,
            "conversation": conversation,
            "dimensions": {k: {"score": dims[k], "rationale": _rationale(k, s, dims[k]),
                               "evidence": _evidence(k, s)}
                           for k in DIMENSIONS},
            "issues": issues,
            "recommendations": recommendations,
            "stats": {
                "turns": s["n"],
                "states": sorted(s["states"])[:6],
                "objectives": sorted(s["objectives"])[:6],
                "facts_total": s["facts_total"],
                "added_facts": s["added_total"],
                "beliefs": s["belief_count"],
                "whys": s["whys"],
                "hypotheses": s["hypotheses"],
                "interventions": s["interventions"],
                "questions": s["questions"],
                "trust_score": s["trust_score"],
                "ended": s.get("ended"),
            },
            "meta": dict(meta or {}),
        }
        return record

    def _store(self, record, meta):
        self._eval_dir.mkdir(parents=True, exist_ok=True)
        safe_id = re.sub(r"[^A-Za-z0-9_.-]", "_", record["conversation_id"])
        save_json(self._eval_dir / f"{safe_id}.json", record)
        index_path = self._eval_dir / "index.json"
        index = load_json(index_path)
        if index is None:
            index = {"entries": []}
        entries = {e["conversation_id"]: e for e in index.get("entries", [])}
        entries[record["conversation_id"]] = {
            "conversation_id": record["conversation_id"],
            "commit_id": record["commit_id"],
            "source": (meta or {}).get("source"),
            "persona": (meta or {}).get("persona"),
            "persona_label": (meta or {}).get("persona_label"),
            "batch": (meta or {}).get("batch"),
            "turns": record["stats"]["turns"],
            "overall": record["overall_score"],
            "coaching": record["coaching"],
            "memory": record["memory"],
            "conversation": record["conversation"],
            "dims": {k: record["dimensions"][k]["score"] for k in DIMENSIONS},
            "generated_at": record["generated_at"],
        }
        index["entries"] = sorted(entries.values(), key=lambda e: e["conversation_id"])
        index["last_updated"] = now_iso()
        save_json(index_path, index)


def _rationale(k, s, score):
    n = s["n"]
    table = {
        "coaching": lambda: (f"coaching states reached, {s['coaching_turns']}/{n} turns with coaching language"
                             if s["states"] & _COACHING_STATES
                             else f"little coaching structure across {n} turns"),
        "empathy": lambda: f"{s['empathy_turns']}/{n} turns showed empathetic language",
        "curiosity": lambda: f"{s['questions']} questions asked ({s['open_questions']} open)",
        "memory_usage": lambda: f"{s['facts_total']} facts stored, {s['added_total']} added this conversation",
        "personalization": lambda: f"{s['fact_refs']} turns referenced stored user facts, {s['belief_count']} beliefs active",
        "pattern_recognition": lambda: f"{s['whys']} patterns, {s['hypotheses']} hypotheses, {s['belief_count']} beliefs",
        "recommendation_quality": lambda: f"{s['interventions']} interventions (top conf {s['intervention_conf']:.0f})",
        "naturalness": lambda: f"{s['repeats_assistant']} repeats, {s['placeholders']} placeholders, {s['robotic']} robotic turns",
        "objective_completion": lambda: f"{s['objective_completed']} of {s['objectives_total']} objectives completed",
        "hallucination_risk": lambda: f"{s['unsupported_numbers']} unsupported numeric claims, {s['placeholders']} placeholders",
        "contradictions": lambda: f"{s['contradiction_events']} contradictions, {s['lie_events']} fibs, {len(s['conflicts'])} fact conflicts",
        "trust": lambda: f"trust {s['trust_score'] if s['trust_score'] is not None else 'n/a'}, {s['open_up_events']} open-ups, {s['lie_events']} fibs",
        "return": lambda: f"ended='{s.get('ended')}', {s['day_gaps']} returns across days, final emotion {s['final_emotion'] or 'n/a'}",
    }
    try:
        return table[k]()
    except Exception:
        return ""


def _evidence(k, s):
    n = s["n"]
    if k == "coaching" and s["states"] & _COACHING_STATES:
        return sorted(s["states"] & _COACHING_STATES)[:3]
    if k == "curiosity":
        return ["question_planner_route"] if s["question_route"] else []
    if k == "memory_usage":
        return ["facts_stored", "beliefs"] if s["facts_total"] else []
    if k == "pattern_recognition":
        return [f"{s['whys']} why-patterns", f"{s['hypotheses']} hypotheses"]
    if k == "recommendation_quality":
        return [f"top_conf={s['intervention_conf']:.0f}"] if s["interventions"] else []
    if k == "contradictions":
        return [f"conflict {a}->{b}" for _, a, b in s["conflicts"]] + \
               [f"{s['lie_events']} lies", f"{s['contradiction_events']} contradictions"]
    if k == "trust":
        return [f"trust={s['trust_score']}"] if s["trust_score"] is not None else []
    return []
