# Conversation Planner V2

---

# Status

Behavior Specification

---

# Version

2.0

---

# Purpose

The Conversation Planner is the decision-making engine of the Wellness Companion.

It does not generate language.

It decides what should happen next.

Every AI response MUST originate from a planner decision.

The LLM is responsible only for expressing that decision naturally.

---

# Mission

Every user message should move the conversation one meaningful step forward.

The planner must continuously answer one question:

"What is the highest-value next action for this user right now?"

---

# Philosophy

The planner optimizes for user progress.

Not conversation length.

Not number of questions.

Not data collection.

The best conversation is the one requiring the fewest questions while providing the greatest value.

---

# Core Responsibilities

The planner SHALL

- determine the next action
- prevent loops
- avoid unnecessary questions
- decide when enough information exists
- decide when coaching should begin
- decide when conversation should end
- temporarily pause investigation
- resume previous investigations
- handle interruptions
- manage conversation modes

The planner SHALL NOT

- detect intent
- retrieve memory
- generate responses
- perform coaching
- execute interventions

---

# Planner Inputs

The planner receives

- RuntimeContext
- IntentGraph
- BranchState
- SlotGraph
- Memory Summary
- User Profile
- Conversation History
- Previous Planner Decision

---

# Planner Outputs

The planner returns

```typescript
PlannerDecision {

    action

    reason

    confidence

    nextState

    metadata

}
```

The Runtime executes the decision.

---

# Success Criteria

A successful planner

- never loops
- never repeats questions
- always knows why it asked something
- minimizes user effort
- maximizes coaching value
- adapts naturally to interruptions
- resumes conversations intelligently



---

# Chapter 1 – Planner Mental Model & Decision Philosophy

## Purpose

The Conversation Planner is the executive decision-making system of the Wellness Companion.

Its responsibility is not to answer the user's message.

Its responsibility is to decide what the AI should accomplish with the next response.

The LLM writes the response.

The Planner decides the objective.

---

# Core Principle

The Planner does not ask:

"What should I say?"

It asks:

"What should happen next?"

This distinction defines the entire architecture.

---

# Mission

Every planner decision SHALL move the user closer to a healthier, more informed, or more actionable state.

A response that does not improve the user's situation is considered a failed planner decision.

---

# The Planner's Mental Model

Before every response, the planner SHALL internally evaluate the conversation using the following sequence.

```text
1. What does the user want right now?

↓

2. What do I already know?

↓

3. What important information is still missing?

↓

4. Do I actually need that information?

↓

5. Can I already provide value?

↓

6. What single action moves the conversation forward the most?
```

The planner SHALL complete this reasoning before selecting an action.

---

# Planner Philosophy

The planner SHALL optimize for

- user progress
- understanding
- trust
- efficiency
- emotional safety
- long-term behavior change

The planner SHALL NOT optimize for

- asking many questions
- collecting unnecessary data
- maximizing conversation length
- filling every slot before helping

---

# The One Question Rule

Before asking any question, the planner SHALL ask itself:

"If I already know enough to help, why am I asking another question?"

If no strong justification exists,

the planner SHALL provide value instead of asking.

---

# Conversation Momentum

Every response SHALL increase momentum.

Momentum is increased when the AI

- uncovers useful information
- provides meaningful insight
- helps the user make a decision
- reduces uncertainty
- creates motivation
- encourages action

Momentum is decreased when the AI

- repeats questions
- changes topic unnecessarily
- restarts discovery
- ignores previous context
- asks for information it already has

The planner SHALL maximize momentum.

---

# Information Economy

Information is expensive.

Every question consumes user attention.

Therefore,

questions SHALL be treated as scarce resources.

The planner SHALL collect only information that changes future decisions.

Questions that do not influence coaching SHALL NOT be asked.

---

# Value Before Data

The planner SHALL prefer

```text
Observe

↓

Understand

↓

Help

↓

Refine Understanding
```

It SHALL NOT prefer

```text
Ask

↓

Ask

↓

Ask

↓

Ask

↓

Finally Help
```

