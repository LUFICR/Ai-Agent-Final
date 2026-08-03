"""Planner Debug Trace System — full execution traces for diagnosis.

PURE DIAGNOSTICS ONLY. This module never changes planner behavior:

- it wraps ``Orchestrator.process_message`` (instance level) and records
  every stage of the turn without touching the executed code path;
- the planner decision tree is *replayed* after the real decision ran,
  using a pre-turn snapshot plus the planner's own read-only signal
  detectors — the replay never mutates the planner;
- violations and per-turn scores are computed afterwards over the
  recorded turns.

Outputs (one set per conversation, under ``data/debug_traces/``):

- ``conversation_<id>.json`` — the full structured trace;
- ``conversation_<id>.md``   — the human-readable report (every turn,
  the conversation decision graph, violation detection, planner scores).

Enable in app.py with ``DEBUG_TRACE=1``; enable in scripts/tests by
calling ``install_tracer(orchestrator, trace_dir=...)``.

Facts worth knowing while reading a trace:

- the orchestrator's LLM (Groq) is nondeterministic: emotion scores and
  generated question texts vary run to run, but the planner decisions
  are deterministic from the context the orchestrator assembles;
- the intent resolver is deterministic: the same context produces the
  same IntentGraph.
"""

import json
import logging
import os
import re
import threading
import time
from pathlib import Path

from . import branch_policy
from .conversation_planner import (
    ConversationMode,
    PlannerAction,
    _ACCEPT_RE,
    _CASUAL_RE,
    _REJECT_RE,
    _SWITCH_RE,
    _TIME_RE,
    _UNCERTAINTY_RE,
    _QUICK_REPLY_OPEN_STATES,
    _QUICK_REPLY_SUPPRESSED_MODES,
    _TEMPORARY_MODES,
    _VALID_TRANSITIONS,
)
from .conversation_logger import _git_commit, mask_secrets
from .utils.storage import now_iso

DEFAULT_TRACE_DIR = Path(__file__).resolve().parent.parent / "data" / "debug_traces"
DEBUG_TRACER_ENABLED = os.environ.get("DEBUG_TRACE", "0") == "1"

_TRACER_VERSION = "1.0.0"
_ASKING_ACTIONS = ("ask_question", "explore_topic", "clarify")

_log = logging.getLogger("wellness_agent.debug_tracing")


# ─── serialization helpers ─────────────────────────────────────────────

def _json_default(o):
    if hasattr(o, "to_dict"):
        return o.to_dict()
    if isinstance(o, set):
        return sorted(str(x) for x in o)
    if isinstance(o, tuple):
        return list(o)
    if isinstance(o, Path):
        return str(o)
    if hasattr(o, "value"):  # str-enums / simple enums
        return o.value
    return str(o)


def _dumps(obj):
    return json.dumps(obj, default=_json_default, indent=2, ensure_ascii=False)


def _normalize(message):
    return re.sub(r"\s+", " ", (message or "").strip().lower())


def _action(decision):
    """Extract the action name from a PlannerDecision or dict (never None)."""
    if decision is None:
        return None
    value = getattr(decision, "action", None)
    if value is None and isinstance(decision, dict):
        return decision.get("action")
    if isinstance(value, PlannerAction):
        return value.value
    if value is not None:
        return str(value)
    return None


# ─── planner snapshot (read-only view of pre-turn state) ───────────────

class _PlannerSnapshot:
    """Pre-turn planner + state machine + branch state (all reads)."""

    __slots__ = ("planner", "mode", "previous_mode", "discovery_exited",
                 "asking_streak", "ladder_idx", "pending_recommendation",
                 "commit_stage", "last_action", "branch_state", "state",
                 "state_turns", "pillar", "avoidance_count")

    def __init__(self, orch):
        planner = orch.agents.planner
        self.planner = planner
        self.mode = planner.mode
        self.previous_mode = planner.previous_mode
        self.discovery_exited = planner._discovery_exited
        self.asking_streak = planner._asking_streak
        self.ladder_idx = planner._ladder_idx
        self.pending_recommendation = planner._pending_recommendation
        self.commit_stage = planner._commit_stage
        self.last_action = _action(planner.last_decision)
        bs = planner._branch_state
        self.branch_state = (dict(bs) if bs else None)
        self.state = orch.state_machine.current_state
        self.state_turns = orch.state_machine.turns_in_state
        self.pillar = orch.current_pillar
        self.avoidance_count = orch.avoidance_count

    def mode_value(self):
        return self.mode.value if self.mode else None

    def previous_mode_value(self):
        return self.previous_mode.value if self.previous_mode else None


def _branch_summary(snapshot):
    branch = branch_policy.branch_for_pillar(snapshot.pillar)
    if branch is None:
        return None
    definition = branch_policy.BRANCH_DEFINITIONS[branch]
    filled = set((snapshot.branch_state or {}).get("filled") or ())
    required = set(definition["required_slots"])
    required_filled = required & filled
    return {
        "branch": branch,
        "pillar": snapshot.pillar,
        "completion_score": round(100.0 * len(required_filled) / len(required), 1),
        "threshold": definition["completion_threshold"],
        "required_filled": sorted(required_filled),
        "required_slots": sorted(required),
        "filled": sorted(filled),
        "missing": sorted(required - filled),
        "completed": bool((snapshot.branch_state or {}).get("completed")),
        "next_actions": list(definition["next_actions"]),
    }


# ─── decision-tree replay (pure; mirrors ConversationPlanner.decide) ───

class _Shadow:
    """Local replica of the planner's mutable state used by the replay.

    Mirrors only what decide() and its helpers read and assign, so the
    replay branches exactly like the real code but never touches the
    real planner object.
    """

    def __init__(self, snap):
        self.mode = snap.mode
        self.previous_mode = snap.previous_mode
        self.discovery_exited = snap.discovery_exited
        self.asking_streak = snap.asking_streak
        self.ladder_idx = snap.ladder_idx
        self.pending_recommendation = snap.pending_recommendation
        self.commit_stage = snap.commit_stage
        self.last_action = snap.last_action
        if snap.branch_state:
            self.branch_state = {"pillar": snap.branch_state.get("pillar"),
                                 "filled": set(snap.branch_state.get("filled") or ()),
                                 "completed": bool(snap.branch_state.get("completed"))}
        else:
            self.branch_state = None

    def enter_mode(self, next_mode, by="", force=False):
        if next_mode == self.mode:
            return True
        if next_mode == ConversationMode.DISCOVERY:
            if self.discovery_exited and not force:
                return False
        elif self.mode is not None and not force:
            if next_mode not in _TEMPORARY_MODES and next_mode != ConversationMode.ESCALATION:
                if next_mode not in _VALID_TRANSITIONS.get(self.mode, set()):
                    return False
        if next_mode == ConversationMode.DISCOVERY:
            self.discovery_exited = False
        else:
            if self.mode is not None:
                self.discovery_exited = True
        self.mode = next_mode
        return True


def _is_rich(message):
    from_stage = _MODE_TO_LIFECYCLE_STAGE.get(from_mode)
    to_stage = _MODE_TO_LIFECYCLE_STAGE.get(to_mode)
    if from_stage is None or to_stage is None:
        return True
    if is_valid_transition(from_stage, to_stage):
        return True
    return to_mode in _TEMPORARY_MODES or to_mode == ConversationMode.ESCALATION


def _is_rich(message):
    words = (message or "").split()
    if not words:
        return False
    if len(words) >= 8:
        return True
    if len(words) < 3:
        return False
    return _has_emotion_keyword(message) or _has_topic_signal(message)


def _button_mode_choice(ctx):
    """Read-only copy of the Button Policy (True → choice buttons)."""
    if _is_rich(ctx.get("message")):
        return False
    message = (ctx.get("message") or "").strip()
    if _UNCERTAINTY_RE.search(message):
        return True
    ig = ctx.get("intent_graph") or {}
    confidence = (ig.get("confidence_scores") or {}).get("overall_confidence")
    if confidence is None:
        confidence = ig.get("overall_confidence")
    if isinstance(confidence, (int, float)) and confidence < 0.60:
        return True
    if (ctx.get("avoidance_count") or 0) >= 2:
        return True
    state = ctx.get("state") or ""
    if state in ("guided_discovery", "pillar_selection") and not ctx.get("minimal_input"):
        return True
    return False


def replay_decision_tree(snapshot, ctx, final_decision):
    """Read-only replay of ConversationPlanner.decide().

    Evaluates every candidate in the planner's exact decision order using
    the planner's own pure detectors plus a pre-turn snapshot. Returns
    the tree of candidates with win/lose reasons, the replayed winner and
    whether the replay matches the real final decision. Can never mutate
    the planner — errors are returned, never raised.
    """
    try:
        return _replay_decision_tree(snapshot, ctx, final_decision)
    except Exception as exc:  # noqa: BLE001 — diagnostics must never break the turn
        _log.warning("decision-tree replay failed: %s", exc)
        return {"tree": [{"step": 0, "candidate": "(trace error)", "status": "error",
                          "why": "%s: %s" % (type(exc).__name__, exc)}],
                "winner": _action(final_decision), "replay_matches": None}


