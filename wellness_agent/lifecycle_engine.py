"""Branch Lifecycle Engine — deterministic per-branch conversation stages.

Implements docs/specifications/BRANCH_LIFECYCLE_ENGINE.md exactly.

- every branch follows the universal lifecycle:
  START -> GREETING -> PROBLEM_IDENTIFICATION -> INVESTIGATION ->
  UNDERSTANDING -> INSIGHT -> RECOMMENDATION -> COMMITMENT -> FOLLOW_UP ->
  CLOSURE; stages are NEVER skipped unless explicitly allowed;
- the planner decides "what stage of the conversation am I in" BEFORE
  selecting actions (planner priority: branch -> stage -> completion ->
  next stage -> action);
- BranchState is an explicit state record with:
  active_branch, current_stage, preceding_stage, next_stage,
  completion_score, required_slots, optional_slots, last_transition, entered_at;
- investigation rules store required slots, optional slots, completion
  threshold per branch;
- remaining transitions are definite (no catching previous stages after
  completion when a new conversation stage begins).

The engine itself is pure and stateless — the ConversationPlanner keeps the
running state across messages and calls this module to determine the current
stage plus compute the completion score.

Args:
    branch_state: lifecycle state dict. ctx (Additional Context) the planner computes

The engine is deterministic — never calls an LLM.
"""

from enum import Enum
from . import branch_policy


class LifecycleStage(str, Enum):
    START = "start"
    GREETING = "greeting"
    PROBLEM_IDENTIFICATION = "problem_identification"
    INVESTIGATION = "investigation"
    UNDERSTANDING = "understanding"
    INSIGHT = "insight"
    RECOMMENDATION = "recommendation"
    COMMITMENT = "commitment"
    FOLLOW_UP = "follow_up"
    CLOSURE = "closure"


STAGE_SEQUENCE = [
    LifecycleStage.START,
    LifecycleStage.GREETING,
    LifecycleStage.PROBLEM_IDENTIFICATION,
    LifecycleStage.INVESTIGATION,
    LifecycleStage.UNDERSTANDING,
    LifecycleStage.INSIGHT,
    LifecycleStage.RECOMMENDATION,
    LifecycleStage.COMMITMENT,
    LifecycleStage.FOLLOW_UP,
    LifecycleStage.CLOSURE,
]

_STAGE_INDEX = {s: i for i, s in enumerate(STAGE_SEQUENCE)}

_FORBIDDEN_TRANSITIONS = {
    (LifecycleStage.INVESTIGATION, LifecycleStage.GREETING),
    (LifecycleStage.INSIGHT, LifecycleStage.START),
    (LifecycleStage.RECOMMENDATION, LifecycleStage.PROBLEM_IDENTIFICATION),
    (LifecycleStage.COMMITMENT, LifecycleStage.START),
    (LifecycleStage.FOLLOW_UP, LifecycleStage.PROBLEM_IDENTIFICATION),
}

_LIFECYCLE_TRANSITIONS = {
    LifecycleStage.START: LifecycleStage.GREETING,
    LifecycleStage.GREETING: LifecycleStage.PROBLEM_IDENTIFICATION,
    LifecycleStage.PROBLEM_IDENTIFICATION: LifecycleStage.INVESTIGATION,
    LifecycleStage.INVESTIGATION: LifecycleStage.UNDERSTANDING,
    LifecycleStage.UNDERSTANDING: LifecycleStage.INSIGHT,
    LifecycleStage.INSIGHT: LifecycleStage.RECOMMENDATION,
    LifecycleStage.RECOMMENDATION: LifecycleStage.COMMITMENT,
    LifecycleStage.COMMITMENT: LifecycleStage.FOLLOW_UP,
    LifecycleStage.FOLLOW_UP: LifecycleStage.CLOSURE,
    LifecycleStage.CLOSURE: None,
}