The AI should begin creating value as early as possible.

---

# Progress Over Perfection

The planner SHALL avoid waiting for perfect understanding.

If sufficient confidence exists,

the planner SHALL act.

Small improvements delivered early are preferred over perfect advice delivered too late.

---

# Respect Existing Knowledge

The planner SHALL never ask

- what is already known
- what the user just answered
- what exists in memory
- what can be inferred

Inference is preferred over interrogation.

---

# User Effort Minimization

Every planner decision SHALL attempt to reduce cognitive effort.

Examples

Instead of

"Tell me everything about your sleep."

Prefer

"You mentioned sleeping only five hours. Has that been happening most nights?"

The planner SHALL narrow decisions rather than broaden them.

---

# Behavioral Coaching Philosophy

The objective is not to solve the user's entire life in one conversation.

The objective is to help the user take one meaningful next step.

Large goals SHALL be decomposed into achievable actions.

---

# Planner Decision Hierarchy

When multiple valid actions exist,

the planner SHALL prioritize

1. Prevent harm
2. Resolve confusion
3. Continue current topic
4. Provide value
5. Gather missing information
6. Introduce new topics

This ordering SHALL remain consistent.

---

# Human Conversation Principle

The planner SHALL behave as a thoughtful human coach.

A thoughtful coach

- listens before speaking
- remembers previous discussion
- notices emotional shifts
- answers direct questions immediately
- does not ignore interruptions
- knows when to stop asking questions
- adapts naturally

The planner SHALL emulate these conversational principles.

---

# Success Criteria

The planner is successful when

✓ Conversations feel natural.

✓ Users rarely repeat themselves.

✓ Questions feel purposeful.

✓ Advice arrives at the right time.

✓ Users feel understood.

✓ The AI avoids repetitive conversational patterns.

✓ Every response has a clear objective.

---

# ADR-CP-001

## Decision

Adopt a progress-first planning philosophy where every response is chosen based on its ability to create meaningful user progress rather than maximize information collection.

## Status

Accepted

## Reason

Users return because conversations help them move forward, not because the AI asks many questions. Optimizing for progress produces shorter, more useful, and more human coaching conversations.

---

# Chapter 2 – Planner Actions & Decision Space

## Purpose

The Conversation Planner SHALL never generate responses directly.

Instead, it SHALL select one Planner Action.

The selected action defines the objective of the next AI response.

The LLM is responsible only for expressing that action naturally.

---

# Core Principle

Every AI response MUST originate from exactly one Planner Action.

The planner SHALL never generate free-form objectives.

Using a finite decision space guarantees

- predictable behavior
- easier debugging
- loop prevention
- measurable planner quality
- consistent coaching

---

# Planner Decision Process

Before every response

The planner SHALL complete the following sequence.

```text
Understand User

↓

Evaluate RuntimeContext

↓

Evaluate IntentGraph

↓

Evaluate Conversation State

↓

Select Planner Action

↓

Generate PlannerDecision

↓

LLM Generates Response
```

The planner SHALL never bypass this process.

---

# PlannerAction

```typescript
enum PlannerAction {

    ASK_QUESTION,

    ANSWER_DIRECT_QUESTION,

    ANSWER_CAPABILITY,

    PROVIDE_INSIGHT,

    PROVIDE_RECOMMENDATION,

    EXPLORE_TOPIC,

    CLARIFY,

    CONFIRM_UNDERSTANDING,

    CREATE_COMMITMENT,

    SCHEDULE_ACTION,

    CHECK_PROGRESS,

    RESUME_TOPIC,

    SWITCH_TOPIC,

    CASUAL_CHAT,

    REFLECT,

    SUMMARIZE,

    CLOSE_CONVERSATION,

    ESCALATE,

    WAIT

}
```

No planner decision SHALL exist outside this set.

---

# Action Definitions

## ASK_QUESTION

Purpose

Collect information that will change future coaching.

Requirements

- question must be necessary
- must not duplicate existing knowledge
- must narrow uncertainty

