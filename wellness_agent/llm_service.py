"""Groq LLM service wrapper — single interface for all model calls."""

import os
import json
import re
from typing import Optional

_GROQ_AVAILABLE = False
try:
    from groq import Groq
    _GROQ_AVAILABLE = True
except ImportError:
    pass


class GroqLLM:
    """Thin wrapper around Groq's API with prompt templates."""

    def __init__(self, api_key: Optional[str] = None, model: str = "llama-3.3-70b-versatile"):
        self.api_key = api_key or os.environ.get("GROQ_API_KEY", "")
        self.model = model
        self.client = None
        self._fallback = False

        if _GROQ_AVAILABLE and self.api_key:
            try:
                self.client = Groq(api_key=self.api_key, max_retries=0, timeout=15.0)
            except Exception:
                self._fallback = True
        else:
            self._fallback = True

        if self._fallback:
            print("[LLM] Groq not configured — using rule-based fallback")

    def is_available(self) -> bool:
        return self.client is not None and not self._fallback

    def _call(self, system: str, user: str, temperature: float = 0.3, max_tokens: int = 1024) -> str:
        if not self.is_available():
            return ""

        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            print(f"[LLM] API error: {e}")
            return ""

    def _extract_json(self, text: str) -> dict:
        """Extract JSON from LLM response, handling markdown fences."""
        text = text.strip()
        text = re.sub(r'^```(?:json)?\s*', '', text)
        text = re.sub(r'\s*```$', '', text)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(0))
                except json.JSONDecodeError:
                    pass
            return {}

    # ─── Phase 2: Orchestrator Router ───────────────────────────

    ROUTER_SYSTEM = """You are the Conversation Orchestrator. You decide which internal agents should run for this turn.
Available agents: emotion_detection, memory_manager, root_cause_engine, recommendation_engine, question_planner, routine_generator, report_generator, reflection_agent.

Rules:
- Always include emotion_detection first.
- If risk signal detected, route ONLY to risk_protocol.
- Only call agents that are needed this turn.

Output JSON only:
{ "risk_detected": boolean, "route": ["agent_name", ...], "reason": "one sentence", "next_state_hint": "state or null" }"""

    def route_turn(self, user_message: str, current_state: str, memory_snapshot: dict, last_turns: list) -> dict:
        if not self.is_available():
            return {}
        inp = json.dumps({"user_message": user_message, "current_state": current_state,
                          "memory_snapshot": memory_snapshot, "last_3_turns": last_turns[-3:]})
        raw = self._call(self.ROUTER_SYSTEM, inp)
        return self._extract_json(raw)

    # ─── Phase 3: State Transition Decider ─────────────────────

    TRANSITION_SYSTEM = """You decide conversation state transitions. You are given the current state, its exit conditions, and the latest exchange. Determine if an exit condition is met, and if so, which state to move to.
Output JSON only:
{ "exit_met": boolean, "next_state": "...", "confidence": 0-100, "reason": "one sentence" }"""

    def decide_transition(self, current_state: str, exit_conditions: list, latest_exchange: str, memory_snapshot: dict) -> dict:
        if not self.is_available():
            return {}
        inp = json.dumps({"current_state": current_state, "exit_conditions": exit_conditions,
                          "latest_exchange": latest_exchange, "memory_snapshot": memory_snapshot})
        raw = self._call(self.TRANSITION_SYSTEM, inp)
        return self._extract_json(raw)

    # ─── Phase 4: Memory Extraction ────────────────────────────

    MEMORY_SYSTEM = """You extract durable facts from a single conversation turn to update long-term memory.
For each fact found, output category (identity|goals|habits|emotional_history|personality), key, value, confidence (0-100), and source ("conversation").
Only extract what's actually stated or strongly implied — never invent. Omit anything under 40 confidence.
If a fact conflicts with existing memory, set action to "update".
Output JSON array only: [{"action":"add|update","category":"...","key":"...","value":"...","confidence":0-100,"source":"conversation"},...]"""

    def extract_memory(self, message: str, existing_memory: dict) -> list:
        if not self.is_available():
            return []
        inp = json.dumps({"message": message, "existing_memory_for_topic": existing_memory})
        raw = self._call(self.MEMORY_SYSTEM, inp, temperature=0.2)
        result = self._extract_json(raw)
        if isinstance(result, list):
            return result
        if isinstance(result, dict) and "facts" in result:
            return result["facts"]
        return [result] if result else []

    # ─── Phase 5: Emotion Extraction ───────────────────────────

    EMOTION_SYSTEM = """You analyze one user message and score it across the dimensions below. Scores are relative signals for tracking trends over time, NOT clinical measurements.
Score every dimension. Infer conservatively from tone, word choice, and context.

Dimensions: primary_emotion (string), secondary_emotion (string), emotional_intensity (0-100), confidence (0-100), avoidance (0-100), stress (0-100), motivation (0-100), hope (0-100), energy (0-100), engagement (0-100), trust (0-100), loneliness (0-100), frustration (0-100), burnout (0-100), anxiety (0-100), depression_risk (0-100), self_esteem (0-100), risk_flag (boolean), risk_reason (string or null).

Set risk_flag=true ONLY for explicit or strongly implied self-harm, suicidal ideation, or intent to harm others — not for general sadness. When in doubt on risk_flag, err toward true.

Output JSON only matching the full schema."""

    def extract_emotion(self, message: str, recent_context: list) -> dict:
        if not self.is_available():
            return {}
        inp = json.dumps({"message": message, "recent_context": recent_context[-5:]})
        raw = self._call(self.EMOTION_SYSTEM, inp, temperature=0.1)
        return self._extract_json(raw)

    # ─── Phase 6/7: Direct Answer (Conversation Planner V2) ───

    ANSWER_SYSTEM = """You answer a direct user question about their wellbeing. Rules:
1. Ground the answer ONLY in the provided context (facts, patterns, hypotheses).
2. Never diagnose, never invent facts, never give medical advice.
3. Be warm, honest, and 1-4 sentences.
4. If the context gives no basis for an answer, say so plainly and offer to explore together.

Output plain text only, no JSON."""

    def generate_answer(self, user_message: str, answer_context: dict) -> str:
        if not self.is_available():
            return ""
        inp = json.dumps({"user_message": user_message, "context": answer_context})
        return self._call(self.ANSWER_SYSTEM, inp, temperature=0.4, max_tokens=256)

    # ─── Phase 6/7: Question Generation ───────────────────────

    QUESTION_SYSTEM = """You write the next question to ask the user, given a target topic and conversation state. Match tone to state — warmer in Rapport Building, more direct in Deep Investigation.

Question types and when to use them:
- Open: broad entry into a new topic
- Reflective: mirrors back what they said to deepen it
- Choice: 3-5 options when the user likely wants low-effort input
- Scaling: numeric/intensity check ("On a scale of 1-10...")
- Clarifying: resolves ambiguity in a prior answer
- Future: forward-looking
- Motivational: connects to stated goals
- Narrative: invites a short story
- Challenge: gently questions a pattern

Choose the type that fits, don't default to Open every time.

Output JSON only: {"question_type":"...","question_text":"...","response_options":["..."] or null}"""

    def generate_question(self, target_pillar: str, current_state: str, memory_context: dict,
                          question_type_hint: str = "") -> dict:
        if not self.is_available():
            return {}
        inp = json.dumps({"target_pillar": target_pillar, "current_state": current_state,
                          "preferred_type_hint": question_type_hint, "memory_context": memory_context})
        raw = self._call(self.QUESTION_SYSTEM, inp, temperature=0.7, max_tokens=256)
        return self._extract_json(raw)

    # ─── Phase 8: Root Cause Analysis ─────────────────────────

    RCA_SYSTEM = """You build a causal reasoning chain from accumulated memory and emotion data for one wellness pillar. Find correlations and plausible explanations — NOT proof. Frame conclusions probabilistically.

Build the chain as linked observations, each with confidence, ending in a most-likely root cause with overall probability. Use only data actually present in the input.

Output JSON only:
{"chain":[{"observation":"...","confidence":0-100}],"likely_root_cause":"...","probability":0-100,"caveat":"Correlational, based on self-reported data — not a diagnosis."}"""

    def analyze_root_cause(self, pillar: str, memory_facts: list, emotion_history: list, habit_trends: dict) -> dict:
        if not self.is_available():
            return {}
        inp = json.dumps({"pillar": pillar, "memory_facts": memory_facts,
                          "emotion_history": emotion_history, "habit_trends": habit_trends})
        raw = self._call(self.RCA_SYSTEM, inp, temperature=0.4, max_tokens=512)
        return self._extract_json(raw)

    # ─── Phase 9: Routine Generation ──────────────────────────

    ROUTINE_SYSTEM = """You generate a routine plan based on a root cause or user-stated goal, plus known constraints.

Rules:
- Ground every recommendation in the user's actual data
- Keep to 3-5 concrete, small actions
- Never recommend anything requiring medical supervision without disclaimer
- Reference existing habit data so it feels like a next step

Output JSON only:
{"routine_type":"morning|work|stress|sleep|exercise|...","actions":[{"action":"...","why":"grounded in data","time_of_day":"...","difficulty":"easy|medium"}],"review_after_days":7}"""

    def generate_routine(self, root_cause_or_goal: str, memory_facts: list, past_adherence: dict, constraints: dict) -> dict:
        if not self.is_available():
            return {}
        inp = json.dumps({"root_cause_or_goal": root_cause_or_goal, "memory_facts": memory_facts,
                          "past_adherence": past_adherence, "constraints": constraints})
        raw = self._call(self.ROUTINE_SYSTEM, inp, temperature=0.5, max_tokens=512)
        return self._extract_json(raw)

    # ─── Phase 10: Report Generation ──────────────────────────

    REPORT_SYSTEM = """You generate a wellness report strictly from the structured data provided. Never invent a number or observation not present in the input.

Include: trend summary, 2-3 observations connecting metrics (correlational framing only), and 1-2 suggested goals.

Output JSON only:
{"summary":"2-3 sentences","trends":[{"metric":"...","direction":"up|down|flat","value":"...","change":"..."}],"observations":["..."],"suggested_goals":["..."]}"""

    def generate_report(self, period: str, metrics: dict, prior_metrics: dict, achievements: list) -> dict:
        if not self.is_available():
            return {}
        inp = json.dumps({"period": period, "metrics": metrics,
                          "prior_period_metrics": prior_metrics, "achievements": achievements})
        raw = self._call(self.REPORT_SYSTEM, inp, temperature=0.3, max_tokens=512)
        return self._extract_json(raw)

    # ─── Phase 10: Crisis / Reflection Response ───────────────

    CRISIS_SYSTEM = """You are responding to a user who may be in crisis. Your response must:
1. Thank them for sharing
2. Provide crisis resource information (988 in US, or local equivalent)
3. Be warm, grounded, and non-clinical
4. Not try to diagnose or therapize

Output a short, warm paragraph."""

    def generate_crisis_response(self, user_message: str, risk_reason: str) -> str:
        if not self.is_available():
            return ""
        inp = json.dumps({"user_message": user_message, "risk_indicator": risk_reason})
        return self._call(self.CRISIS_SYSTEM, inp, temperature=0.5, max_tokens=256)

    REFLECTION_SYSTEM = """You are closing out a wellness conversation. Generate a warm, brief closing message that:
- Acknowledges what was discussed
- Leaves the door open for next time
- Is 1-3 sentences
"""

    def generate_reflection(self, state_info: dict, recent_context: list) -> str:
        if not self.is_available():
            return ""
        inp = json.dumps({"state_info": state_info, "recent_exchange": recent_context[-2:] if recent_context else []})
        return self._call(self.REFLECTION_SYSTEM, inp, temperature=0.6, max_tokens=200)