class BranchState:
    """Per-branch lifecycle state record."""

    __slots__ = (
        "active_branch",
        "current_stage",
        "preceding_stage",
        "next_stage",
        "completion_score",
        "required_slots",
        "optional_slots",
        "last_transition",
        "entered_at",
    )

    def __init__(self, active_branch=None, current_stage=None,
                 preceding_stage=None, next_stage=None,
                 completion_score=0.0, required_slots=None,
                 optional_slots=None, last_transition=None,
                 entered_at=None):
        self.active_branch = active_branch
        self.current_stage = current_stage
        self.preceding_stage = preceding_stage
        self.next_stage = next_stage
        self.completion_score = completion_score
        self.required_slots = required_slots or set()
        self.optional_slots = optional_slots or set()
        self.last_transition = last_transition
        self.entered_at = entered_at

    def to_dict(self):
        return {
            "active_branch": self.active_branch,
            "current_stage": self.current_stage.value
            if isinstance(self.current_stage, LifecycleStage) else self.current_stage,
            "preceding_stage": self.preceding_stage.value
            if isinstance(self.preceding_stage, LifecycleStage) else self.preceding_stage,
            "next_stage": self.next_stage.value
            if isinstance(self.next_stage, LifecycleStage) else self.next_stage,
            "completion_score": round(self.completion_score, 3),
            "required_slots": sorted(self.required_slots),
            "optional_slots": sorted(self.optional_slots),
            "last_transition": self.last_transition,
            "entered_at": self.entered_at,
        }


def branch_belongs_to_lifecycle(branch):
    """Check if a branch has a defined lifecycle."""
    return branch in branch_policy.BRANCH_DEFINITIONS


def get_stage_sequence():
    """Return the ordered list of lifecycle stages."""
    return list(STAGE_SEQUENCE)


def get_next_stage(current_stage):
    """Return the next stage in the lifecycle, or None if at CLOSURE."""
    if isinstance(current_stage, LifecycleStage):
        return _LIFECYCLE_TRANSITIONS.get(current_stage)
    return None


def get_preceding_stage(current_stage):
    """Return the preceding stage in the lifecycle, or None if at START."""
    if isinstance(current_stage, LifecycleStage):
        idx = _STAGE_INDEX.get(current_stage)
        if idx is not None and idx > 0:
            return STAGE_SEQUENCE[idx - 1]
    return None


def is_forbidden_transition(from_stage, to_stage):
    """Check if a transition is forbidden."""
    if isinstance(from_stage, LifecycleStage) and isinstance(to_stage, LifecycleStage):
        return (from_stage, to_stage) in _FORBIDDEN_TRANSITIONS
    return False


def is_valid_transition(from_stage, to_stage):
    """Check if a transition follows the lifecycle sequence."""
    if isinstance(from_stage, LifecycleStage) and isinstance(to_stage, LifecycleStage):
        expected = _LIFECYCLE_TRANSITIONS.get(from_stage)
        return to_stage == expected
    return False


def completion_score(required_slots_filled, required_slots_total):
    """Compute completion score as a float 0.0-1.0."""
    if required_slots_total <= 0:
        return 1.0
    return required_slots_filled / required_slots_total


def is_complete(required_slots_filled, required_slots_total, threshold=1.0):
    """Check if the branch investigation is complete."""
    if required_slots_total <= 0:
        return True
    return (required_slots_filled / required_slots_total) >= threshold


def stage_transition(current_stage, target_stage, branch_state=None):
    """Attempt a stage transition. Returns (new_stage, reason) or (current_stage, reason)."""
    if current_stage == target_stage:
        return current_stage, "already in this stage"

    if is_forbidden_transition(current_stage, target_stage):
        return current_stage, "forbidden transition"

    if not is_valid_transition(current_stage, target_stage):
        return current_stage, "invalid transition — must follow lifecycle sequence"

    return target_stage, "transition allowed"


def evaluate_branch_lifecycle(branch, ctx):
    """Evaluate the branch lifecycle state for the current conversation turn.

    Returns a BranchState with the current stage, completion score,
    and next stage determined from the branch's required slots and
    the conversation context.
    """
    definition = branch_policy.BRANCH_DEFINITIONS.get(branch)
    if definition is None:
        return BranchState(active_branch=branch)

    required = set(definition["required_slots"])
    optional = set(definition.get("optional_slots", []))
    threshold = definition.get("completion_threshold", 1.0)

    fills = branch_policy.detect_slot_fills(
        ctx.get("message") or "", branch, ctx.get("intent_graph") or {})

    filled_required = required & fills
    filled_optional = optional & fills
    total_required = len(required)
    filled_count = len(filled_required)

    score = completion_score(filled_count, total_required)
    complete = is_complete(filled_count, total_required, threshold)

    current_stage = LifecycleStage.INVESTIGATION
    if complete:
        current_stage = LifecycleStage.UNDERSTANDING

    next_stage = get_next_stage(current_stage)

    return BranchState(
        active_branch=branch,
        current_stage=current_stage,
        preceding_stage=get_preceding_stage(current_stage),
        next_stage=next_stage,
        completion_score=round(score, 3),
        required_slots=filled_required,
        optional_slots=filled_optional,
        last_transition="evaluate",
        entered_at=None,
    )