def _replay_decision_tree(snapshot, ctx, final_decision):
    planner = snapshot.planner
    message = (ctx.get("message") or "").strip()
    ig = ctx.get("intent_graph") or {}
    emotion = ctx.get("emotion") or {}
    shadow = _Shadow(snapshot)
    tree = []

    def add(step, candidate, status, why):
        tree.append({"step": step, "candidate": candidate,
                     "status": status, "why": why})

    def finish(winner, matches):
        return {"tree": tree, "winner": winner,
                "replay_matches": bool(matches)}

    # decide() step 1 — escalation (always first)
    primary_intent = (ig.get("primary_intent") or {}).get("intent", "")
    if emotion.get("risk_flag") or primary_intent == "crisis":
        add(1, "escalate", "selected",
            "risk_flag or primary intent 'crisis'")
        return finish("escalate", _action(final_decision) == "escalate")

    # decide() step 2 — interruption recovery
    if snapshot.mode in _TEMPORARY_MODES and snapshot.previous_mode is not None:
        if planner._is_topic_switch(message, ig):
            add(2, "switch_topic (interruption recovery)", "selected",
                "topic switch while an interruption was active")
        elif planner._is_wellness_concern(message, ig):
            add(2, "resume_topic (interruption recovery)", "selected",
                "wellness concern while an interruption was active")
        elif planner._is_casual(message):
            add(2, "casual_chat (interruption recovery)", "selected",
                "casual signal while an interruption was active")
        elif planner._is_capability(message):
            add(2, "answer_capability (interruption recovery)", "selected",
                "capability while an interruption was active")
        elif planner._is_direct_question(message):
            add(2, "answer_direct_question (interruption recovery)", "selected",
                "direct question while an interruption was active")
        else:
            add(2, "resume previous mode", "selected",
                "message unrelated to the interruption; restoring %s"
                % (snapshot.previous_mode.value if snapshot.previous_mode else "none"))
        return finish(_action(final_decision), True)
    add(2, "interruption recovery", "rejected",
        "no interruption active (mode=%s, previous_mode=%s)"
        % (snapshot.mode_value(), snapshot.previous_mode_value()))

    # decide() steps 3-7 — pure signal detectors (first match wins)
    def signal(step, name, matched, why_hit, why_miss):
        status = "selected" if matched else "rejected"
        why = why_hit if matched else why_miss
        add(step, name, status, why)
        return matched

    if signal(3, "answer_capability", planner._is_capability(message),
              "message matches the capability regex",
              "no capability question in the message"):
        return finish("answer_capability",
                      _action(final_decision) == "answer_capability")
    if signal(4, "switch_topic", planner._is_topic_switch(message, ig),
              "explicit topic switch (regex or graph branch_change/topic_shift)",
              "no switch request (graph: topic_shift=%s branch_change=%s)"
              % (bool(ig.get("topic_shift")), bool(ig.get("branch_change_requested")))):
        return finish("switch_topic", _action(final_decision) == "switch_topic")
    if signal(5, "close_conversation (goodbye)", planner._is_goodbye(message),
              "message matches the goodbye regex",
              "no goodbye phrase"):
        return finish("close_conversation",
                      _action(final_decision) == "close_conversation")
    if signal(6, "casual_chat", planner._is_casual(message),
              "message matches the casual-chat regex",
              "no casual-chat request"):
        return finish("casual_chat", _action(final_decision) == "casual_chat")
    if signal(7, "answer_direct_question", planner._is_direct_question(message),
              "message is a direct question",
              "no direct question signal"):
        return finish("answer_direct_question",
                      _action(final_decision) == "answer_direct_question")

    # decide() step 8a — commitment flow
    if shadow.mode == ConversationMode.COMMITMENT:
        if _REJECT_RE.match(message):
            add(8, "close_conversation (commitment declined)", "selected",
                "user declined the commitment")
            winner = "close_conversation"
        elif shadow.commit_stage == "proposed" and (
                _ACCEPT_RE.match(message) or _TIME_RE.search(message)):
            add(8, "schedule_action", "selected",
                "commitment accepted; scheduling the action")
            winner = "schedule_action"
        elif shadow.commit_stage == "proposed":
            add(8, "wait (commitment pause)", "selected",
                "commitment proposed; waiting for the user's answer")
            winner = "wait"
        else:
            add(8, "close_conversation (commitment scheduled)", "selected",
                "commitment scheduled; closing the conversation")
            winner = "close_conversation"
        return finish(winner, _action(final_decision) == winner)

    # decide() step 8b — recommendation acceptance
    if shadow.mode == ConversationMode.COACHING and shadow.pending_recommendation:
        if _ACCEPT_RE.match(message) or _TIME_RE.search(message):
            add(8, "create_commitment", "selected", "recommendation accepted")
        elif _REJECT_RE.match(message):
            add(8, "summarize", "selected",
                "recommendation declined; summarizing before closure")
        else:
            add(8, "provide_recommendation (pending)", "selected",
                "recommendation pending; no acceptance or decline yet")
        return finish(_action(final_decision), True)
    if shadow.pending_recommendation:
        add(8, "recommendation reply", "rejected",
            "pending recommendation is set but mode=%s" % shadow.mode_value())

    # decide() step 8c — summarization exit
    if shadow.mode == ConversationMode.SUMMARIZATION:
        add(8, "close_conversation (summarization)", "selected",
            "summarization exits to closure")
        return finish("close_conversation",
                      _action(final_decision) == "close_conversation")

    # decide() step 8d — branch completion gate
    branch = branch_policy.branch_for_pillar(ctx.get("current_pillar"))
    gate_active = shadow.mode in (None, ConversationMode.DISCOVERY,
                                  ConversationMode.INVESTIGATION)
    if branch is None or not gate_active:
        if branch is None:
            add(8, "branch completion gate", "rejected",
                "no branch for pillar %r" % ctx.get("current_pillar"))
        else:
            add(8, "branch completion gate", "rejected",
                "mode %s outside discovery/investigation" % shadow.mode_value())
    else:
        fills = branch_policy.detect_slot_fills(
            message, ctx.get("current_pillar"), ig)
        if not fills:
            add(8, "branch completion gate", "rejected",
                "no slot evidence in this message for branch '%s'" % branch)
        else:
            if shadow.branch_state is None or \
                    shadow.branch_state.get("pillar") != ctx.get("current_pillar"):
                shadow.branch_state = {"pillar": ctx.get("current_pillar"),
                                       "filled": set(), "completed": False}
            shadow.branch_state["filled"].update(fills)
            definition = branch_policy.BRANCH_DEFINITIONS[branch]
            required = set(definition["required_slots"])
            filled_required = required & shadow.branch_state["filled"]
            if shadow.branch_state.get("completed"):
                add(8, "branch completion gate", "rejected",
                    "branch already completed (one-shot)")
            elif len(filled_required) < definition["completion_threshold"]:
                add(8, "branch completion gate", "rejected",
                    "threshold not met yet: %d/%d required filled"
                    % (len(filled_required), len(required)))
            else:
                add(8, "provide_insight (branch complete)", "selected",
                    "branch complete: %d/%d required slots filled"
                    % (len(filled_required), len(required)))
                return finish("provide_insight",
                              _action(final_decision) == "provide_insight")

    # decide() step 9 — state-machine-driven flow (deterministic branch order)
    winner, reason = _replay_state_flow(ctx)
    add(9, "state flow", "selected", reason)

    # decide() step 10 — loop guard (max-two questions)
    progress = bool(ig.get("answered_current_question")) or bool(ig.get("new_slots_detected"))
    primary = (ig.get("primary_intent") or {}).get("intent", "")
    asking = winner in _ASKING_ACTIONS
    if progress or primary in ("answer", "additional_information", "commitment", "goal_update"):
        guard_streak = 0
    elif asking and snapshot.last_action in _ASKING_ACTIONS:
        guard_streak = snapshot.asking_streak + 1
    else:
        guard_streak = 0
    if guard_streak >= 2 and asking:
        add(9, "loop guard (max-two questions)", "selected",
            "two consecutive questions asked — provide value now")
        winner = "provide_insight"
    return finish(winner, _action(final_decision) == winner)