Example

"You mentioned headaches. When did they start?"

---

## ANSWER_DIRECT_QUESTION

Purpose

Answer exactly what the user asked.

Planner SHALL prioritize this over continuing investigations.

Example

User

"Why do I feel tired?"

Planner

ANSWER_DIRECT_QUESTION

---

## ANSWER_CAPABILITY

Purpose

Explain what the assistant can do.

Current investigation SHALL be paused.

After completion

Planner SHALL resume previous conversation naturally.

Example

"What can you help me with?"

---

## PROVIDE_INSIGHT

Purpose

Explain patterns, relationships, or observations.

Examples

"I've noticed your mood often drops after several nights of poor sleep."

No new question is required.

---

## PROVIDE_RECOMMENDATION

Purpose

Offer one actionable recommendation.

Recommendations SHALL be specific.

After acceptance,

Planner SHALL transition to CREATE_COMMITMENT.

---

## EXPLORE_TOPIC

Purpose

Deepen understanding of the active branch.

The planner SHALL remain within the current topic.

It SHALL NOT restart discovery.

---

## CLARIFY

Purpose

Resolve ambiguity.

Example

"When you say exhausted, do you mean physically tired or mentally drained?"

Clarification SHALL narrow uncertainty.

---

## CONFIRM_UNDERSTANDING

Purpose

Verify an important hypothesis before acting.

Example

"So it sounds like work stress has been affecting your sleep. Is that right?"

---

## CREATE_COMMITMENT

Purpose

Convert accepted advice into an achievable action.

Example

"Would tomorrow morning be a good time to try this?"

Planner SHALL avoid returning to discovery.

---

## SCHEDULE_ACTION

Purpose

Determine when the user intends to perform an agreed action.

Scheduling SHALL occur only after commitment.

---

## CHECK_PROGRESS

Purpose

Review progress on previous commitments.

This action is primarily used in follow-up conversations.

---

## RESUME_TOPIC

Purpose

Return to a previously paused conversation.

Example

User

"What can you do?"

↓

Planner answers

↓

Planner resumes sleep discussion.

---

## SWITCH_TOPIC

Purpose

Transition cleanly to a new topic.

The planner SHALL preserve previous context.

Example

"Let's talk about productivity instead."

---

## CASUAL_CHAT

Purpose

Suspend coaching.

Allow natural conversation.

The planner SHALL NOT ask diagnostic questions.

The planner SHALL remain capable of returning to coaching later.

---

## REFLECT

Purpose

Help the user process thoughts or emotions.

Reflection SHALL prioritize listening over advising.

---

## SUMMARIZE

Purpose

Summarize discoveries before ending or transitioning.

Example

"Today we discovered..."

---

## CLOSE_CONVERSATION

Purpose

End the interaction naturally.

Planner SHALL avoid reopening discovery.

---

## ESCALATE

Purpose

Handle crisis, safety, or human-support situations.

The planner SHALL immediately suspend normal coaching.

---

## WAIT

Purpose

Pause for user input.

No additional question SHALL be asked.

---

# Action Priority

When multiple actions are valid

The planner SHALL prefer

| Priority | Action |
|-----------|--------|
| 1 | ESCALATE |
| 2 | ANSWER_DIRECT_QUESTION |
| 3 | ANSWER_CAPABILITY |
| 4 | CLARIFY |
| 5 | CONFIRM_UNDERSTANDING |
| 6 | PROVIDE_INSIGHT |
| 7 | PROVIDE_RECOMMENDATION |
| 8 | CREATE_COMMITMENT |
| 9 | CHECK_PROGRESS |
|10 | EXPLORE_TOPIC |
|11 | ASK_QUESTION |
|12 | RESUME_TOPIC |
|13 | SWITCH_TOPIC |
|14 | REFLECT |
|15 | SUMMARIZE |
|16 | CLOSE_CONVERSATION |
|17 | CASUAL_CHAT |
|18 | WAIT |

Higher-priority actions SHALL interrupt lower-priority ones when appropriate.

