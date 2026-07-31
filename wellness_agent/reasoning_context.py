"""ReasoningContext — per-turn structured reasoning state.

Assembled deterministically from engine outputs BEFORE any LLM prompt, so the
LLM only writes natural language. The LLM never decides the coaching objective,
the intervention, the active hypotheses, or the behavior profile — those are
already fixed here, sourced from the objective / behavior / hypothesis / why
engines and the intervention ranking engine.

Every response from the orchestrator carries this object (turn_result,
get_summary, /chat). Shape:

{
 "conversation_objective": "",
 "objective_reason": "",
 "active_hypotheses": [],
 "behavior_traits": [],
 "top_patterns": [],
 "recommended_intervention": {},
 "conversation_mode": "",
 "response_style": "",
 "confidence_summary": {},
 "memory_summary": {}
}

Near-zero latency — plain dict assembly, no LLM calls.
"""

_STATE_MODES = {
    "greeting": "opening",
    "guided_discovery": "discovery",
    "pillar_selection": "discovery",
    "deep_investigation": "investigation",
    "insight_generation": "insight",
    "routine_planning": "planning",
    "reflection": "reflection",
    "follow_up": "follow_up",
    "weekly_review": "review",
    "rapport_building": "rapport",
    "avoidance_detection": "rapport",
    "soft_exploration": "exploration",
    "free_conversation": "open_dialogue",
}

_STYLE_BY_TRAIT = [
    ("prefers_short_answers", "concise"),
    ("analytical", "evidence_focused"),
    ("reflective_thinker", "reflective"),
    ("overwhelmed_by_choices", "simple"),
    ("motivated_by_progress", "progress_oriented"),
    ("likes_structured_routines", "structured"),
]


def conversation_mode(state, risk_flag=False):
    """Map the state machine state to a coach-facing conversation mode."""
    if risk_flag:
        return "crisis_support"
    return _STATE_MODES.get(state or "", "open_dialogue")


def response_style(active_traits):
    """Derive a response style from the learned behavior profile (deterministic)."""
    traits = set(active_traits or [])
    for trait, style in _STYLE_BY_TRAIT:
        if trait in traits:
            return style
    return "supportive"


def _objective_reason(objective):
    objective = objective or {}
    name = objective.get("objective", "")
    reason = objective.get("reason", "")
    confidence = objective.get("confidence", 0)
    if name and reason:
        return f"{reason} (confidence {confidence}%)"
    if name:
        return f"Selected objective '{name}' (confidence {confidence}%)"
    return ""


def build_reasoning_context(*, objective=None, active_hypotheses=None, behavior_traits=None,
                            top_patterns=None, recommended_intervention=None,
                            state=None, risk_flag=False,
                            confidence_summary=None, memory_summary=None,
                            learning_summary=None):
    """Assemble the ReasoningContext object from existing engine outputs.

    All arguments are optional; the returned dict always has the full shape.
    `learning_summary` is per-user learning (never cross-user); the key is only
    present for live users who have completed conversations, so the context
    shape stays stable for everyone else.
    """
    ctx = {
        "conversation_objective": (objective or {}).get("objective", ""),
        "objective_reason": _objective_reason(objective),
        "active_hypotheses": list(active_hypotheses or []),
        "behavior_traits": list(behavior_traits or []),
        "top_patterns": list(top_patterns or []),
        "recommended_intervention": dict(recommended_intervention or {}),
        "conversation_mode": conversation_mode(state, risk_flag),
        "response_style": response_style(behavior_traits or []),
        "confidence_summary": dict(confidence_summary or {}),
        "memory_summary": dict(memory_summary or {}),
    }
    if learning_summary:
        ctx["learning_summary"] = dict(learning_summary)
    return ctx