def _replay_state_flow(ctx):
    """Replay of _state_flow(): returns (winning action, reason)."""
    state = ctx.get("state") or ""
    route = ctx.get("route") or []
    avoidance = ctx.get("avoidance_count") or 0
    exit_offered = ctx.get("exit_offered") or False
    exit_consumed = ctx.get("exit_consumed") or False
    objective = ctx.get("objective") or ""
    ig = ctx.get("intent_graph") or {}

    if state == "greeting":
        return "ask_question", "greeting policy: welcome naturally, one open question"
    if "question_planner" in route and avoidance == 1 and not exit_consumed \
            and not ctx.get("minimal_input"):
        return "clarify", "avoidance: force choice with concrete options"
    if avoidance >= 3 and not exit_offered and not exit_consumed:
        return "wait", "repeated avoidance: offer to end the conversation"
    if state != "greeting" and _is_rich(ctx.get("message")):
        return "explore_topic", "rich free text: continue naturally"
    if "question_planner" in route:
        if state == "deep_investigation":
            return "explore_topic", "deepening understanding of the active branch"
        if _button_mode_choice(ctx):
            return "clarify", "fallback: user cannot articulate — choice buttons"
        return "ask_question", "discovery question"
    if "root_cause_engine" in route and ctx.get("current_pillar"):
        return "provide_insight", "enough investigation confidence: share the pattern"
    if "routine_generator" in route:
        return "provide_recommendation", "investigation complete: offer a recommendation"
    if objective == "close_conversation" and state != "greeting":
        return "close_conversation", "objective is conversation closure"
    if state == "reflection":
        return "reflect", "reflection mode: prioritize listening"
    if state == "follow_up":
        return "check_progress", "follow-up: review progress on commitments"
    slot_progress = bool(ig.get("answered_current_question")) or bool(ig.get("new_slots_detected"))
    if slot_progress and state not in ("greeting", "reflection", "follow_up"):
        return "explore_topic", "slot completed: keep the active branch"
    if state == "free_conversation":
        return "ask_question", "open dialogue: keep coaching momentum"
    if state == "rapport_building":
        return "ask_question", "rapport building: low-pressure coaching question"
    if state == "avoidance_detection":
        return "wait", "avoidance: offer choices without pressure"
    if state == "soft_exploration":
        return "ask_question", "soft exploration: gentle opening"
    if state == "insight_generation":
        return "provide_insight", "insight already delivered: check in"
    return "ask_question", "default: keep momentum"


# ─── per-turn section builders ─────────────────────────────────────────

def _intent_section(ig):
    ig = ig or {}
    primary = ig.get("primary_intent") or {}
    secondaries = ig.get("secondary_intents") or []
    backgrounds = ig.get("background_intents") or []
    return {
        "primary_intent": primary.get("intent"),
        "secondary_intents": [i.get("intent") for i in secondaries],
        "background_intents": [i.get("intent") for i in backgrounds],
        "confidence": {
            "overall": ig.get("overall_confidence"),
            "primary": primary.get("confidence"),
            "secondary": {i.get("intent"): i.get("confidence") for i in secondaries},
            "background": {i.get("intent"): i.get("confidence") for i in backgrounds},
        },
        "intent_graph": {
            "continue_branch": ig.get("continue_branch"),
            "branch_change_requested": ig.get("branch_change_requested"),
            "answered_current_question": ig.get("answered_current_question"),
            "new_slots_detected": list(ig.get("new_slots_detected") or []),
            "topic_shift": ig.get("topic_shift"),
            "emotion_shift": ig.get("emotion_shift"),
            "interruption": ig.get("interruption"),
            "correction": ig.get("correction"),
            "requires_clarification": ig.get("requires_clarification"),
            "reason": ig.get("reason"),
        },
        "why_this_intent_won": {
            "evidence": list(primary.get("evidence") or []),
            "notes": primary.get("notes"),
            "priority": primary.get("priority"),
            "level": primary.get("level"),
        },
        "why_others_lost": [
            {"intent": i.get("intent"), "confidence": i.get("confidence"),
             "level": i.get("level"),
             "evidence": list(i.get("evidence") or [])}
            for i in (list(secondaries) + list(backgrounds))
        ],
        "keyword_matches": _keyword_matches(ig),
        "embedding_score": None,  # no embeddings in this pipeline
        "rule_matches": list(ig.get("reasoning", {}).get("signals") or []),
        "conflict_resolution": {
            "ambiguity": ig.get("reasoning", {}).get("ambiguity"),
            "requires_clarification": ig.get("requires_clarification"),
        },
    }


def _keyword_matches(ig):
    hits = []
    for intent in ([ig.get("primary_intent")] +
                   list(ig.get("secondary_intents") or []) +
                   list(ig.get("background_intents") or [])):
        for ev in intent.get("evidence") or []:
            if isinstance(ev, str):
                hits.append(ev)
    return hits[:20]


def _question_selection(decision):
    meta = decision.get("metadata") or {}
    action = decision.get("action")
    priority = meta.get("question_priority")
    strategy = priority or _action_to_strategy(action)
    return {
        "question_strategy": strategy,
        "open_question": action in ("ask_question", "explore_topic")
                         and meta.get("button_mode") != "choice",
        "clarification": action == "clarify",
        "reflection": action == "reflect",
        "recommendation": action == "provide_recommendation",
        "commitment": action in ("create_commitment", "schedule_action"),
        "why_this_strategy_won": decision.get("reason"),
        "rejected_strategies": _rejected_strategies(strategy, action),
        "button_mode": meta.get("button_mode"),
        "ladder_stage": priority,
    }


def _action_to_strategy(action):
    return {
        "ask_question": "open",
        "explore_topic": "open",
        "clarify": "clarifying",
        "provide_insight": "reflective",
        "provide_recommendation": "action",
        "create_commitment": "commitment",
        "schedule_action": "commitment",
    }.get(action, "n/a")


def _rejected_strategies(strategy, action):
    ladder = ("reflective", "clarifying", "narrowing", "action", "commitment")
    if strategy in ladder and action in ("ask_question", "explore_topic", "clarify"):
        idx = ladder.index(strategy)
        return ["stage '%s' not reached yet" % s for s in ladder[idx + 1:]]
    if action == "reflect":
        return ["commitment not yet appropriate: reflection comes first"]
    return ["not this decision: action is '%s'" % action]


def _branch_evaluation(ctx, ig, snapshot):
    pillar = ctx.get("current_pillar")
    branch = branch_policy.branch_for_pillar(pillar)
    message = (ctx.get("message") or "").strip().lower()
    topic_hits = []
    for intent in ([ig.get("primary_intent")] + list(ig.get("secondary_intents") or [])):
        notes = intent.get("notes") or ""
        if notes.startswith("topic="):
            topic_hits.append(notes[6:])
    candidates = []
    for branch_name in branch_policy.BRANCH_DEFINITIONS:
        patterns = branch_policy._BRANCH_SLOT_PATTERNS.get(branch_name, {})
        score = 0
        for pattern in patterns.values():
            if pattern.search(message):
                score += 1
        for topic in topic_hits:
            mapped = branch_policy.PILLAR_BRANCH.get(topic)
            if mapped == branch_name:
                score += 1
        if score > 0:
            candidates.append({"branch": branch_name,
                               "confidence": round(min(1.0, 0.3 + 0.15 * score), 3)})
    candidates.sort(key=lambda c: -c["confidence"])
    return {
        "active_branch": branch,
        "active_pillar": pillar,
        "candidate_branches": candidates,
        "rejected_branches": [c["branch"] for c in candidates if c["branch"] != branch],
        "branch_confidence": max([c["confidence"] for c in candidates], default=0.0),
        "why_selected": ("pillar %r maps to branch %r" % (pillar, branch))
                        if branch else "no pillar active",
        "required_slots": list(branch_policy.BRANCH_DEFINITIONS[branch]["required_slots"])
                          if branch else [],
        "optional_slots": list(branch_policy.BRANCH_DEFINITIONS[branch]["optional_slots"])
                          if branch else [],
        "completion": _branch_summary(snapshot),
    }


def _state_machine_section(records, result_state):
    current = (result_state or {}).get("current_state")
    relevant = [r for r in records if r.get("type") in
                ("transition", "set_state", "select_pillar")]
    if not relevant:
        return {"state_before": None, "state_after": current,
                "transition_rule": None, "why_transition": None,
                "fallback": None, "fallback_reason": None, "records": []}
    rec = relevant[-1]
    return {
        "state_before": rec.get("before"),
        "transition_rule": rec.get("rule"),
        "state_after": rec.get("after"),
        "why_transition": rec.get("why"),
        "fallback": rec.get("fallback"),
        "fallback_reason": rec.get("fallback_reason"),
        "forced": rec.get("forced"),
        "records": [
            {"type": r.get("type"), "before": r.get("before"), "after": r.get("after"),
             "rule": r.get("rule"), "why": r.get("why")}
            for r in records
        ],
    }