---

# Action Transition Rules

Example

```text
PROVIDE_RECOMMENDATION

↓

User Accepts

↓

CREATE_COMMITMENT

↓

SCHEDULE_ACTION

↓

CLOSE_CONVERSATION
```

Never

```text
Recommendation

↓

Root Menu

↓

Category Buttons
```

---

# Forbidden Planner Behavior

The planner SHALL NOT

- repeat the same Planner Action without new information
- restart discovery after recommendation acceptance
- ignore direct questions
- ignore capability questions
- ignore topic switches
- ignore accepted commitments
- return to the root menu unless beginning a brand-new conversation

---

# Acceptance Criteria

Implementation is complete when

✓ Every response maps to one Planner Action.

✓ Direct questions interrupt investigations.

✓ Capability questions pause and resume conversations.

✓ Recommendation acceptance creates commitments.

✓ Casual chat disables coaching temporarily.

✓ Planner no longer relies on root-menu recovery.

✓ Action transitions remain deterministic.

---

# ADR-CP-002

## Decision

Adopt a finite Planner Action model where every AI response originates from a predefined action rather than free-form planning.

## Status

Accepted

## Reason

A finite action space makes planner behavior deterministic, measurable, testable, and significantly reduces conversational loops while preserving flexibility in natural language generation.

---

# Chapter 3 – Conversation Modes & State Machine

## Purpose

The Conversation Planner SHALL operate within exactly one Conversation Mode at any given time.

A Conversation Mode represents the current objective of the conversation.

Modes prevent the planner from asking inappropriate questions, restarting discovery, or ignoring user interruptions.

Every Planner Decision SHALL be influenced by the active Conversation Mode.

---

# Core Principle

A conversation is not just a sequence of messages.

It is a sequence of changing objectives.

The Planner SHALL always know

- where the conversation currently is
- why it is there
- what event causes it to leave
- where it should go next

---

# ConversationMode

```typescript
enum ConversationMode {

    DISCOVERY,

    INVESTIGATION,

    COACHING,

    REFLECTION,

    COMMITMENT,

    FOLLOW_UP,

    QUESTION_ANSWERING,

    CASUAL_CHAT,

    SUMMARIZATION,

    CLOSURE,

    ESCALATION

}
```

The Runtime SHALL maintain exactly one active mode.

---

# Mode Definitions

## DISCOVERY

Purpose

Understand why the user came.

Entry

- New conversation
- User gives no clear direction

Exit

- Clear primary topic discovered

Allowed Actions

- ASK_QUESTION
- CLARIFY
- CONFIRM_UNDERSTANDING

Forbidden

- Deep coaching
- Recommendations
- Re-entering Discovery

---

## INVESTIGATION

Purpose

Understand one specific problem.

Entry

- Discovery completed
- User selected topic
- Intent Resolver confidence high

Allowed

- EXPLORE_TOPIC
- ASK_QUESTION
- PROVIDE_INSIGHT

Exit

Enough confidence to help.

---

## COACHING

Purpose

Provide guidance.

Entry

- Investigation complete

Allowed

- PROVIDE_RECOMMENDATION
- PROVIDE_INSIGHT
- CREATE_COMMITMENT

Forbidden

- Restart Discovery

---

## REFLECTION

Purpose

Help users think.

Entry

- Emotional conversations
- Journaling
- Self-awareness

Allowed

- REFLECT
- CONFIRM_UNDERSTANDING

The planner SHALL prioritize listening.

---

## COMMITMENT

Purpose

Turn intention into action.

Allowed

- CREATE_COMMITMENT
- SCHEDULE_ACTION

Exit

Commitment completed.

---

## FOLLOW_UP

Purpose

Review previous commitments.

Allowed

- CHECK_PROGRESS
- PROVIDE_INSIGHT

Discovery SHALL NOT occur.

---

## QUESTION_ANSWERING

Purpose

Answer direct user questions.

Examples

"What can you do?"

"Why do I feel tired?"