def _quick_reply_section(snapshot, ctx, decision):
    meta = decision.get("metadata") or {}
    shown = bool(decision.get("showQuickReplies"))
    checks = []
    mode = snapshot.mode_value()
    if mode in {m.value for m in _QUICK_REPLY_SUPPRESSED_MODES}:
        checks.append("suppressed: mode '%s' is directive" % mode)
    if snapshot.pending_recommendation:
        checks.append("suppressed: recommendation pending")
    if ctx.get("current_pillar"):
        checks.append("suppressed: topic established (%s)" % ctx.get("current_pillar"))
    if ctx.get("has_topic_signal"):
        checks.append("suppressed: message itself started a topic")
    if _is_rich(ctx.get("message")):
        checks.append("suppressed: free text beats buttons")
    if meta.get("quick_tree") or meta.get("force_choice"):
        checks.append("suppressed: uncertainty recovery tree active")
    state = ctx.get("state") or ""
    if state in _QUICK_REPLY_OPEN_STATES or bool(meta.get("greeting")):
        checks.append("shown: open prompt (state=%s)" % state)
    ig = ctx.get("intent_graph") or {}
    confidence = (ig.get("confidence_scores") or {}).get("overall_confidence")
    if confidence is None:
        confidence = ig.get("overall_confidence")
    if isinstance(confidence, (int, float)) and confidence < 0.60:
        checks.append("shown: low intent confidence (%.2f)" % confidence)
    if _UNCERTAINTY_RE.search(ctx.get("message") or ""):
        checks.append("shown: uncertainty phrase")
    if not checks:
        checks.append("not an asking decision")
    return {
        "should_show_buttons": shown,
        "reason": "shown (conversation entry)" if shown
                  else "hidden — " + "; ".join(checks),
        "buttons_generated": list(decision.get("quickReplies") or []),
        "quick_reply_type": decision.get("quickReplyType") or "",
        "buttons_hidden": not shown,
        "why": "; ".join(checks),
    }


def _llm_prompt_section(decision, reasoning_ctx, system_context, result):
    rctx = reasoning_ctx or {}
    return {
        "planner_objective": decision.get("reason"),
        "conversation_objective": rctx.get("conversation_objective"),
        "conversation_mode": rctx.get("conversation_mode"),
        "objective_reason": rctx.get("objective_reason"),
        "response_strategy": {"action": decision.get("action"),
                              "style": rctx.get("response_style"),
                              "mode": decision.get("mode")},
        "system_prompt_summary": {
            "source": "PRODUCT_CONTEXT",
            "chars": len(system_context or ""),
            "excerpt": ((system_context or "")[:200].replace("\n", " ").strip() + "…")
                       if system_context else "",
        },
        "llm_used_for_response": bool(result.get("llm_used")),
    }


def _final_response_section(turn_result, response_time_ms):
    return {
        "generated_response": turn_result.get("response"),
        "rendered_response": turn_result.get("response"),
        "options": turn_result.get("options"),
        "tokens": None,  # token counts are not reported by the LLM provider
        "latency_ms": round(response_time_ms, 1),
        "llm_used": turn_result.get("llm_used"),
        "show_quick_replies": turn_result.get("show_quick_replies", False),
        "quick_replies": list(turn_result.get("quick_replies") or []),
    }


def _planner_section(snapshot, decision, replay):
    return {
        "current_mode": decision.get("mode"),
        "mode_before": snapshot.mode_value(),
        "previous_mode": snapshot.previous_mode_value(),
        "planner_action": decision.get("action"),
        "planner_reason": decision.get("reason"),
        "planner_confidence": decision.get("confidence"),
        "decision_tree": replay["tree"],
        "replay_winner": replay["winner"],
        "replay_matches": replay.get("replay_matches"),
        "metadata": decision.get("metadata") or {},
    }


def _runtime_context_section(result):
    return {
        "state": (result.get("state") or {}).get("current_state")
                 if isinstance(result.get("state"), dict) else result.get("state"),
        "objective": (result.get("objective") or {}).get("objective")
                     if isinstance(result.get("objective"), dict)
                     else result.get("objective"),
        "route": result.get("route") or [],
        "emotion": {k: result.get("emotion", {}).get(k)
                    for k in ("primary_emotion", "emotional_intensity", "avoidance",
                              "engagement", "frustration", "risk_flag")},
        "risk_detected": result.get("risk_detected"),
        "reasoning_context": {
            "conversation_objective": (result.get("reasoning_context") or {})
                                      .get("conversation_objective"),
            "conversation_mode": (result.get("reasoning_context") or {})
                                 .get("conversation_mode"),
            "response_style": (result.get("reasoning_context") or {})
                              .get("response_style"),
            "behavior_traits": (result.get("reasoning_context") or {})
                               .get("behavior_traits", []),
        },
    }


def _has_emotion_keyword(message):
    words = ("sad", "lonely", "down", "tired", "anxious", "stressed",
             "overwhelm", "burnout")
    lower = (message or "").lower()
    return any(w in lower for w in words)


def _has_topic_signal(message):
    words = ("work", "sleep", "stress", "anxiety", "mood", "sad", "lonely",
             "tired", "family", "friend", "relationship", "exercise", "health",
             "eat", "food", "routine", "focus", "energy", "money", "finances",
             "motivation", "procrastination", "depressed", "overwhelm", "burnout")
    lower = (message or "").lower()
    return any(t in lower for t in words)


# ─── violations ────────────────────────────────────────────────────────

_VIOLATION_LABELS = {
    "repeated_question": "Repeated Question",
    "repeated_buttons": "Repeated Buttons",
    "unexpected_topic_switch": "Unexpected Topic Switch",
    "planner_loop": "Planner Loop",
    "discovery_restart": "Discovery Restart",
    "casual_chat_exit": "Casual Chat Exit",
    "recommendation_missing": "Recommendation Missing",
    "commitment_missing": "Commitment Missing",
    "insight_missing": "Insight Missing",
    "wrong_mode_transition": "Wrong Mode Transition",
    "branch_abandoned": "Branch Abandoned",
    "branch_completion_ignored": "Branch Completion Ignored",
    "free_text_ignored": "Free Text Ignored",
    "button_overused": "Button Overused",
    "question_economy_violated": "Question Economy Violated",
}


def _summary_of_turn(turn):
    ui = turn.get("user_input") or {}
    intent = turn.get("intent_resolver") or {}
    branch_eval = turn.get("branch_evaluation") or {}
    planner = turn.get("planner") or {}
    sm = turn.get("state_machine") or {}
    qr = turn.get("quick_replies") or {}
    fr = turn.get("final_response") or {}
    completion = branch_eval.get("completion") or {}
    message = ui.get("raw_message")
    return {
        "message": message,
        "state": sm.get("state_after"),
        "action": planner.get("planner_action"),
        "mode": planner.get("current_mode"),
        "question": turn.get("question_text"),
        "options": list(fr.get("options") or []),
        "quick_replies": list(qr.get("buttons_generated") or []),
        "rich_input": _is_rich(message),
        "casual_signal": bool(_CASUAL_RE.search(message or "")),
        "switch_signal": bool(_SWITCH_RE.search(message or "")),
        "ig": intent.get("intent_graph") or {},
        "pillar": branch_eval.get("active_pillar"),
        "branch_completion": bool(completion.get("completed")),
        "branch": completion.get("branch"),
        "filled": list(completion.get("required_filled") or []),
    }


def _completion_ignored_within(summaries, idx, filled_cache):
    """Cumulative branch-fill check used by the completion-ignored detector."""
    branch = branch_policy.branch_for_pillar(summaries[idx].get("pillar"))
    if not branch:
        return False
    definition = branch_policy.BRANCH_DEFINITIONS[branch]
    required = set(definition["required_slots"])
    if filled_cache.get("branch") != branch:
        filled_cache.update(branch=branch, filled=set())
    for i in range(filled_cache.get("from", 0), idx + 1):
        s = summaries[i]
        if branch_policy.branch_for_pillar(s.get("pillar")) == branch:
            fills = branch_policy.detect_slot_fills(
                s.get("message") or "", s.get("pillar"), s.get("ig") or {})
            filled_cache["filled"].update(fills)
            filled_cache["from"] = i + 1
    required_filled = len(filled_cache["filled"] & required)
    return required_filled >= definition["completion_threshold"]


def _detect_turn_violations(idx, summaries):
    found = []
    turn = summaries[idx]
    action = turn["action"]

    def add(code, reason):
        found.append({"code": code, "label": _VIOLATION_LABELS[code], "reason": reason})

    if turn["question"]:
        q_norm = _normalize(turn["question"])
        for prev in summaries[:idx]:
            if prev["question"] and _normalize(prev["question"]) == q_norm:
                add("repeated_question", "question '%s' was already asked"
                    % turn["question"])
                break

    if turn["options"]:
        prev = summaries[idx - 1] if idx > 0 else None
        if prev and prev["options"] == turn["options"]:
            add("repeated_buttons", "identical options shown two turns in a row")

    if action == "switch_topic":
        ig = turn["ig"]
        if not (ig.get("topic_shift") or ig.get("branch_change_requested")
                or turn["switch_signal"]):
            add("unexpected_topic_switch",
                "switch_topic fired without an explicit switch request")

    if idx >= 2:
        if all(summaries[i]["action"] == action
               and summaries[i]["state"] == turn["state"]
               for i in (idx - 2, idx - 1, idx)):
            add("planner_loop", "action '%s' repeated 3x in state '%s'"
                % (action, turn["state"]))

    if action == "ask_question" and turn["state"] in ("guided_discovery", "pillar_selection"):
        for prev in reversed(summaries[:idx]):
            if prev["mode"] and prev["mode"] not in (None, "discovery"):
                add("discovery_restart",
                    "discovery question after the planner had left DISCOVERY")
                break

    if action == "casual_chat" and not turn["casual_signal"]:
        prev_mode = summaries[idx - 1]["mode"] if idx > 0 else None
        if prev_mode != "casual_chat":
            add("casual_chat_exit",
                "casual_chat action without a casual request in the message")

    if idx > 0:
        prev_mode = summaries[idx - 1]["mode"]
        cur_mode = turn["mode"]
        if prev_mode and cur_mode and cur_mode != prev_mode:
            try:
                prev_enum = ConversationMode(prev_mode)
                cur_enum = ConversationMode(cur_mode)
            except ValueError:
                prev_enum = cur_enum = None
            if prev_enum and cur_enum \
                    and cur_enum not in _VALID_TRANSITIONS.get(prev_enum, set()) \
                    and cur_enum not in _TEMPORARY_MODES \
                    and cur_enum != ConversationMode.ESCALATION:
                add("wrong_mode_transition",
                    "mode %s -> %s is not in _VALID_TRANSITIONS"
                    % (prev_mode, cur_mode))

    if idx > 0:
        prev_pillar = summaries[idx - 1]["pillar"]
        cur_pillar = turn["pillar"]
        if prev_pillar and cur_pillar and cur_pillar != prev_pillar \
                and not (turn["switch_signal"] or action == "switch_topic"
                         or action == "close_conversation"):
            add("branch_abandoned",
                "active branch moved %s -> %s without a switch request"
                % (prev_pillar, cur_pillar))

    if action in ("ask_question", "explore_topic", "clarify", "wait"):
        ig = turn["ig"]
        fills = branch_policy.detect_slot_fills(
            turn["message"] or "", turn["pillar"] or "", ig)
        if fills and not turn["branch_completion"]:
            filled_cache = _detect_ignored_cache.setdefault(summaries, {})
            branch = branch_policy.branch_for_pillar(turn["pillar"])
            if branch:
                definition = branch_policy.BRANCH_DEFINITIONS[branch]
                res = {**filled_cache}
                prev_filled = res.setdefault("filled", set())
                running = {f for f in prev_filled}
                running |= fills
                prev_filled |= fills
                if len(running & set(definition["required_slots"])) \
                        >= definition["completion_threshold"]:
                    add("branch_completion_ignored",
                        "branch threshold met but action stayed '%s'" % action)

    if turn["rich_input"] and action in ("ask_question", "clarify"):
        if turn["options"] and len(turn["options"]) > 2:
            add("free_text_ignored",
                "rich free text answered with %d buttons" % len(turn["options"]))

    if idx > 0 and (turn["options"] or turn["quick_replies"]):
        prev = summaries[idx - 1]
        if prev["options"] or prev["quick_replies"]:
            add("button_overused", "buttons shown on two consecutive turns")

    if idx >= 2:
        window = [summaries[i] for i in range(idx - 2, idx + 1)]
        if all(s["action"] in _ASKING_ACTIONS for s in window):
            progress = any(bool(s["ig"].get("answered_current_question"))
                           or bool(s["ig"].get("new_slots_detected"))
                           for s in window)
            if not progress:
                add("question_economy_violated",
                    "3 consecutive questions with zero slot/answer progress")
    return found


# per-conversation booking used to keep the ignored-completion check cheap
_detect_ignored = threading.local()
if not hasattr(_detect_ignored, "filled"):
    _detect_ignored.filled = {}


def _forward_scan_violations(summaries):
    found = []
    for idx, turn in enumerate(summaries):
        if turn["branch_completion"]:
            horizon = summaries[idx + 1: idx + 4]
            if not any(s["action"] == "provide_recommendation" for s in horizon):
                found.append({
                    "code": "recommendation_missing",
                    "label": _VIOLATION_LABELS["recommendation_missing"],
                    "reason": "branch completed at turn %d but no recommendation followed"
                              % (idx + 1),
                })
            break
    for idx, turn in enumerate(summaries):
        if turn["action"] == "provide_recommendation":
            horizon = summaries[idx + 1: idx + 3]
            if horizon and any(_ACCEPT_RE.match((s["message"] or "").strip().lower())
                               for s in horizon) \
                    and not any(s["action"] in ("create_commitment", "schedule_action")
                                for s in horizon):
                found.append({
                    "code": "commitment_missing",
                    "label": _VIOLATION_LABELS["commitment_missing"],
                    "reason": "recommendation accepted but no commitment action followed",
                })
            break
    return found


# ─── per-turn scores ───────────────────────────────────────────────────

def _score_turn(idx, turn, summaries, vcodes):
    decision = turn.get("planner") or {}
    ig = (turn.get("intent_resolver") or {}).get("intent_graph") or {}

    intent = 0.0
    conf = (turn.get("intent_resolver") or {}).get("confidence") or {}
    if not isinstance(conf, dict):
        conf = {}
    conf = conf.get("overall")
    if isinstance(conf, (int, float)):
        intent = max(0.0, min(1.0, conf))
    if ig.get("requires_clarification"):
        intent = max(0.0, intent - 0.15)

    planner = max(0.0, min(1.0, decision.get("planner_confidence") or 0.0))
    if not decision.get("replay_matches", True):
        planner = max(0.0, planner - 0.3)

    question = 1.0
    action = decision.get("planner_action")
    if action in _ASKING_ACTIONS:
        if "repeated_question" in vcodes:
            question = 0.0
        if "question_economy_violated" in vcodes:
            question = max(0.0, question - 0.5)
        if "free_text_ignored" in vcodes:
            question = max(0.0, question - 0.4)
    else:
        question = 0.9 if action not in ("wait",) else 0.6

    branch = 0.0
    completion = (turn.get("branch_evaluation") or {}).get("completion")
    if completion and completion.get("completed"):
        branch = 1.0
    elif completion and completion.get("required_slots"):
        req = len(completion.get("required_slots") or [])
        filled = len(completion.get("required_filled") or [])
        branch = max(0.0, min(1.0, filled / max(1, req)))
    if "branch_completion_ignored" in vcodes:
        branch = max(0.0, branch - 0.5)
    if "branch_abandoned" in vcodes:
        branch = max(0.0, branch - 0.4)

    state = 1.0
    if "wrong_mode_transition" in vcodes:
        state = 0.2
    if "discovery_restart" in vcodes:
        state = max(0.0, state - 0.4)

    flow = max(0.0, 1.0 - 0.2 * len(vcodes))

    naturalness = 1.0
    if "button_overused" in vcodes:
        naturalness -= 0.4
    if "free_text_ignored" in vcodes:
        naturalness = max(0.0, naturalness - 0.2)

    overall = round(0.15 * intent + 0.15 * planner + 0.20 * question
                    + 0.15 * branch + 0.15 * state + 0.10 * flow
                    + 0.10 * naturalness, 3)
    return {
        "intent": round(intent, 3),
        "planner": round(planner, 3),
        "question_quality": round(question, 3),
        "branch_completion": round(branch, 3),
        "state_transition": round(state, 3),
        "conversation_flow": round(flow, 3),
        "naturalness": round(naturalness, 3),
        "overall": overall,
    }


def _average(scores):
    if not scores:
        return {}
    keys = ("intent", "planner", "question_quality", "branch_completion",
            "state_transition", "conversation_flow", "naturalness", "overall")
    return {k: round(sum(s.get(k, 0.0) for s in scores) / len(scores), 3)
            for k in keys}


# ─── state machine instrumentation (wrappers; behavior unchanged) ──────

_ACTIVE = threading.local()


def _emit(kind, **kw):
    records = getattr(_ACTIVE, "records", None)
    if records is not None:
        records.append({"type": kind, **kw})