The previous mode SHALL be remembered.

After completion

Planner SHALL return to the previous mode.

---

## CASUAL_CHAT

Purpose

Have a natural conversation.

Coaching SHALL be suspended.

The planner SHALL NOT ask diagnostic questions.

Examples

"Tell me a joke."

"How's your day?"

"What movies do you like?"

Exit

User introduces a coaching-related concern.

---

## SUMMARIZATION

Purpose

Summarize progress.

Allowed

- SUMMARIZE

Exit

Closure or Follow-up.

---

## CLOSURE

Purpose

End the conversation naturally.

Allowed

- CLOSE_CONVERSATION

The planner SHALL NOT restart Discovery.

---

## ESCALATION

Purpose

Handle safety-sensitive situations.

Normal coaching SHALL immediately stop.

Only safety workflows are permitted.

---

# State Machine

```text
DISCOVERY

↓

INVESTIGATION

↓

COACHING

↓

COMMITMENT

↓

FOLLOW_UP

↓

CLOSURE
```

Supporting transitions

```text
Any Mode

↓

QUESTION_ANSWERING

↓

Return to Previous Mode
```

```text
Any Mode

↓

CASUAL_CHAT

↓

Return to Previous Mode
```

```text
Any Mode

↓

ESCALATION
```

---

# Valid Transitions

| From | To |
|--------|------|
| DISCOVERY | INVESTIGATION |
| INVESTIGATION | COACHING |
| COACHING | COMMITMENT |
| COMMITMENT | FOLLOW_UP |
| FOLLOW_UP | CLOSURE |
| Any | QUESTION_ANSWERING |
| Any | CASUAL_CHAT |
| Any | ESCALATION |

---

# Invalid Transitions

The planner SHALL reject

```
COACHING

↓

DISCOVERY
```

```
COMMITMENT

↓

DISCOVERY
```

```
FOLLOW_UP

↓

DISCOVERY
```

```
CLOSURE

↓

DISCOVERY
```

unless a completely new conversation has begun.

---

# Mode Persistence

The Runtime SHALL store

```typescript
ConversationModeState {

    currentMode;

    previousMode;

    enteredAt;

    enteredBy;

    exitCondition;

}
```

Mode SHALL survive interruptions.

---

# Interruption Handling

Example

```text
Current Mode

COACHING

↓

User

"What can you do?"

↓

QUESTION_ANSWERING

↓

Answer

↓

Return

↓

COACHING
```

The previous mode SHALL always resume.

---

# Casual Chat Behavior

When in CASUAL_CHAT

The planner SHALL

- stop investigative questioning
- answer conversationally
- maintain memory
- avoid switching back to coaching unless the user introduces a coaching topic

Example

User

"Let's just chat."

Planner

CASUAL_CHAT

NOT

DISCOVERY

---

# Exit Conditions

Each mode SHALL define explicit exit conditions.

The planner SHALL NOT leave a mode arbitrarily.

Examples

DISCOVERY

Exit

Primary concern identified.

COACHING

Exit

Recommendation accepted or declined.

FOLLOW_UP

Exit

Progress reviewed.

---

# Loop Prevention Rules

The planner SHALL NEVER

- re-enter DISCOVERY without a new conversation
- ask the same discovery question twice
- restart after commitment
- forget the previous mode
- lose context after interruptions

These rules are mandatory.

---

# Acceptance Criteria

Implementation is complete when

✓ Exactly one mode is active.

✓ Direct questions temporarily suspend the current mode.

✓ Casual chat suspends coaching.

✓ Previous mode resumes automatically.

✓ Discovery occurs only once per conversation.

✓ Invalid transitions are rejected.

✓ Planner no longer falls back to the root discovery state.

---

# ADR-CP-003

## Decision

Adopt an explicit Conversation Mode state machine to control planner behavior.

## Status

Accepted

## Reason

Conversation modes provide deterministic behavioral control, prevent repeated discovery loops, support interruptions gracefully, and ensure conversations progress toward meaningful outcomes instead of restarting.