def _wrap_transition(orch, original):
    def wrapped(emotion_result=None, user_message=""):
        before = orch.state_machine.current_state
        result = original(emotion_result, user_message)
        after = orch.state_machine.current_state
        _emit("transition", before=before, after=after,
              rule=_transition_rule(before, after, emotion_result, user_message),
              why="state machine moved %s -> %s (emotion=%s)" % (
                  before, after,
                  ((emotion_result or {}).get("primary_emotion"))),
              fallback=(before == after),
              fallback_reason="no transition matched" if before == after else None,
              forced=False)
        return result
    return wrapped


def _wrap_set_state(orch, original):
    def wrapped(state):
        before = orch.state_machine.current_state
        result = original(state)
        after = orch.state_machine.current_state
        _emit("set_state", before=before, after=after,
              rule="forced set_state(%s)" % state,
              why="explicit state override (branch completion / loop break)",
              fallback=False, forced=True)
        return result
    return wrapped


def _wrap_select_pillar(orch, original):
    def wrapped(pillar):
        result = original(pillar)
        _emit("select_pillar", before=orch.state_machine.current_state,
              after=orch.state_machine.current_state,
              rule="select_pillar(%s)" % pillar,
              why="pillar %s selected" % pillar,
              fallback=False, forced=False)
        return result
    return wrapped


_TRANSITION_RULES = {
    ("greeting", "guided_discovery"): "topic signal at greeting",
    ("greeting", "free_conversation"): "long reply / greeting turn limit",
    ("free_conversation", "guided_discovery"): "topic signal or intensity > 50",
    ("free_conversation", "avoidance_detection"): "avoidance > 50",
    ("rapport_building", "free_conversation"): "trust >= 50 / engagement > 65 / 4 turns",
    ("avoidance_detection", "soft_exploration"): "avoidance_count >= 2",
    ("avoidance_detection", "free_conversation"): "3 turns without avoidance",
    ("avoidance_detection", "guided_discovery"): "anger/frustration (user engaged)",
    ("soft_exploration", "guided_discovery"): "engagement > 50",
    ("soft_exploration", "free_conversation"): "3 turns without engagement",
    ("guided_discovery", "pillar_selection"): "pillar signal detected",
    ("guided_discovery", "deep_investigation"): "selected_pillar set",
    ("guided_discovery", "free_conversation"): "4 turns without a pillar signal",
    ("pillar_selection", "deep_investigation"): "selected_pillar set",
    ("pillar_selection", "guided_discovery"): "2 turns without selection",
    ("deep_investigation", "insight_generation"): "5 questions or explicit exit",
    ("insight_generation", "routine_planning"): "insight delivered",
    ("routine_planning", "reflection"): "routine created / 4 turns",
    ("reflection", "follow_up"): "2 turns in reflection",
    ("weekly_review", "free_conversation"): "weekly review complete",
    ("follow_up", "free_conversation"): "follow-up complete",
}


def _transition_rule(before, after, emotion, message):
    if before == after:
        return "none (state kept)"
    return _TRANSITION_RULES.get((before, after),
                                 "transition %s -> %s" % (before, after))


# ─── tracer ────────────────────────────────────────────────────────────

class DebugTracer:
    """Per-orchestrator trace recorder.

    Wraps ``process_message`` (and the state-machine entry points) on ONE
    orchestrator instance; the executed code path is unchanged. Writes
    ``conversation_<id>.json`` and ``conversation_<id>.md`` after every
    turn so a crash never loses the trace. All reads are guarded so a
    diagnostic failure never breaks the conversation.
    """

    def __init__(self, orch, trace_dir=None):
        self.orch = orch
        self.conversation_id = re.sub(r"[^A-Za-z0-9_.\-]", "_",
                                      str(getattr(orch, "user_id", "default")))
        self.trace_dir = Path(trace_dir or os.environ.get(
            "WELLNESS_TRACE_DIR") or DEFAULT_TRACE_DIR)
        self.trace_dir.mkdir(parents=True, exist_ok=True)
        self.turns = []
        self.summaries = []
        self.started_at = now_iso()
        self._original = None
        self._original_wraps = []
        self._filled_by_branch = {}
        self._prev_question = None

    def install(self):
        orch = self.orch
        if getattr(orch, "_debug_tracer", None) is not None:
            return self
        self._original = orch.process_message
        orch._debug_tracer = self
        orch.process_message = self._wrapped_process

        self._install_state_wrap(orch.state_machine, "transition", _wrap_transition)
        self._install_state_wrap(orch.state_machine, "set_state", _wrap_set_state)
        self._install_state_wrap(orch.state_machine, "select_pillar", _wrap_select_pillar)
        return self

    def _install_state_wrap(self, obj, name, factory):
        original = getattr(obj, name)
        setattr(obj, name, factory(self.orch, original))
        self._original_wraps.append((obj, name, original))

    def uninstall(self):
        if self._original is not None:
            self.orch.process_message = self._original
            self._original = None
        for obj, name, original in self._original_wraps:
            setattr(obj, name, original)
        self._original_wraps = []
        if getattr(self.orch, "_debug_tracer", None) is self:
            del self.orch._debug_tracer

    def _wrapped_process(self, message, *args, **kwargs):
        snapshot = self._safe_snapshot()
        _ACTIVE.records = []
        t0 = time.perf_counter()
        try:
            result = self._original(message, *args, **kwargs)
        except Exception:
            _ACTIVE.records = None
            raise
        elapsed = (time.perf_counter() - t0) * 1000.0
        records = _ACTIVE.records or []
        _ACTIVE.records = None
        try:
            turn = self._build_turn(message, snapshot, result, records, elapsed)
            self.turns.append(turn)
            self.summaries.append(_summary_of_turn(turn))
            self._write_files()
        except Exception as exc:  # noqa: BLE001
            _log.warning("debug trace build failed: %s", exc)
        return result

    def _safe_snapshot(self):
        try:
            return _PlannerSnapshot(self.orch)
        except Exception as exc:  # noqa: BLE001
            _log.warning("debug tracer snapshot failed: %s", exc)
            return None

    def _question_text(self, decision, result):
        if decision.get("action") not in _ASKING_ACTIONS:
            return None
        question = (self.orch.last_question or {}).get("question_text")
        if not question or question == self._prev_question:
            response = (result.get("response") or "").strip()
            question = response if response.endswith("?") else None
        self._prev_question = question
        return question

    def _build_turn(self, message, snapshot, result, records, elapsed):
        if snapshot is None:
            snapshot = _PlannerSnapshot(self.orch) if self.orch.agents else None
        decision = result.get("planner_decision") or {}
        ig = result.get("intent_graph") or {}
        state_info = result.get("state") or {}
        ctx = _turn_context(message, ig, result, self.orch)
        replay = replay_decision_tree(snapshot, ctx, decision)
        branch_eval = _branch_evaluation(ctx, ig, snapshot)
        return {
            "turn_number": len(self.turns) + 1,
            "timestamp": now_iso(),
            "question_text": self._question_text(decision, result),
            "user_input": {
                "raw_message": message,
                "normalized_message": _normalize(message),
                "conversation_history": [
                    {"user": t.get("user"), "assistant": t.get("assistant"),
                     "state": t.get("state")}
                    for t in (self.orch.last_turns or [])[-10:]
                ],
                "runtime_context": _runtime_context_section(result),
                "previous_planner": {
                    "mode": snapshot.mode_value(),
                    "action": snapshot.last_action,
                    "active_branch": snapshot.pillar,
                    "slots": (branch_eval.get("completion") or {}).get("filled", []),
                    "completion": (branch_eval.get("completion") or {})
                                  .get("completion_score"),
                },
            },
            "intent_resolver": _intent_section(ig),
            "branch_evaluation": branch_eval,
            "question_selection": _question_selection(decision),
            "planner": _planner_section(snapshot, decision, replay),
            "state_machine": _state_machine_section(records, state_info),
            "branch_completion": branch_eval.get("completion") or {},
            "quick_replies": _quick_reply_section(snapshot, ctx, decision),
            "llm_prompt": _llm_prompt_section(
                decision, result.get("reasoning_context"), self.orch.context, result),
            "final_response": _final_response_section(result, elapsed),
        }

    def _write_files(self):
        doc = self._document()
        json_path = self.trace_dir / ("conversation_%s.json" % self.conversation_id)
        md_path = self.trace_dir / ("conversation_%s.md" % self.conversation_id)
        try:
            json_path.write_text(_dumps(mask_secrets(doc)), encoding="utf-8")
        except OSError as exc:
            _log.warning("debug trace JSON write failed: %s", exc)
        try:
            md_path.write_text(_render_markdown(doc), encoding="utf-8")
        except OSError as exc:
            _log.warning("debug trace MD write failed: %s", exc)

    def _document(self):
        violations = []
        self._filled_by_branch = {}
        for idx in range(len(self.summaries)):
            for v in self._detect_turn_violations(idx):
                violations.append({**v, "turn": idx + 1})
        violations += _forward_scan_violations(self.summaries)
        scores = []
        for idx, turn in enumerate(self.turns):
            vcodes = [v["code"] for v in violations if v.get("turn") == idx + 1]
            scores.append(_score_turn(idx, turn, self.summaries, vcodes))
        return {
            "metadata": {
                "tool": "planner-debug-trace",
                "trace_version": _TRACER_VERSION,
                "conversation_id": self.conversation_id,
                "user_id": self.conversation_id,
                "started_at": self.started_at,
                "ended_at": now_iso(),
                "total_turns": len(self.turns),
                "git_commit": _git_commit(),
            },
            "decision_graph": [self._graph_node(t) for t in self.turns],
            "violations": violations,
            "planner_scores": scores,
            "average_scores": _average(scores),
            "turns": self.turns,
        }

    def _detect_turn_violations(self, idx):
        turn = self.turns[idx]
        summary = self.summaries[idx]
        found = []
        action = summary["action"]

        def add(code, reason):
            found.append({"code": code, "label": _VIOLATION_LABELS[code],
                          "reason": reason, "turn": idx + 1})

        if summary["question"]:
            q_norm = _normalize(summary["question"])
            for prev in self.summaries[:idx]:
                if prev["question"] and _normalize(prev["question"]) == q_norm:
                    add("repeated_question", "question '%s' was already asked"
                        % summary["question"])
                    break

        if summary["options"]:
            prev = self.summaries[idx - 1] if idx > 0 else None
            if prev and prev["options"] == summary["options"]:
                add("repeated_buttons", "identical options two turns in a row")

        if action == "switch_topic":
            ig = summary["ig"]
            if not (ig.get("topic_shift") or ig.get("branch_change_requested")
                    or summary["switch_signal"]):
                add("unexpected_topic_switch",
                    "switch_topic without an explicit switch request")

        if idx >= 2:
            if all(self.summaries[i]["action"] == action
                   and self.summaries[i]["state"] == summary["state"]
                   for i in (idx - 2, idx - 1, idx)):
                add("planner_loop", "action '%s' repeated 3x in state '%s'"
                    % (action, summary["state"]))

        if action == "ask_question" and summary["state"] in ("guided_discovery", "pillar_selection"):
            for prev in reversed(self.summaries[:idx]):
                if prev["mode"] and prev["mode"] not in (None, "discovery"):
                    add("discovery_restart",
                        "discovery question after planner had left DISCOVERY")
                    break

        if action == "casual_chat" and not summary["casual_signal"]:
            prev_mode = self.summaries[idx - 1]["mode"] if idx > 0 else None
            if prev_mode != "casual_chat":
                add("casual_chat_exit", "casual_chat without a casual request")

        if idx > 0:
            prev_mode = self.summaries[idx - 1]["mode"]
            cur_mode = summary["mode"]
            if prev_mode and cur_mode and cur_mode != prev_mode:
                try:
                    prev_enum = ConversationMode(prev_mode)
                    cur_enum = ConversationMode(cur_mode)
                except ValueError:
                    prev_enum = cur_enum = None
                if prev_enum and cur_enum \
                        and cur_enum not in _VALID_TRANSITIONS.get(prev_enum, set()) \
                        and cur_enum not in _TEMPORARY_MODES \
                        and cur_enum != ConversationMode.ESCALATION:
                    add("wrong_mode_transition", "mode %s -> %s invalid"
                        % (prev_mode, cur_mode))

        if idx > 0:
            prev_pillar = self.summaries[idx - 1]["pillar"]
            cur_pillar = summary["pillar"]
            if prev_pillar and cur_pillar and cur_pillar != prev_pillar \
                    and not (summary["switch_signal"] or action == "switch_topic"
                             or action == "close_conversation"):
                add("branch_abandoned", "branch moved %s -> %s without a switch"
                    % (prev_pillar, cur_pillar))

        if action in _ASKING_ACTIONS or action in ("wait",):
            fills = branch_policy.detect_slot_fills(
                summary["message"] or "", summary["pillar"] or "", summary["ig"] or {})
            if fills and not summary["branch_completion"]:
                branch = branch_policy.branch_for_pillar(summary["pillar"])
                if branch:
                    definition = branch_policy.BRANCH_DEFINITIONS[branch]
                    required = set(definition["required_slots"])
                    key = (summary["pillar"], branch)
                    combined = self._filled_by_branch.get(key, set()) | fills
                    self._filled_by_branch[key] = combined
                    if len(combined & required) >= definition["completion_threshold"]:
                        add("branch_completion_ignored",
                            "branch threshold met but action stayed '%s'" % action)

        if summary["rich_input"] and action in ("ask_question", "clarify"):
            if summary["options"] and len(summary["options"]) > 2:
                add("free_text_ignored",
                    "rich free text answered with %d buttons" % len(summary["options"]))

        if idx > 0 and (summary["options"] or summary["quick_replies"]):
            prev = self.summaries[idx - 1]
            if prev["options"] or prev["quick_replies"]:
                add("button_overused", "buttons shown on two consecutive turns")

        if idx >= 2:
            window = self.summaries[idx - 2: idx + 1]
            if all(s["action"] in _ASKING_ACTIONS for s in window):
                progress = any(bool(s["ig"].get("answered_current_question"))
                               or bool(s["ig"].get("new_slots_detected"))
                               for s in window)
                if not progress:
                    add("question_economy_violated",
                        "3 consecutive questions with zero slot/answer progress")
        return found

    @staticmethod
    def _graph_node(turn):
        completion = turn.get("branch_completion") or {}
        return {
            "turn": turn.get("turn_number"),
            "state": (turn.get("state_machine") or {}).get("state_after"),
            "pillar": (turn.get("branch_evaluation") or {}).get("active_pillar"),
            "branch": (turn.get("branch_evaluation") or {}).get("active_branch"),
            "completion": completion.get("completion_score"),
            "action": (turn.get("planner") or {}).get("planner_action"),
            "mode": (turn.get("planner") or {}).get("current_mode"),
        }


def _turn_context(message, ig, result, orch):
    state_info = result.get("state") or {}
    return {
        "message": message,
        "intent_graph": result.get("intent_graph") or {},
        "emotion": result.get("emotion") or {},
        "state": state_info.get("current_state")
                 if isinstance(state_info, dict) else state_info,
        "state_info": state_info,
        "route": result.get("route") or [],
        "current_pillar": orch.current_pillar,
        "objective": (orch.current_objective or {}).get("objective"),
        "avoidance_count": orch.avoidance_count,
        "exit_offered": orch._exit_offered,
        "exit_consumed": orch._exit_consumed,
        "minimal_input": not (message or "").strip()
                         or len((message or "").strip().split()) < 3,
        "has_emotion_keyword": _has_emotion_keyword(message),
        "has_topic_signal": _has_topic_signal(message),
    }


# ─── markdown report ───────────────────────────────────────────────────

_SEP = "---------------------------------------"


def _render_markdown(doc):
    lines = []
    meta = doc["metadata"]
    lines += [
        "# Planner Debug Trace — %s" % meta["conversation_id"],
        "",
        "- tool: %s (v%s)" % (meta["tool"], meta["trace_version"]),
        "- started: %s" % meta["started_at"],
        "- ended: %s" % meta["ended_at"],
        "- turns: %d" % meta["total_turns"],
        "- git: %s" % meta["git_commit"],
        "",
    ]
    for turn in doc["turns"]:
        lines += _render_turn_markdown(turn)
    lines += _render_graph_markdown(doc["decision_graph"])
    lines += _render_violations_markdown(doc["violations"])
    lines += _render_scores_markdown(doc["planner_scores"], doc["average_scores"])
    return "\n".join(lines) + "\n"


def _md_small(value):
    text = json.dumps(value, default=_json_default, ensure_ascii=False)
    if len(text) > 220:
        text = text[:220] + "…"
    return text


def _render_turn_markdown(turn):
    lines = []
    n = turn["turn_number"]
    lines += [
        "## TURN %d" % n, "", _SEP,
        "### User Input", "",
        "**Raw Message:**", turn["user_input"]["raw_message"] or "(empty)", "",
        "**Normalized Message:**", turn["user_input"]["normalized_message"] or "(empty)", "",
        "**Conversation History:**",
    ]
    history = turn["user_input"]["conversation_history"]
    if history:
        for t in history:
            lines.append("- user: %r → %r [%s]" % (
                (t.get("user") or "")[:70], (t.get("assistant") or "")[:70],
                t.get("state")))
    else:
        lines.append("(none)")
    rctx = turn["user_input"]["runtime_context"]
    lines += [
        "", "**Current RuntimeContext:**",
        "- state: %s" % rctx.get("state"),
        "- objective: %s" % rctx.get("objective"),
        "- route: %s" % ", ".join(rctx.get("route") or []) or "(none)",
        "- emotion: %s" % rctx.get("emotion"),
        "- reasoning: objective=%s mode=%s style=%s" % (
            rctx.get("reasoning_context", {}).get("conversation_objective"),
            rctx.get("reasoning_context", {}).get("conversation_mode"),
            rctx.get("reasoning_context", {}).get("response_style")),
        "",
        "**Previous Planner:**",
        "- mode: %s" % turn["user_input"]["previous_planner"]["mode"],
        "- action: %s" % turn["user_input"]["previous_planner"]["action"],
        "- active branch: %s" % turn["user_input"]["previous_planner"]["active_branch"],
        "- slots: %s" % (turn["user_input"]["previous_planner"]["slots"] or "(none)"),
        "- completion: %s%%" % turn["user_input"]["previous_planner"]["completion"],
        "", _SEP, "### Intent Resolver", "",
    ]
    intent = turn["intent_resolver"]
    lines += [
        "- primary: %s" % intent["primary_intent"],
        "- secondary: %s" % ("; ".join(intent["secondary_intents"]) or "(none)"),
        "- confidence: overall=%s primary=%s" % (
            intent["confidence"].get("overall"), intent["confidence"].get("primary")),
        "- why won: %s" % _md_small(intent["why_this_intent_won"]),
        "- why lost: %s" % _md_small(intent["why_others_lost"]),
        "- keyword/rule matches: %s" % (
            ", ".join(intent["keyword_matches"]) or "(none)"),
        "- embedding score: n/a (no embeddings)",
        "- conflict resolution: %s" % intent["conflict_resolution"],
        "", _SEP, "### Branch Evaluation", "",
    ]
    be = turn["branch_evaluation"]
    lines += [
        "- active branch: %s (pillar=%s)" % (be["active_branch"], be["active_pillar"]),
        "- candidates: %s" % be["candidate_branches"],
        "- confidence: %s" % be["branch_confidence"],
        "- why selected: %s" % be["why_selected"],
        "- why rejected: %s" % (", ".join(be["rejected_branches"]) or "(none)"),
        "- required slots: %s" % ("; ".join(be["required_slots"]) or "(none)"),
        "- completion: %s" % _md_small(be["completion"]),
        "", _SEP, "### Question Selection", "",
    ]
    qs = turn["question_selection"]
    lines += [
        "- strategy: %s" % qs["question_strategy"],
        "- open: %s | clarification: %s | reflection: %s | recommendation: %s | commitment: %s"
        % (qs["open_question"], qs["clarification"], qs["reflection"],
           qs["recommendation"], qs["commitment"]),
        "- why won: %s" % qs["why_this_strategy_won"],
        "- rejected: %s" % "; ".join(qs["rejected_strategies"]),
        "", _SEP, "### Planner", "",
    ]
    pl = turn["planner"]
    lines += [
        "- mode (before): %s → %s" % (pl["mode_before"], pl["current_mode"]),
        "- previous mode: %s" % pl["previous_mode"],
        "- action: %s" % pl["planner_action"],
        "- reason: %s" % pl["planner_reason"],
        "- confidence: %s" % pl["planner_confidence"],
        "- replay matches: %s" % pl.get("replay_matches"),
        "",
        "**Decision Tree (candidates in order):**",
    ]
    for entry in pl["decision_tree"]:
        lines.append("- step %d: %s — **%s**: %s" % (
            entry["step"], entry["candidate"], entry["status"], entry["why"]))
    sm = turn["state_machine"]
    lines += [
        "", _SEP, "### State Machine", "",
        "- state before: %s" % sm["state_before"],
        "- rule: %s" % sm["transition_rule"],
        "- state after: %s" % sm["state_after"],
        "- why: %s" % sm["why_transition"],
        "- fallback: %s (%s)" % (sm["fallback"], sm["fallback_reason"]),
        "- forced: %s" % ("yes" if sm.get("forced") else "no"),
        "", _SEP, "### Branch Completion", "",
    ]
    bc = turn["branch_completion"]
    if bc:
        lines += [
            "- completion score: %s%%" % bc.get("completion_score"),
            "- threshold: %d" % bc.get("threshold"),
            "- completed: %s" % bc.get("completed"),
            "- why: %d/%d required slots filled → %s" % (
                len(bc.get("required_filled") or []),
                len(bc.get("required_slots") or []),
                "terminal sequence" if bc.get("completed") else "keep collecting"),
            "- next candidate actions: %s" % (bc.get("next_actions") or "(none)"),
        ]
    else:
        lines.append("- (no branch active)")
    lines += [
        "", _SEP, "### Quick Replies", "",
        "- should show: %s" % turn["quick_replies"]["should_show_buttons"],
        "- reason: %s" % turn["quick_replies"]["reason"],
        "- buttons: %s" % (turn["quick_replies"]["buttons_generated"] or "(none)"),
        "- hidden: %s — %s" % (turn["quick_replies"]["buttons_hidden"],
                               turn["quick_replies"]["why"]),
        "", _SEP, "### LLM Prompt", "",
    ]
    llm = turn["llm_prompt"]
    lines += [
        "- planner objective: %s" % llm["planner_objective"],
        "- conversation objective: %s" % llm["conversation_objective"],
        "- system prompt: %s (%d chars) — %s" % (
            llm["system_prompt_summary"]["source"],
            llm["system_prompt_summary"]["chars"],
            llm["system_prompt_summary"]["excerpt"]),
        "- response strategy: %s" % _md_small(llm["response_strategy"]),
        "", _SEP, "### Final Response", "",
        "- generated: %s" % (turn["final_response"]["generated_response"] or "(empty)"),
        "- options: %s" % (turn["final_response"]["options"] or "(none)"),
        "- latency: %s ms | llm: %s | tokens: %s" % (
            turn["final_response"]["latency_ms"],
            turn["final_response"]["llm_used"],
            turn["final_response"]["tokens"]),
        "", "", "",
    ]
    return lines


def _render_graph_markdown(graph):
    lines = ["## Decision Graph", "", "```", "Greeting", "   ↓"]
    for node in graph:
        state = node.get("state") or "Unknown"
        lines.append("%s (turn %d: %s)" % (
            state.replace("_", " ").title(), node["turn"], node["action"]))
        lines.append("   ↓")
    lines += ["...", "```", ""]
    return lines


def _render_violations_markdown(violations):
    lines = ["## Violation Detection", ""]
    if not violations:
        lines.append("No violations detected.")
    for v in violations:
        lines.append("- **[%s]** (turn %d): %s" % (
            v.get("label", v.get("code")), v.get("turn", "?"), v["reason"]))
    lines.append("")
    return lines


def _render_scores_markdown(scores, averages):
    lines = ["## Planner Score", ""]
    lines.append("| Turn | Intent | Planner | Question | Branch | State | Flow | Natural | Overall |")
    lines.append("|------|--------|---------|----------|--------|-------|------|---------|---------|")
    for i, s in enumerate(scores):
        lines.append("| %d | %.2f | %.2f | %.2f | %.2f | %.2f | %.2f | %.2f | **%.2f** |" % (
            i + 1, s["intent"], s["planner"], s["question_quality"],
            s["branch_completion"], s["state_transition"], s["conversation_flow"],
            s["naturalness"], s["overall"]))
    if scores:
        lines.append("| **avg** | %.2f | %.2f | %.2f | %.2f | %.2f | %.2f | %.2f | **%.2f** |" % (
            averages.get("intent", 0), averages.get("planner", 0),
            averages.get("question_quality", 0), averages.get("branch_completion", 0),
            averages.get("state_transition", 0), averages.get("conversation_flow", 0),
            averages.get("naturalness", 0), averages.get("overall", 0)))
    lines.append("")
    return lines


# ─── public API ────────────────────────────────────────────────────────

def install_tracer(orchestrator, trace_dir=None):
    """Install the debug tracer on one orchestrator instance.

    Returns the DebugTracer; call ``uninstall()`` to restore the original
    methods. Writes one JSON + one Markdown report per conversation
    under ``data/debug_traces/``. If a tracer is already installed on the
    instance, the existing tracer is returned unchanged.
    """
    existing = getattr(orchestrator, "_debug_tracer", None)
    if existing is not None:
        return existing
    tracer = DebugTracer(orchestrator, trace_dir)
    tracer.install()
    return tracer


def uninstall_tracer(orchestrator):
    tracer = getattr(orchestrator, "_debug_tracer", None)
    if tracer is not None:
        tracer.uninstall()


__all__ = [
    "DebugTracer",
    "DEFAULT_TRACE_DIR",
    "DEBUG_TRACER_ENABLED",
    "install_tracer",
    "uninstall_tracer",
    "replay_decision_tree",
    "_render_markdown",
]