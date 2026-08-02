RFC-001 — Adaptive Conversation Orchestrator (ACO)
# Version History

| Version | Date | Changes |
|----------|------|---------|
| 0.1 | Today | Initial philosophy |


# Table of Contents

1. Philosophy, Mental Model & Core Principles
2. Intent Resolution
3. Branch Intelligence
4. Slot Intelligence
5. Question Planning
6. Conversation Economics
7. Adaptive Coaching Intelligence
8. Recovery System
9. Loop Prevention
10. Implementation Guidelines
11. Testing Specification
12. Future Extensions






Chapter 1 — Philosophy, Mental Model & Core Principles
Document Information
Field	Value
RFC	RFC-001
Title	Adaptive Conversation Orchestrator
Version	1.0 Draft
Status	Draft
Owner	AI Architecture
Applies To	AI Wellness Coach
Dependencies	Memory Engine, Behavior Engine, Hypothesis Engine, Why Engine, Objective Engine
1. Mission Statement

The purpose of the Adaptive Conversation Orchestrator (ACO) is not to control conversations.

Its purpose is to continuously improve the AI's understanding of the user while minimizing conversational effort.

Every conversation should leave the AI knowing the user slightly better than before.

Every conversation should leave the user feeling slightly more understood than before.

These two goals are equally important.

2. The Core Problem

Traditional chatbots operate like this:

Receive Message

↓

Generate Response

↓

Wait

This creates isolated conversations.

There is no long-term understanding.

Many guided coaching systems operate like this:

State

↓

Question

↓

Next State

↓

Next Question

This creates rigid conversations.

The user adapts to the system.

ACO introduces a third model.

User Message

↓

Understand

↓

Update User Model

↓

Determine Missing Knowledge

↓

Determine Highest Value Action

↓

Generate Response

The AI adapts to the user.

3. The Mental Model

The orchestrator never asks:

"What state am I in?"

Instead it always asks five questions.

Question 1
What do I currently know?

Examples:

Sleep duration
Stress level
Current goals
Work situation
Emotional state
Previous commitments
Active routines

Knowledge is retrieved from Memory, Behavior Engine, Why Engine, Hypothesis Engine, and active conversation context.

Question 2
How certain am I?

Knowing something is different from believing it confidently.

Example

Sleep = 5 hours

Confidence = 95%

versus

Sleep = "probably around 5–6 hours"

Confidence = 42%

The orchestrator should always reason with confidence.

Question 3
What is still unknown?

Unknown information is more valuable than repeated information.

Example

Known

sleeps 5 hours
stressed
tired

Unknown

when did this begin?

The next question should target the unknown with the highest value.

Question 4
What action creates the most value?

The answer is not always "ask another question."

Sometimes the best action is:

summarize
reflect
validate emotion
recommend
celebrate progress
pause
simply listen

The orchestrator chooses actions, not questions.

Question 5
Has the user's understanding improved?

The conversation should improve BOTH

the AI's understanding

and

the user's understanding.

If neither improved,

the conversation produced little value.

4. The Understanding Model

ACO does not track conversation.

ACO tracks understanding.

Every conversation modifies an internal understanding graph.

Example

Understanding

Sleep

██████░░░░

60%

Stress

████████░░

80%

Career

██░░░░░░░░

20%

Relationships

████░░░░░░

40%

This graph changes continuously.

It becomes the true state of the AI.

Conversation state becomes temporary.

Understanding becomes permanent.

5. The Three Layers of Understanding

The AI should separate information into three layers.

Layer 1 — Facts

Objective information.

Examples

sleeps 6 hours
works remotely
drinks coffee
goes to gym

Facts are observable.

Layer 2 — Beliefs

Interpretations.

Examples

lack of sleep contributes to low energy
work pressure increases anxiety
morning routine improves focus

Beliefs contain confidence.

Beliefs can change.

Layer 3 — Unknowns

Missing information.

Examples

motivation trigger unknown
burnout cause unknown
bedtime unknown

Unknowns drive conversation.

Not states.

6. The Golden Rule

The orchestrator exists for one reason.

Reduce uncertainty while increasing value.

Every message should do at least one of these.

Increase understanding.

Reduce uncertainty.

Strengthen trust.

Help the user.

If a response does none of these,

it should not be sent.

7. The Laws of Conversation

These are non-negotiable.

Law 1

Never ask a question if the answer is already known.

Law 2

Never ask two questions in one message unless absolutely necessary.

Law 3

Never recommend before understanding.

Law 4

Free text always overrides UI.

Buttons are shortcuts.

Never requirements.

Law 5

Understanding is permanent.

Conversation state is temporary.

Law 6

The AI should investigate success as often as problems.

If a user says:

"I actually slept well this week."

The AI should explore why.

Success teaches as much as failure.

Law 7

Curiosity has limits.

Do not interrogate.

If the AI has asked multiple questions without providing value, it must switch to giving an insight, reflection, encouragement, or actionable guidance.

Law 8

Every response must have a purpose.

Allowed purposes include:

Understand
Clarify
Reflect
Validate
Encourage
Challenge
Recommend
Celebrate
Summarize

If no purpose exists,

do not generate the response.

Law 9

The AI remembers commitments.

If a user says

"I'll try sleeping earlier."

The AI must follow up later.

Otherwise trust is reduced.

Law 10

The AI must earn the right to coach.

Understanding comes first.

Advice comes second.

8. Success Criteria

ACO is considered successful when:

The user rarely repeats information.
The AI naturally resumes previous conversations.
The AI asks fewer but higher-value questions.
The AI recognizes patterns instead of isolated facts.
The AI adapts to free text without requiring buttons.
The AI avoids loops and unnecessary repetition.
The user feels understood before feeling advised.
9. Architectural Principle

The orchestrator is not an AI engine.

It is a decision-making layer.

Its responsibilities are limited to:

deciding what information is missing,
deciding what the next objective is,
selecting the highest-value conversational action,
coordinating existing engines.

It must never duplicate the responsibilities of the Memory Engine, Behavior Engine, Hypothesis Engine, Why Engine, or LLM.

RFC-001 – Chapter 2.1
Intent Resolution Architecture
Purpose

The Intent Resolution System (IRS) is the first decision-making component executed after every user message.

Its responsibility is not to generate responses.

Its responsibility is to determine what the user is trying to accomplish before any conversation planning occurs.

The output of the Intent Resolver becomes the primary input for the Adaptive Conversation Orchestrator.

Responsibilities

The Intent Resolver SHALL:

Understand the user's immediate intention.
Preserve conversational context.
Detect whether the current conversation should continue or change direction.
Allow free-text responses to replace UI button selections.
Prevent unnecessary state resets.
Detect interruptions.
Detect corrections.
Detect emotional shifts.
Support multiple simultaneous intents.

The Intent Resolver SHALL NOT:

Generate coaching advice.
Decide recommendations.
Store memories.
Update hypotheses.
Rank interventions.

Those responsibilities belong to other engines.

Execution Order

Every user message MUST follow this pipeline.

User Message
      │
      ▼
Normalize Input
      │
      ▼
Intent Resolver
      │
      ▼
Branch Manager
      │
      ▼
Slot Resolver
      │
      ▼
Question Planner
      │
      ▼
Reasoning Pipeline
      │
      ▼
LLM

The Intent Resolver is always executed before every other orchestration component.

Design Principles

The Intent Resolver follows five principles.

Principle 1 — User Meaning Over UI

The user's message always has higher priority than interface controls.

Example

AI:

Which area matters most?

Buttons:

Sleep
Stress
Productivity

User types:

"I've been exhausted for weeks."

The resolver SHALL infer:

Primary Branch:
Physical Health

Sub Branch:
Energy

The user SHALL NOT be asked to click a button.

Principle 2 — Meaning Before Keywords

Intent is determined by meaning rather than exact words.

Example

"I'm completely drained."

"I'm exhausted."

"I have no energy."

"I can't keep my eyes open."

All should resolve to the same semantic intent.

Implementations SHOULD rely on semantic similarity or structured LLM classification rather than keyword matching alone.

Principle 3 — Context First

The resolver SHALL interpret messages using:

Current conversation
Active branch
Previous AI question
Recent memory
Conversation objective

Example

AI asks:

"How many hours do you sleep?"

User replies:

"About five."

Without context, "About five" is ambiguous.

With context, it resolves to:

sleep_hours = 5
Principle 4 — Never Lose Progress

Intent resolution SHALL preserve the current investigation whenever possible.

Example

Current branch:

Physical Health

↓

Energy Investigation

User says:

"Also work has been stressful."

This should produce:

Primary Intent:
Continue Energy Investigation

Secondary Intent:
Record Work Stress

The investigation SHALL continue.

Principle 5 — Every Message Has Intent

No user message is considered meaningless.

Even:

Okay

Hmm

Maybe

Not sure

...

must resolve into a recognized conversational action.

Intent Categories

Every message SHALL be classified into one or more of these high-level categories.

Category	Description
Answer	User answers the current question
New Information	User provides additional facts
Clarification	User requests clarification
Question	User asks the AI something
Topic Change	User wants to discuss something else
Emotion	User expresses feelings
Correction	User corrects previous information
Confirmation	User confirms an AI assumption
Rejection	User rejects a suggestion or question
Greeting	Conversation start or resume
Goodbye	Conversation ending
Crisis	Safety-critical content
Meta	User asks about the AI or app
Small Talk	Casual conversation
Unknown	Confidence too low to classify

These are categories only.

Detailed intent definitions will appear in Chapter 2.2.

Intent Resolution Output

The Intent Resolver SHALL return a structured object.

{
  "primary_intent": "",
  "secondary_intents": [],
  "confidence": 0.94,

  "continue_branch": true,
  "branch_change_requested": false,

  "answered_current_question": true,

  "new_slots_detected": [],

  "topic_shift": false,

  "emotion_shift": false,

  "requires_clarification": false,

  "reason": ""
}

This object is the contract between the Intent Resolver and the rest of the orchestrator.

Priority Rules

When multiple intents are detected, they SHALL be processed in the following order:

Priority	Intent
1	Crisis / Emergency
2	Correction
3	Direct Answer
4	Clarification Request
5	Topic Change
6	Emotion
7	New Information
8	Question
9	Small Talk
10	Greeting

Higher-priority intents may interrupt lower-priority processing.

Example:

User says:

"Actually I don't sleep five hours anymore. Also I have a question."

The resolver SHALL process:

Correction
Update understanding
User Question
Acceptance Criteria

The Intent Resolver is considered correct if it satisfies the following:

Free-text answers advance the conversation without requiring button clicks.
Current investigations are preserved unless a higher-priority intent requires interruption.
Multiple intents can be represented simultaneously.
Previously answered questions are recognized.
Ambiguous messages trigger clarification rather than incorrect assumptions.
Intent output is deterministic and consumed by downstream components.

# Chapter 2.2 – Intent Classification

---

# Purpose

The Intent Classification System defines every conversational intent the Adaptive Conversation Orchestrator (ACO) can recognize.

Intent classification is responsible for answering one question:

> **"What is the user trying to accomplish with this message?"**

This classification determines how every downstream component behaves.

Intent classification MUST be deterministic.

The LLM may assist with semantic understanding, but the orchestrator owns the final routing decision.

---

# Design Goals

The classifier SHALL

- understand user goals
- support natural language
- support UI button selections
- support mixed messages
- support interruptions
- preserve context
- avoid incorrect branch changes

The classifier SHALL NOT

- generate coaching
- update memory
- select interventions
- produce responses

---

# Classification Pipeline

Every incoming message passes through the following stages.

```

User Message
│
▼
Normalize Input
│
▼
Extract Meaning
│
▼
Detect Candidate Intents
│
▼
Calculate Confidence
│
▼
Resolve Priority
│
▼
Return Structured Intent

```

---

# Intent Object

Every detected intent SHALL follow this structure.

```json
{
    "intent": "",
    "confidence": 0.95,
    "priority": 1,
    "requires_branch_change": false,
    "requires_clarification": false,
    "slot_updates": [],
    "notes": ""
}
```

---

# Confidence Levels

| Confidence | Meaning | Action |
|------------|---------|--------|
| 0.95–1.00 | Certain | Execute |
| 0.80–0.94 | High | Execute |
| 0.60–0.79 | Medium | Continue but monitor |
| 0.40–0.59 | Low | Clarify |
| Below 0.40 | Unknown | Ask clarifying question |

The orchestrator MUST never silently guess below 0.60 confidence.

---

# Supported Intents

The system currently supports sixteen primary intents.

---

## Intent 1 — Greeting

Purpose

Conversation start or return.

Examples

"Hi"

"Hello"

"Good morning"

"I’m back"

Action

Resume previous context if available.

Never restart onboarding automatically.

---

## Intent 2 — Answer Current Question

Purpose

The user answered what the AI asked.

Examples

AI

"How many hours do you sleep?"

User

"About five."

Action

Advance investigation.

Never ask the same question again.

---

## Intent 3 — Additional Information

Purpose

User provides more context than requested.

Example

AI

"How many hours do you sleep?"

User

"I sleep about five hours because work has been hectic."

Action

Update slots.

Store additional context.

Continue current investigation.

---

## Intent 4 — Correction

Purpose

User corrects previous information.

Example

"I actually sleep seven hours now."

Action

Update facts.

Reduce confidence in previous belief.

Never create duplicate memories.

---

## Intent 5 — Clarification Request

Purpose

User does not understand.

Examples

"What do you mean?"

"Can you explain?"

Action

Pause investigation.

Clarify.

Resume afterwards.

---

## Intent 6 — Ask AI Question

Purpose

The user wants information.

Examples

"Why am I always tired?"

"Can stress affect sleep?"

Action

Answer.

Resume previous branch afterwards.

---

## Intent 7 — Topic Change

Purpose

User intentionally changes discussion.

Example

"I don't want to talk about sleep anymore."

Action

Pause current branch.

Open new branch.

Store unfinished investigation.

---

## Intent 8 — Emotional Expression

Purpose

User expresses emotional state.

Examples

"I'm overwhelmed."

"I feel hopeless."

"I'm really excited."

Action

Update emotion.

Re-evaluate objective.

Do not ignore emotion because another branch is active.

---

## Intent 9 — Goal Update

Purpose

User changes long-term goal.

Example

"I want to focus on weight loss now."

Action

Update profile.

Update coaching objective.

---

## Intent 10 — Commitment

Purpose

User promises an action.

Examples

"I'll sleep earlier."

"I'll try walking."

Action

Create follow-up reminder.

Track commitment.

---

## Intent 11 — Success

Purpose

User reports improvement.

Examples

"I actually slept well."

"I exercised three times."

Action

Celebrate.

Investigate WHY success happened.

Strengthen habits.

---

## Intent 12 — Failure

Purpose

User reports setback.

Examples

"I failed again."

"I skipped everything."

Action

Avoid judgement.

Investigate obstacles.

Do not immediately recommend solutions.

---

## Intent 13 — Rejection

Purpose

User rejects recommendation.

Example

"I don't want to meditate."

Action

Understand reason.

Offer alternatives.

---

## Intent 14 — Small Talk

Purpose

Relationship building.

Examples

"How are you?"

"What's up?"

Action

Respond briefly.

Return to coaching naturally.

---

## Intent 15 — Goodbye

Purpose

Conversation ending.

Examples

"Bye"

"Talk later"

Action

Summarize if appropriate.

Persist conversation.

End session.

---

## Intent 16 — Crisis

Purpose

Safety-critical situation.

Examples

Self-harm.

Immediate danger.

Medical emergency.

Action

Suspend all coaching.

Transfer to Crisis Protocol.

---

# Multiple Intent Detection

One message may contain multiple intents.

Example

"I'm exhausted, work is stressful and I don't want to meditate."

Detected

Primary

Emotional Expression

Secondary

Additional Information

Secondary

Rejection

The orchestrator SHALL preserve every detected intent.

---

# Intent Priority

When multiple intents exist.

Priority order SHALL be

1. Crisis
2. Correction
3. Commitment
4. Goal Update
5. Answer Current Question
6. Emotional Expression
7. Topic Change
8. Clarification
9. Additional Information
10. Ask AI Question
11. Success
12. Failure
13. Rejection
14. Greeting
15. Small Talk
16. Goodbye

Higher-priority intents execute first.

---

# Clarification Rules

If two candidate intents differ by less than 10% confidence

DO NOT guess.

Ask a clarification question.

Example

"I'm exhausted."

Possible

Sleep

Stress

Burnout

Confidence

Sleep

58%

Stress

54%

Action

Clarify.

Never assume.

---

# Acceptance Criteria

The Intent Classifier is complete when

✓ Free text replaces buttons naturally.

✓ Corrections update previous knowledge.

✓ Multiple intents are preserved.

✓ Investigations continue correctly.

✓ Topic changes do not lose progress.

✓ Low-confidence situations trigger clarification.

✓ The same message always produces the same classification.

---

# Implementation Notes

The classifier should expose a single interface.

```

resolveIntent()

```

Input

```

Conversation Context

User Message

Current Branch

Memory Summary

```

Output

```

ResolvedIntent

```

No other component should classify user intent independently.

All downstream systems MUST use the resolved intent generated by this module.



---

# Chapter 2.3 – Intent Graphs & Multi-Intent Resolution

---

# Purpose

Traditional conversational systems assume that every user message contains exactly one intent.

This assumption is incorrect.

Real users communicate multiple ideas, emotions, corrections, goals, and requests simultaneously.

The Adaptive Conversation Orchestrator SHALL preserve this richness rather than collapsing it into a single label.

The purpose of this chapter is to define how multiple intents are represented, prioritized, and consumed by downstream orchestration components.

---

# Problem Statement

Consider the following user message:

> "I've been sleeping only five hours because work has been crazy, and I promised myself I'd start exercising again."

A traditional chatbot typically extracts:

Intent:
Sleep

The remaining information is either ignored or stored without influencing the conversation.

The ACO SHALL instead recognize all meaningful conversational signals.

---

# Design Philosophy

The orchestrator SHALL NOT think:

```

One Message

↓

One Intent

```

Instead it SHALL think:

```

One Message

↓

Intent Graph

↓

Conversation Understanding

↓

Decision

```

Intent Graphs preserve the complexity of human communication.

---

# Intent Graph

An Intent Graph is a structured representation of all meaningful intents contained within a single user message.

It consists of:

- one Primary Intent
- zero or more Secondary Intents
- zero or more Background Intents
- relationships between intents

Intent Graphs are temporary structures.

They exist only during orchestration.

They are NOT stored as long-term memory.

---

# Intent Levels

## Primary Intent

The primary intent represents the user's dominant conversational goal.

Characteristics

- highest priority
- drives the next conversational action
- determines branch progression

Example

> "I'm exhausted."

Primary

Low Energy

---

## Secondary Intent

Secondary intents provide supporting context.

They enrich understanding but do not redirect the conversation.

Example

> "I'm exhausted because work has been stressful."

Primary

Low Energy

Secondary

Work Stress

---

## Background Intent

Background intents contain useful information that should be remembered but should not immediately change conversation direction.

Example

> "I'm exhausted because work has been stressful, and my sister is getting married next month."

Background

Family Event

The conversation SHOULD remain focused on the current investigation.

---

# Intent Graph Structure

Every graph SHALL contain

```json
{
    "primary_intent": {},
    "secondary_intents": [],
    "background_intents": [],
    "relationships": [],
    "overall_confidence": 0.91
}
```

---

# Intent Relationships

The orchestrator SHALL recognize relationships between intents.

Supported relationship types

| Relationship | Meaning |
|-------------|---------|
| Cause | One intent explains another |
| Effect | One intent results from another |
| Dependency | One intent depends on another |
| Conflict | Two intents contradict |
| Reinforcement | Multiple intents support each other |
| Independent | No relationship |

---

# Example

User

> "I'm exhausted because work has been overwhelming."

Intent Graph

```

Low Energy

↑

CAUSE

│

Work Stress

```

This graph tells downstream systems

Work Stress likely contributes to Low Energy.

---

# Intent Promotion

Secondary intents may become primary later.

Example

Conversation

Work Stress

↓

Later

User says

"I don't actually care about work anymore.

My sleep is the real issue."

The orchestrator SHALL promote

Sleep

to Primary Intent.

---

# Intent Demotion

Primary intents may become secondary when conversation focus changes naturally.

Demotion SHALL preserve history.

Demotion SHALL NOT delete information.

---

# Intent Conflict

Sometimes intents disagree.

Example

Conversation 1

"I enjoy mornings."

Conversation 10

"I hate mornings."

Intent Graph

Morning Preference

↓

Conflict

↓

Request Confirmation

The orchestrator SHALL prefer clarification over silent replacement.

---

# Intent Merging

Duplicate intents SHALL merge.

Example

"I'm exhausted."

"I'm tired."

"I have no energy."

Result

Single Intent

Low Energy

Confidence increases.

---

# Intent Splitting

Compound statements SHALL be separated.

Example

"I can't focus because I haven't been sleeping."

Split

Intent A

Low Focus

Intent B

Poor Sleep

Relationship

Poor Sleep

CAUSES

Low Focus

---

# Intent Confidence

Every intent SHALL maintain confidence independently.

Example

| Intent | Confidence |
|---------|-----------|
| Poor Sleep | 96% |
| Burnout | 51% |
| Depression | 28% |

Only high-confidence intents influence planning.

Low-confidence intents remain hypotheses.

---

# Intent Consumption

Different orchestrator components consume different portions of the graph.

| Component | Uses |
|-----------|------|
| Branch Manager | Primary Intent |
| Slot Resolver | Primary + Secondary |
| Memory Engine | Primary + Background |
| Hypothesis Engine | Entire Graph |
| Why Engine | Relationships |
| Question Planner | Unknowns within Graph |
| Objective Engine | Primary Intent |

This separation prevents duplicated reasoning.

---

# Branch Preservation

The Intent Graph SHALL never automatically abandon an active branch simply because a new secondary intent appears.

Example

Current Branch

Energy Investigation

User

"My work has been stressful."

Result

Continue Energy Investigation.

Store Work Stress.

Do NOT switch branches.

---

# Branch Switching Rules

A branch switch SHALL occur only when

- user explicitly requests it
- crisis detected
- current investigation completed
- current investigation abandoned

Secondary intents SHALL NOT trigger branch switching.

---

# Graph Lifecycle

Every graph follows

```

Create

↓

Populate

↓

Resolve

↓

Consume

↓

Discard

```

Graphs are ephemeral.

Knowledge extracted from them persists through Memory.

---

# Design Constraints

The graph SHALL

✓ support multiple intents

✓ preserve relationships

✓ support confidence

✓ remain deterministic

✓ avoid duplicate intents

✓ support future expansion

---

# Failure Modes

The orchestrator MUST detect

- circular intent relationships
- duplicate intent graphs
- orphan intents
- confidence inversion
- invalid relationships

These conditions SHALL trigger diagnostics.

---

# Acceptance Criteria

The implementation is complete when

✓ one message may produce multiple intents

✓ relationships are preserved

✓ branch switching is deterministic

✓ free text no longer collapses into one label

✓ downstream engines consume only the portions they require

✓ intent graphs are destroyed after orchestration

---

# Architecture Decision Record

## ADR-002

Decision

Represent user messages as Intent Graphs instead of single intent labels.

Status

Accepted

Reason

Human communication is multidimensional.

Collapsing messages into a single intent discards valuable context and leads to unnatural conversations.

Intent Graphs preserve conversational richness while maintaining deterministic orchestration.


---

# Chapter 2.4 – Intent Resolution Algorithms & Decision Engine

---

# Purpose

This chapter defines the deterministic algorithms used by the Intent Resolution System.

Previous chapters defined:

- what intents are
- how multiple intents are represented
- how Intent Graphs behave

This chapter defines **how the orchestrator makes decisions.**

The algorithms in this chapter MUST be deterministic.

The LLM may assist semantic understanding, but the orchestrator owns the final routing decision.

---

# Design Goals

The Intent Decision Engine SHALL

- resolve ambiguous user messages
- rank competing intents
- prevent unnecessary branch switching
- preserve conversation continuity
- minimize clarification questions
- support deterministic routing

---

# Decision Pipeline

Every user message SHALL pass through the following sequence.

```

Incoming Message

↓

Normalize

↓

Intent Classification

↓

Intent Graph Construction

↓

Confidence Calculation

↓

Priority Resolution

↓

Conflict Detection

↓

Branch Decision

↓

Question Planning

↓

Reasoning Pipeline

↓

LLM

```

Every stage MUST complete before the next stage begins.

---

# Algorithm 1 — Candidate Intent Generation

Purpose

Generate every possible intent from the user message.

Example

Message

"I've been sleeping five hours because work has been stressful."

Candidates

```

Low Sleep

Work Stress

Low Energy

```

Candidate generation SHALL prefer recall over precision.

Filtering happens later.

---

# Algorithm 2 — Confidence Calculation

Every candidate receives an independent confidence score.

Confidence SHALL be calculated using multiple evidence sources.

| Source | Weight |
|---------|-------:|
| Semantic similarity | 35% |
| Current conversation | 25% |
| Active branch | 15% |
| Memory consistency | 15% |
| User history | 10% |

Example

```

Sleep Intent

Semantic

95

Conversation

90

Branch

100

Memory

88

History

91

↓

Final

93

```

Confidence values SHALL range from 0–100.

---

# Algorithm 3 — Intent Ranking

All candidates SHALL be ranked.

Ranking Score

```

Priority Weight

+

Confidence

+

Context Match

+

Branch Match

-

Conflict Penalty

```

Higher score wins.

---

# Algorithm 4 — Primary Intent Selection

The highest ranked intent becomes Primary only if

Confidence ≥ 80

Otherwise

clarification SHALL be considered.

Example

```

Sleep

92

Stress

85

↓

Primary

Sleep

↓

Secondary

Stress

```

---

# Algorithm 5 — Ambiguity Detection

The orchestrator SHALL detect ambiguity.

Example

```

Sleep

71

Stress

69

```

Difference

2%

This is ambiguous.

DO NOT GUESS.

Instead

Ask

```

You mentioned both your sleep and work.

Which one feels like the bigger issue right now?

```

---

# Algorithm 6 — Clarification Decision

Clarification SHALL occur when

- Confidence below threshold
- Intent conflict
- Slot conflict
- Equal ranking
- Contradictory memories

Clarification SHALL always attempt to resolve only one ambiguity.

Never ask multiple clarifications together.

---

# Algorithm 7 — Branch Continuity

Before opening a new branch

the orchestrator SHALL evaluate

```

Current Branch

↓

Complete?

↓

No

↓

Can new information become secondary?

↓

Yes

↓

Continue

```

The orchestrator SHALL prefer branch continuity.

---

# Algorithm 8 — Branch Switching

Branch changes SHALL require one of

✓ explicit user request

✓ crisis

✓ investigation complete

✓ user abandonment

Secondary intents SHALL NEVER trigger branch switching.

---

# Algorithm 9 — Slot Extraction

Intent Resolution SHALL identify slot values.

Example

```

"I've slept five hours for two weeks."

```

Extract

```

sleep_hours = 5

duration = 2 weeks

```

These slots SHALL be passed to Slot Resolver.

---

# Algorithm 10 — Duplicate Detection

The orchestrator SHALL detect duplicate information.

Example

Already Known

```

Sleep

5 hours

```

User

```

"I still sleep around five."

```

Result

Increase confidence.

Do NOT create duplicate facts.

Do NOT ask again.

---

# Algorithm 11 — Contradiction Detection

Example

Previous

```

Sleep

8 hours

```

Current

```

Sleep

5 hours

```

Decision

```

Conflict

↓

Ask confirmation

↓

Update memory

```

Never silently overwrite.

---

# Algorithm 12 — Information Gain

Every possible next question SHALL receive an Information Gain score.

Purpose

Determine which question reduces uncertainty the most.

Example

Known

```

Sleep

5

Stress

High

Energy

Low

```

Unknown

```

Duration

Bedtime

Wake Time

```

Information Gain

| Question | Gain |
|----------|-----:|
| Duration | 92 |
| Bedtime | 44 |
| Wake Time | 28 |

The orchestrator SHALL ask the highest gain question.

---

# Algorithm 13 — Question Cost

Every question has a cost.

Cost increases when

- already asked recently
- emotionally difficult
- conversation fatigue
- user frustration

Question Score

```

Information Gain

-

Question Cost

```

The highest net score wins.

---

# Algorithm 14 — Response Value Check

Before generating a response

the orchestrator SHALL evaluate

```

Questions Asked

↓

Insights Given

↓

Recommendations Given

↓

Reflection Given

```

If

```

Questions

>

3

```

without value

the AI SHALL stop asking questions.

Instead

Provide

- reflection
- insight
- encouragement
- recommendation

---

# Algorithm 15 — Objective Validation

Before response generation

verify

```

Current Objective

↓

Does selected question support objective?

↓

YES

↓

Continue

↓

NO

↓

Select different question

```

Every question MUST support today's objective.

---

# Algorithm 16 — Loop Detection

The orchestrator SHALL detect

- repeated questions
- repeated branches
- repeated objectives
- repeated clarifications

If detected

Recovery Mode SHALL activate.

---

# Decision Table

| Situation | Action |
|-----------|--------|
| High confidence | Continue |
| Medium confidence | Continue + monitor |
| Low confidence | Clarify |
| Conflict | Confirm |
| Crisis | Override |
| User changes topic | Pause branch |
| User answers current question | Advance |
| User provides future slots | Skip questions |
| Duplicate answer | Increase confidence |
| Branch complete | Close branch |

---

# Pseudocode

```text

resolveIntent(message):

normalize(message)

candidate_intents = classify(message)

intent_graph = build_graph(candidate_intents)

calculate_confidence(intent_graph)

resolve_conflicts(intent_graph)

select_primary(intent_graph)

extract_slots(message)

evaluate_information_gain()

select_best_question()

return DecisionContext

```

---

# Failure Modes

The implementation SHALL detect

- infinite clarification loops
- repeated branch switching
- conflicting slot updates
- confidence oscillation
- duplicate intent graphs
- orphan intents

Each SHALL generate diagnostics.

---

# Acceptance Criteria

Implementation is complete when

✓ Same input produces same decision.

✓ Free text advances branches.

✓ Buttons become optional.

✓ Duplicate questions disappear.

✓ Information Gain drives question selection.

✓ Ambiguous situations trigger clarification.

✓ Branch switching becomes deterministic.

✓ Loop detection prevents repeated investigations.

---

# Architecture Decision Record

## ADR-003

Decision

Intent resolution SHALL use deterministic algorithms after semantic understanding.

Status

Accepted

Reason

The LLM is responsible for language understanding.

The orchestrator is responsible for decision making.

Separating these responsibilities improves consistency, testability, and maintainability.

---

# Chapter 2.5 – Intent Resolution Edge Cases & Acceptance Tests

---

# Purpose

This chapter defines the official acceptance tests for the Intent Resolution System.

The implementation SHALL be considered complete only if every scenario in this chapter produces the expected behavior.

These tests form the baseline regression suite.

Every future modification to the Intent Resolver MUST pass these tests.

---

# Testing Philosophy

The objective of testing is NOT to verify that the AI produces pleasant responses.

The objective is to verify that the orchestrator makes correct decisions.

Tests focus on

- intent detection
- branch continuity
- slot extraction
- clarification
- branch switching
- loop prevention

Natural language generation is outside the scope of this chapter.

---

# Test Structure

Every test SHALL contain

- Scenario
- Previous Context
- User Message
- Expected Intent Graph
- Expected Branch
- Expected Slot Updates
- Expected Decision
- Pass Criteria

---

# Test Category A – Free Text Overrides Buttons

---

## Test A1

Previous Question

"What area is affecting you most?"

Buttons

Sleep

Stress

Work

Relationships

User

"I've been exhausted all week."

Expected

Primary Branch

Physical Health

Sub Branch

Energy

Decision

Advance without requiring button selection.

PASS

No button required.

---

## Test A2

Previous Question

"How many hours do you sleep?"

User

"Usually around five."

Expected

Slot

sleep_hours = 5

Decision

Advance.

PASS

No repeated sleep question.

---

## Test A3

Previous Question

"What concerns you?"

User

"My job has been overwhelming."

Expected

Primary Branch

Career

Secondary

Stress

PASS

Buttons ignored.

---

# Test Category B – Skip Logic

---

## Test B1

Known

sleep_hours

Unknown

duration

User

"I've been sleeping five hours for two weeks."

Expected

Update

sleep_hours

duration

Decision

Skip future duration question.

PASS

Never ask duration again.

---

## Test B2

User answers three future questions in one sentence.

Expected

Fill every slot.

Skip completed questions.

---

# Test Category C – Topic Switching

---

## Test C1

Current Branch

Sleep Investigation

User

"I actually want to talk about work."

Expected

Pause

Sleep

Open

Career

PASS

Progress preserved.

---

## Test C2

Current Branch

Stress

User

"Forget stress.

Let's discuss relationships."

Expected

Pause

Stress

Resume

Relationships

PASS

No data lost.

---

# Test Category D – Branch Continuity

---

## Test D1

Current Branch

Energy

User

"My work has also been stressful."

Expected

Continue

Energy

Store

Work Stress

PASS

No branch switch.

---

## Test D2

Current Branch

Burnout

User

"I'm also sleeping badly."

Expected

Secondary Intent

Poor Sleep

Continue

Burnout

PASS

---

# Test Category E – Corrections

---

## Test E1

Previous Memory

Sleep

5 hours

User

"I actually sleep seven hours now."

Expected

Conflict

Confirmation

Update Memory

PASS

Old memory replaced only after confirmation.

---

# Test Category F – Ambiguity

---

## Test F1

User

"I'm exhausted."

Possible

Sleep

Stress

Burnout

Confidence

Similar

Expected

Clarification

PASS

No assumptions.

---

# Test Category G – Duplicate Information

---

## Test G1

Memory

Sleep

5 hours

User

"I'm still sleeping five hours."

Expected

Increase confidence.

No duplicate memory.

PASS

---

# Test Category H – Commitments

---

## Test H1

User

"I'll try sleeping earlier."

Expected

Commitment

Follow-up scheduled.

PASS

---

# Test Category I – Positive Change

---

## Test I1

User

"I slept eight hours yesterday."

Expected

Celebrate.

Investigate why.

Store success.

PASS

---

# Test Category J – Failure

---

## Test J1

User

"I skipped everything again."

Expected

No judgement.

Investigate obstacles.

PASS

---

# Test Category K – Conversation Recovery

---

## Test K1

User

"I don't know."

Expected

Clarify.

Avoid repeating identical question.

---

## Test K2

User

"..."

Expected

Gentle follow-up.

No loop.

---

# Test Category L – Multi Intent

---

## Test L1

User

"I'm exhausted because work has been stressful and I promised myself I'd exercise."

Expected

Primary

Low Energy

Secondary

Work Stress

Commitment

Exercise

PASS

Intent Graph created.

---

## Test L2

User

"I'm anxious, I can't sleep and my relationship is falling apart."

Expected

Three intents.

No information lost.

---

# Test Category M – Return After Days

---

## Test M1

Conversation resumes after seven days.

Expected

Resume previous investigation if incomplete.

Otherwise

Start new conversation naturally.

PASS

---

# Test Category N – Loop Prevention

---

## Test N1

Question already answered.

Expected

Never ask again.

---

## Test N2

Completed Branch

Expected

Never reopen automatically.

---

## Test N3

Root category completed.

Expected

Never restart root selection.

---

# Test Category O – Safety

---

## Test O1

Self-harm mention.

Expected

Immediate Crisis Protocol.

PASS

---

## Test O2

Medical emergency.

Expected

Suspend coaching.

Safety first.

---

# Regression Checklist

Every release MUST verify

✓ Free text overrides buttons

✓ Branch continuity

✓ Slot extraction

✓ Duplicate detection

✓ Contradiction handling

✓ Clarification

✓ Intent Graph generation

✓ Branch preservation

✓ Skip Logic

✓ Loop Prevention

✓ Crisis detection

✓ Commitment tracking

✓ Positive reinforcement

✓ Recovery behavior

✓ Multi-intent support

---

# Acceptance Criteria

The Intent Resolution System SHALL be accepted only when

- every regression test passes
- deterministic outputs are produced
- branch continuity is preserved
- loops cannot be reproduced
- free text consistently overrides UI navigation
- duplicate questions are eliminated
- ambiguity results in clarification rather than assumptions
- completed branches remain closed unless explicitly reopened

---

# Architecture Decision Record

## ADR-004

Decision

Intent Resolution SHALL be validated using deterministic scenario-based regression tests rather than subjective conversation quality alone.

Status

Accepted

Reason

Conversation quality is difficult to measure consistently.

Decision quality is measurable, repeatable, and suitable for automated testing.

This allows future implementations to evolve without breaking established conversational behavior.

---

# Chapter 2.6 – Conversation Context Model (CCM)

---

# Purpose

The Conversation Context Model (CCM) is the canonical representation of the current conversational state.

It acts as the shared data contract between every orchestration component.

The CCM ensures that all reasoning components operate on the same understanding of the conversation.

Without a shared context model, each component develops its own interpretation, resulting in inconsistent behavior, repeated questions, broken branch progression, and conversation loops.

The CCM SHALL be the only source of truth for the active conversation.

---

# Design Goals

The CCM SHALL

- maintain the current conversational understanding
- coordinate all orchestration components
- preserve branch continuity
- support interruption and recovery
- eliminate duplicated state
- support deterministic orchestration

The CCM SHALL NOT

- store long-term memory
- replace the Memory Engine
- replace the Behavior Engine
- replace the Why Engine
- replace the Hypothesis Engine

It represents the current conversation only.

---

# Lifetime

Conversation Context exists only for the duration of a conversation.

When a conversation begins

↓

Create Context

When conversation ends

↓

Persist relevant knowledge

↓

Destroy Context

Only Memory survives.

Conversation Context does not.

---

# Ownership

The Adaptive Conversation Orchestrator owns the Conversation Context.

No other engine may directly modify context.

Every modification MUST pass through the orchestrator.

This prevents race conditions.

---

# High-Level Architecture

```

                 User Message
                       │
                       ▼
             Adaptive Conversation
                 Orchestrator
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
     Conversation   Memory      Behavior
       Context       Engine       Engine
          │            │            │
          └────────────┼────────────┘
                       ▼
               Question Planner
                       │
                       ▼
                      LLM

```

Conversation Context sits between the orchestrator and every reasoning engine.

---

# Core Structure

The Conversation Context SHALL contain the following sections.

```

Conversation Context

├── Session
├── Active Branch
├── Active Objective
├── Intent Graph
├── Slot State
├── Conversation History
├── User State
├── Investigation State
├── Pending Commitments
├── Pending Questions
├── Active Hypotheses
├── Why Insights
├── Conversation Metrics

```

---

# Session

Tracks conversation identity.

Fields

- session_id
- conversation_id
- user_id
- created_at
- updated_at
- message_count
- conversation_age

---

# Active Branch

Represents the current investigation.

Example

```

Physical Health

↓

Sleep Investigation

```

Fields

- branch
- sub_branch
- branch_status

Possible Status

- Active
- Paused
- Completed
- Abandoned

Only one branch may be Active.

---

# Active Objective

Stores today's coaching objective.

Examples

- Understand Sleep Pattern
- Investigate Burnout
- Build Morning Routine

Only one active objective is allowed.

---

# Intent Graph

Contains the resolved Intent Graph from Chapter 2.3.

Fields

- primary_intent
- secondary_intents
- relationships
- confidence

This object is replaced every user message.

---

# Slot State

Tracks every known slot.

Example

```

sleep_hours

duration

stress_level

exercise_frequency

```

Each slot SHALL contain

- value
- confidence
- source
- timestamp

Slots remain mutable until confidence is high.

---

# Conversation History

Stores recent interaction history.

Purpose

Support immediate reasoning.

History SHALL NOT replace Memory.

Recommended Window

Last 20–50 messages.

---

# User State

Represents the user's current conversational condition.

Fields

- emotional_state
- engagement_level
- openness
- conversation_pace
- trust_estimate
- frustration_level

This state is dynamic.

---

# Investigation State

Tracks progress within the current branch.

Fields

Known

Unknown

Pending

Completed

The Question Planner SHALL consume this state.

---

# Pending Commitments

Stores promises made during the conversation.

Examples

"I'll sleep earlier."

"I'll go for a walk."

Commitments remain active until

- completed
- cancelled
- expired

---

# Pending Questions

Tracks unanswered AI questions.

Example

AI

"When did this begin?"

User changes topic.

Pending Question remains.

It may be resumed later.

---

# Active Hypotheses

Stores hypotheses currently under investigation.

Example

Work Stress

↓

Poor Sleep

↓

Low Energy

Each hypothesis SHALL include

- confidence
- supporting evidence
- conflicting evidence

---

# Why Insights

Stores active explanations generated by the Why Engine.

Example

Low Sleep

↓

Reduced Focus

↓

Reduced Productivity

These insights influence Question Planning.

---

# Conversation Metrics

Tracks conversation quality.

Fields

questions_asked

insights_given

recommendations_given

reflections_given

clarifications

branch_switches

interruptions

loop_count

These metrics SHALL reset each conversation.

---

# Context Update Rules

Every user message SHALL update the Conversation Context in this order.

```

Receive Message

↓

Resolve Intent

↓

Update Intent Graph

↓

Update Slots

↓

Update User State

↓

Update Investigation

↓

Update Metrics

↓

Update Pending Items

↓

Generate Response

```

This order MUST remain consistent.

---

# Read Permissions

Different components consume different parts of the context.

| Component | Reads |
|-----------|-------|
| Branch Manager | Active Branch |
| Slot Resolver | Slot State |
| Question Planner | Investigation State |
| Why Engine | Active Hypotheses + Slots |
| Memory Engine | Conversation Summary |
| Objective Engine | Active Objective |
| AI Judge | Entire Context |

This minimizes unnecessary coupling.

---

# Write Permissions

Only the Adaptive Conversation Orchestrator may modify the CCM.

Other engines return structured outputs.

The orchestrator applies updates.

This prevents conflicting state mutations.

---

# Context Persistence Rules

At conversation end

Persist

✓ New memories

✓ Confirmed commitments

✓ Updated preferences

✓ Completed goals

Do NOT persist

✗ Temporary emotions

✗ Low-confidence hypotheses

✗ Pending questions

✗ Active branch state

Conversation Context is ephemeral.

Memory is permanent.

---

# Failure Modes

The orchestrator SHALL detect

- missing active branch
- duplicate objectives
- orphan hypotheses
- invalid slot values
- conflicting context updates
- stale pending questions
- invalid branch status

These SHALL generate diagnostics.

---

# Acceptance Criteria

The CCM is considered complete when

✓ Every engine reads the same context.

✓ Only one source of truth exists.

✓ Context survives throughout the conversation.

✓ Memory remains separate from context.

✓ Branches resume correctly.

✓ Pending questions survive interruptions.

✓ Slot updates remain consistent.

✓ Conversation loops cannot occur because of inconsistent state.

---

# Architecture Decision Record

## ADR-005

Decision

Introduce a centralized Conversation Context Model shared by all orchestration components.

Status

Accepted

Reason

Multiple independent state representations create inconsistent behavior.

A single canonical context model guarantees deterministic orchestration while allowing reasoning engines to remain independent.



---

# Chapter 2.7 – Conversation Lifecycle & State Transitions

---

# Purpose

The Conversation Lifecycle defines the stages through which every conversation progresses.

The Adaptive Conversation Orchestrator SHALL treat conversations as evolving investigations rather than isolated exchanges.

The lifecycle ensures that conversations begin naturally, maintain context, recover from interruptions, complete investigations, and end gracefully.

This chapter defines the legal lifecycle states, allowed transitions, transition triggers, and recovery behavior.

---

# Philosophy

A conversation is NOT a sequence of questions.

A conversation is a journey toward understanding.

Every conversation should move the AI and the user closer to a better understanding of the user's situation.

The orchestrator SHALL optimize for meaningful progress rather than message count.

---

# Lifecycle Overview

Every conversation follows the same high-level lifecycle.

```

Conversation Start

↓

Context Initialization

↓

Primary Investigation

↓

Understanding Expansion

↓

Reflection

↓

Action Planning

↓

Commitment (Optional)

↓

Conversation Closure

↓

Knowledge Persistence

↓

Conversation End

```

A conversation MAY revisit earlier stages if new information emerges.

---

# Lifecycle States

The orchestrator recognizes the following lifecycle states.

| State | Purpose |
|--------|----------|
| Initializing | Build initial context |
| Investigating | Gather understanding |
| Exploring | Expand understanding into connected areas |
| Reflecting | Summarize and validate understanding |
| Planning | Develop next actions |
| Committing | Capture commitments |
| Closing | End conversation gracefully |
| Completed | Persist knowledge and terminate |

Only one lifecycle state SHALL be active at any time.

---

# State Definitions

## Initializing

Purpose

Create a new conversation context.

Responsibilities

- Load memory summary
- Load user profile
- Resume unfinished investigations
- Initialize metrics
- Determine conversation objective

Exit Criteria

Conversation objective established.

---

## Investigating

Purpose

Reduce uncertainty.

Characteristics

- ask targeted questions
- collect missing slots
- validate assumptions
- avoid recommendations

Exit Criteria

Sufficient understanding achieved.

---

## Exploring

Purpose

Expand understanding.

Example

User reports

Poor Sleep

↓

Explore

Stress

Routine

Environment

Habits

The orchestrator SHALL avoid exploring unrelated topics.

---

## Reflecting

Purpose

Demonstrate understanding.

Examples

"I've noticed..."

"It sounds like..."

"So far we've discovered..."

Reflection SHOULD occur before recommendations.

---

## Planning

Purpose

Translate understanding into action.

Planning SHALL

- propose realistic actions
- align with user goals
- consider user constraints

Planning SHALL NOT introduce unrelated advice.

---

## Committing

Purpose

Capture user commitments.

Examples

"I'll sleep before 11."

"I'll walk tomorrow morning."

Every commitment SHALL include

- action
- confidence
- follow-up date (if applicable)

---

## Closing

Purpose

Finish naturally.

The AI SHOULD

- summarize progress
- reinforce positive effort
- remind of commitments (if any)

The AI SHALL NOT reopen investigations during closing.

---

## Completed

Purpose

Persist conversation outcomes.

Persist

✓ confirmed memories

✓ commitments

✓ updated preferences

✓ completed objectives

Discard

✗ temporary reasoning

✗ pending clarifications

✗ temporary hypotheses

---

# State Transition Rules

The following transitions are legal.

```

Initializing

↓

Investigating

↓

Exploring

↓

Reflecting

↓

Planning

↓

Committing

↓

Closing

↓

Completed

```

The following backward transitions are allowed.

```

Planning

↓

Investigating

```

Reason

New uncertainty discovered.

---

```

Reflecting

↓

Investigating

```

Reason

User corrects AI understanding.

---

```

Closing

↓

Investigating

```

Reason

User introduces significant new concern.

---

# Illegal Transitions

The orchestrator SHALL reject

Completed

↓

Investigating

Reason

Conversation already terminated.

---

Planning

↓

Initializing

Reason

Conversation already exists.

---

Closing

↓

Exploring

Reason

New investigations require explicit reopening.

---

# Transition Triggers

| Trigger | Transition |
|----------|------------|
| User provides new concern | Investigating |
| Investigation complete | Reflecting |
| Reflection accepted | Planning |
| User agrees to action | Committing |
| User ends conversation | Closing |
| Commitments persisted | Completed |

---

# Interruption Handling

Users may interrupt any lifecycle stage.

Example

Current

Planning

User

"Actually I forgot to mention I've been drinking a lot of coffee."

Expected

Planning

↓

Investigating

↓

Update understanding

↓

Return to Planning

Progress SHALL NOT be lost.

---

# Pause & Resume

The orchestrator SHALL support paused investigations.

Paused investigations SHALL retain

- collected slots
- active hypotheses
- pending questions
- objective

Upon resume

The conversation SHALL continue from the pause point.

The AI SHALL NOT restart the investigation.

---

# Timeout Recovery

If the conversation pauses for an extended period

Example

Several days

Upon return

The orchestrator SHALL

- summarize previous discussion
- ask whether the user wishes to continue
- restore conversation context

The AI SHALL NOT assume continuation.

---

# Branch Completion

A branch is considered complete only when

- required slots collected
- primary objective achieved
- recommendations delivered (if appropriate)
- user acknowledges completion

Completed branches SHALL remain closed unless explicitly reopened.

---

# Conversation Completion Criteria

A conversation is complete when

One or more of the following occur

✓ objective achieved

✓ user leaves

✓ user requests end

✓ crisis protocol activated

✓ human handoff initiated

---

# Lifecycle Metrics

Track

- investigation duration
- reflection frequency
- planning frequency
- commitment rate
- completion rate
- interruption rate
- branch completion rate
- abandoned investigations

These metrics SHALL support continuous evaluation.

---

# Failure Modes

Detect

- endless investigation
- skipped reflection
- recommendations before understanding
- unfinished commitments
- abandoned active branches
- repeated conversation restarts

These SHALL generate diagnostics.

---

# Acceptance Criteria

The lifecycle implementation is complete when

✓ conversations progress naturally

✓ interruptions preserve progress

✓ recommendations occur after understanding

✓ completed branches remain closed

✓ paused investigations resume correctly

✓ conversations terminate cleanly

✓ commitments persist correctly

---

# Architecture Decision Record

## ADR-006

Decision

Conversation orchestration SHALL follow a deterministic lifecycle rather than a simple message-response loop.

Status

Accepted

Reason

Meaningful coaching requires structured progression from understanding to action.

A lifecycle model prevents premature advice, repeated investigations, and fragmented conversations while preserving flexibility through controlled state transitions.


---

# Chapter 3 – Branch Intelligence

---

# Purpose

Branch Intelligence is responsible for organizing conversations into structured investigations.

Unlike traditional chatbot state machines, Branch Intelligence does not track UI navigation.

Instead, it manages the lifecycle of user investigations.

A branch represents an active area of exploration.

Examples

- Sleep
- Burnout
- Career
- Relationships
- Anxiety
- Exercise

The purpose of Branch Intelligence is to ensure that every investigation remains focused, adaptive, recoverable, and deterministic.

---

# Design Philosophy

Traditional chatbots think

Question

↓

Answer

↓

Next Question

Branch Intelligence thinks

Investigation

↓

Understanding

↓

Progress

↓

Completion

Questions are simply tools.

The investigation is the true unit of work.

---

# Core Principles

The Branch Manager SHALL

- maintain only one active investigation
- preserve unfinished investigations
- prevent loops
- support interruptions
- support nested investigations
- support deterministic recovery

The Branch Manager SHALL NOT

- generate responses
- store memory
- ask questions
- make recommendations

---

# Definition

A Branch represents a focused investigation into one domain of the user's life.

Examples

Physical Health

↓

Sleep

↓

Sleep Quality

OR

Career

↓

Burnout

↓

Workload

A branch exists until its objective has been completed or intentionally abandoned.

---

# Branch Hierarchy

The orchestrator SHALL organize branches hierarchically.

```

Root

├── Physical Health

│ ├── Sleep

│ ├── Energy

│ ├── Exercise

│ └── Nutrition

│

├── Mental Wellness

│ ├── Anxiety

│ ├── Burnout

│ ├── Stress

│ └── Mood

│

├── Productivity

│ ├── Focus

│ ├── Motivation

│ ├── Planning

│ └── Habits

│

├── Relationships

│ ├── Partner

│ ├── Friends

│ ├── Family

│ └── Social

│

├── Career

│ ├── Workload

│ ├── Job Satisfaction

│ ├── Career Growth

│ └── Financial Stress

```

The hierarchy SHALL be configurable.

---

# Branch States

Each branch SHALL exist in exactly one state.

| State | Description |
|---------|-------------|
| Active | Current investigation |
| Paused | Temporarily interrupted |
| Completed | Finished successfully |
| Abandoned | User chose not to continue |
| Archived | Long-term completed investigation |

---

# Active Branch Rule

The orchestrator SHALL maintain exactly one Active Branch.

Never two.

Never zero during an investigation.

This removes ambiguity.

---

# Branch Stack

Instead of deleting unfinished branches,

the orchestrator SHALL maintain a Branch Stack.

Example

```

Sleep Investigation

↓

User changes topic

↓

Career Investigation

↓

Career Complete

↓

Resume

↓

Sleep Investigation

```

The stack preserves progress.

---

# Branch Object

Every branch SHALL contain

```json
{
    "id": "",
    "parent": "",
    "status": "Active",
    "objective": "",
    "completion": 0.45,
    "priority": 81,
    "created_at": "",
    "updated_at": "",
    "slots": [],
    "hypotheses": [],
    "pending_questions": [],
    "summary": ""
}
```

---

# Branch Progress

Progress SHALL be determined by understanding.

Not by number of questions.

Example

Wrong

```

Question 4

↓

Progress 80%

```

Correct

```

Required Knowledge

↓

Collected

↓

Understanding

↓

Progress

```

---

# Branch Completion

A branch SHALL complete only when

Required slots collected

AND

Primary hypothesis sufficiently validated

AND

Current objective satisfied

AND

User acknowledges understanding

Completion SHALL NOT depend on question count.

---

# Branch Pause

A branch SHALL pause when

- user changes topic
- crisis interrupts
- user asks unrelated question
- higher-priority investigation begins

Paused branches retain

- slots
- hypotheses
- pending questions
- objective
- progress

Nothing is lost.

---

# Branch Resume

When a paused branch resumes

the AI SHALL continue naturally.

Example

Bad

```

Let's start over.

```

Correct

```

Earlier you mentioned your sleep had been poor for about two weeks.

Before we switched topics, we were exploring whether stress might be contributing.

Can we continue from there?

```

---

# Branch Abandonment

A branch becomes abandoned only if

- user explicitly stops
- user rejects investigation
- investigation becomes irrelevant

Abandonment SHALL NOT delete information.

---

# Branch Priority

Every branch SHALL maintain a priority score.

Priority is influenced by

- user urgency
- emotional impact
- coaching objective
- confidence
- crisis level
- investigation progress

Higher priority branches interrupt lower priority ones.

---

# Nested Investigations

Example

Burnout Investigation

↓

Sleep Investigation

↓

Caffeine Investigation

These SHALL exist as nested branches.

Completion returns naturally.

---

# Cross-Branch Insights

Branches SHALL communicate.

Example

Sleep

↓

Energy

↓

Productivity

↓

Mood

The Why Engine SHALL consume these relationships.

---

# Branch Switching Rules

The orchestrator SHALL switch branches ONLY if

✓ User explicitly requests

✓ Crisis detected

✓ Current branch completed

✓ Branch abandoned

Secondary information SHALL NOT trigger switching.

---

# Illegal Branch Switching

The following transitions are forbidden

Energy

↓

Work

↓

Energy

↓

Work

(loop)

The Branch Manager SHALL reject oscillating transitions.

---

# Root Protection

The Root menu SHALL only appear when

- no active branch exists
- onboarding begins
- user explicitly requests category selection

The Root SHALL NEVER appear during an active investigation.

This rule eliminates the looping behavior observed in previous implementations.

---

# Branch Recovery

If the conversation resumes after interruption

The orchestrator SHALL

Load Branch

↓

Restore Objective

↓

Restore Slots

↓

Restore Pending Questions

↓

Continue

No investigation restarts.

---

# Failure Modes

Detect

- branch loops
- duplicate active branches
- orphan branches
- missing objectives
- endless investigations
- completed branch reopening
- invalid parent-child relationships

Generate diagnostics.

---

# Acceptance Criteria

Implementation is complete when

✓ Only one active branch exists.

✓ Paused investigations resume naturally.

✓ Completed branches remain closed.

✓ Root never reappears unnecessarily.

✓ Branch loops cannot occur.

✓ Nested investigations function correctly.

✓ Cross-branch reasoning works.

✓ Understanding—not question count—determines progress.

---

# Architecture Decision Record

## ADR-007

Decision

Replace state-driven conversation flow with investigation-driven branch management.

Status

Accepted

Reason

Users think in problems, not screens.

Managing investigations instead of UI states creates conversations that are resilient to interruptions, free-text input, and long-term coaching while eliminating navigation loops.



---

# Chapter 4 – Knowledge Model & Slot Intelligence

---

# Purpose

The Knowledge Model defines **what the AI knows, how certain it is, how knowledge evolves over time, and what information is still missing.**

Unlike traditional conversational systems that simply collect answers to predefined questions, the Adaptive Conversation Orchestrator maintains a living model of the user's world.

Every user message either

- creates knowledge,
- strengthens knowledge,
- weakens knowledge,
- contradicts knowledge,
- or creates new unknowns.

The Knowledge Model is the foundation for every future coaching decision.

---

# Philosophy

The AI should never think

"I asked Question 7."

Instead it should think

"I now understand 82% of this user's sleep habits."

Knowledge—not conversation—is the primary state of the system.

---

# Core Principles

The Knowledge Model SHALL

- represent facts
- represent uncertainty
- represent beliefs
- represent unknowns
- support contradictions
- evolve continuously
- remain explainable

The Knowledge Model SHALL NOT

- store conversation history
- replace long-term memory
- generate recommendations

---

# Knowledge Hierarchy

Every piece of user knowledge belongs to one of four levels.

```

Knowledge

├── Facts
├── Beliefs
├── Unknowns
└── Hypotheses

```

---

# Facts

Facts are information confirmed with high confidence.

Examples

- Sleeps 6 hours
- Works remotely
- Drinks coffee daily
- Goes to gym twice weekly

Facts SHALL contain

- value
- confidence
- evidence
- timestamp
- source

Facts MAY change over time.

---

# Beliefs

Beliefs are interpretations.

Examples

- Work stress reduces sleep quality.
- Morning exercise improves focus.
- Late caffeine causes insomnia.

Beliefs always include confidence.

Beliefs may be promoted to facts after repeated confirmation.

---

# Unknowns

Unknowns are not empty values.

Unknowns represent information the orchestrator intentionally wants to learn.

Example

Known

Sleep Hours

Unknown

Bedtime

Unknown

Sleep Quality

Unknowns drive investigations.

---

# Hypotheses

Hypotheses explain observations.

Example

Poor Sleep

↓

Low Energy

↓

Reduced Productivity

Hypotheses are consumed by the Why Engine.

---

# Knowledge Domains

Knowledge SHALL be organized by domains.

```

Health

Lifestyle

Career

Relationships

Mindset

Habits

Environment

Goals

Identity

```

Every branch references one or more domains.

---

# Slot Definition

A Slot is the smallest measurable unit of knowledge.

Example

```

sleep_hours

```

Example

```

exercise_frequency

```

Example

```

stress_level

```

Slots are NOT questions.

Multiple questions may populate one slot.

---

# Slot Object

Every slot SHALL contain

```json
{
  "name": "",
  "value": null,
  "confidence": 0,
  "importance": 0,
  "status": "unknown",
  "evidence": [],
  "source": "",
  "updated_at": "",
  "last_confirmed_at": ""
}
```

---

# Slot Status

Every slot exists in exactly one state.

| Status | Description |
|---------|-------------|
| Unknown | No information |
| Partial | Incomplete understanding |
| Inferred | AI inferred |
| Confirmed | User confirmed |
| Contradicted | Conflicting evidence |
| Expired | Needs reconfirmation |

---

# Slot Confidence

Confidence SHALL always be independent of value.

Example

```

Sleep Hours

5

Confidence

98%

```

Example

```

Sleep Hours

5

Confidence

42%

```

Same value.

Different certainty.

---

# Slot Importance

Not every slot matters equally.

Importance determines investigation priority.

Examples

| Slot | Importance |
|-------|-----------:|
| suicidal_risk | 100 |
| sleep_hours | 95 |
| stress_level | 90 |
| favorite_music | 10 |

Question Planner SHALL use importance.

---

# Slot Dependencies

Some slots depend on others.

Example

```

Sleep Investigation

↓

sleep_hours

↓

sleep_quality

↓

bedtime

↓

wake_time

```

The orchestrator SHALL understand dependencies before selecting questions.

---

# Slot Evidence

Every slot SHALL maintain evidence.

Example

```

Sleep Hours

Evidence

Conversation #4

Conversation #8

Wearable Device

Weekly Check-in

```

Confidence increases with evidence.

---

# Contradictions

Example

Previous

```

Sleep

8 hours

```

Current

```

Sleep

5 hours

```

Result

```

Contradicted

↓

Ask Confirmation

↓

Update

```

Never overwrite silently.

---

# Slot Aging

Knowledge becomes stale.

Example

Weight

Last Updated

18 months ago

Status

Expired

The orchestrator SHOULD naturally refresh outdated information.

---

# Slot Decay

Confidence gradually decreases when information has not been confirmed for long periods.

Example

```

90%

↓

84%

↓

77%

↓

Needs Confirmation

```

This prevents stale assumptions.

---

# Slot Inheritance

Parent branches share slots.

Example

Physical Health

↓

Sleep

↓

sleep_hours

↓

Energy Investigation

may reuse

sleep_hours

No duplicate collection.

---

# Cross-Branch Slot Sharing

Example

Stress Level

may influence

- Sleep
- Productivity
- Relationships
- Burnout

One slot.

Many investigations.

---

# Required vs Optional Slots

Every investigation SHALL define

Required Slots

Optional Slots

Recommendations SHALL NOT occur until required slots reach sufficient confidence.

---

# Slot Completion

A slot becomes complete when

- value exists
- confidence exceeds threshold
- contradiction resolved

---

# Slot Quality Score

Every slot receives a quality score.

```

Quality

=

Confidence

×

Evidence

×

Recency

```

Low-quality slots SHOULD be revisited.

---

# Knowledge Completeness

Every investigation SHALL calculate

```

Known Knowledge

/

Required Knowledge

```

Example

```

82%

```

This replaces question-count progress.

---

# Failure Modes

Detect

- duplicate slots
- conflicting values
- stale slots
- circular dependencies
- missing required slots
- invalid confidence

Generate diagnostics.

---

# Acceptance Criteria

Implementation is complete when

✓ Duplicate questions disappear.

✓ Slots survive branch changes.

✓ Contradictions are resolved.

✓ Slot confidence evolves.

✓ Knowledge completeness drives investigations.

✓ Branches reuse knowledge.

✓ Recommendations require sufficient knowledge.

---

# Architecture Decision Record

## ADR-008

Decision

The orchestrator SHALL reason over structured knowledge rather than completed questions.

Status

Accepted

Reason

Questions are temporary.

Knowledge persists.

A knowledge-driven architecture allows adaptive conversations, better reasoning, and long-term coaching without repetitive questioning.


---

# Chapter 5 – Conversation Planner

---

# Purpose

The Conversation Planner is the central decision-making component of the Adaptive Conversation Orchestrator.

It determines the highest-value conversational action for every user message.

The planner SHALL NOT assume that asking another question is always the correct action.

Instead, it continuously evaluates the current understanding, coaching objective, user state, and conversation quality before selecting the next conversational move.

The Conversation Planner is responsible for deciding

**What should happen next?**

The LLM is responsible only for expressing that decision naturally.

---

# Philosophy

Traditional chatbot

↓

Question

↓

Answer

↓

Question

Adaptive Conversation Planner

↓

Understand

↓

Reason

↓

Choose Best Action

↓

Generate Response

Questions are only one possible action.

---

# Responsibilities

The planner SHALL

- decide the next conversational action
- minimize unnecessary questions
- maximize conversational value
- balance curiosity with usefulness
- coordinate every reasoning engine

The planner SHALL NOT

- classify intent
- manage memory
- store slots
- generate language

---

# Inputs

The planner consumes

- Conversation Context
- Intent Graph
- Active Branch
- Knowledge Model
- User State
- Why Insights
- Active Hypotheses
- Conversation Metrics
- Coaching Objective

---

# Outputs

The planner returns

```json
{
  "next_action": "",
  "reason": "",
  "priority": 0,
  "confidence": 0,
  "required_context": [],
  "expected_outcome": ""
}
```

The LLM receives this object.

---

# Conversation Actions

The planner may choose exactly ONE primary action.

Supported actions

| Action | Purpose |
|---------|----------|
| Ask | Reduce uncertainty |
| Reflect | Demonstrate understanding |
| Validate | Acknowledge emotion |
| Encourage | Reinforce effort |
| Celebrate | Strengthen success |
| Clarify | Resolve ambiguity |
| Recommend | Suggest action |
| Challenge | Encourage growth |
| Summarize | Consolidate understanding |
| Pause | Reduce cognitive load |

Every response begins with an action.

Not with text.

---

# Action Selection Algorithm

The planner evaluates

1.

Current objective

↓

2.

Knowledge completeness

↓

3.

Conversation fatigue

↓

4.

User engagement

↓

5.

Information gain

↓

6.

Recent actions

↓

7.

Conversation value

↓

Select Best Action

---

# Information Gain

Every unknown piece of knowledge receives a score.

Higher score

↓

Higher priority

The planner SHOULD prefer questions that reduce the greatest uncertainty.

---

# Conversation Value

Every action produces value.

Examples

Question

Knowledge

Reflection

Trust

Celebration

Motivation

Recommendation

Behavior Change

The planner SHALL maximize cumulative value.

---

# Curiosity Budget

The AI SHALL NOT ask unlimited questions.

Track

Questions Since Last Value

Example

Questions

3

↓

Planner MUST provide

Reflection

Insight

Recommendation

or

Encouragement

before asking again.

---

# Question Cost

Questions have cost.

Cost increases when

- repeated
- emotionally difficult
- low information gain
- user frustration
- conversation fatigue

Planner SHOULD avoid expensive questions unless necessary.

---

# User Energy

Estimate

High

Medium

Low

High Energy

↓

Long exploration

Low Energy

↓

Short responses

↓

More value

↓

Fewer questions

---

# Conversation Pace

Three pacing modes

Fast

Medium

Deep

Planner selects automatically.

---

# Reflection Trigger

Planner SHOULD generate reflection when

- understanding reaches threshold
- user expresses strong emotion
- investigation completes
- contradiction resolved

Reflection strengthens trust.

---

# Recommendation Trigger

Recommendations SHALL only occur when

- sufficient understanding exists
- required slots complete
- confidence exceeds threshold

Never recommend too early.

---

# Opportunity Detection

Planner SHALL detect positive moments.

Examples

"I slept well."

"I exercised."

"I finally relaxed."

Planner SHOULD

Celebrate

↓

Investigate Success

↓

Strengthen Habit

Not simply acknowledge.

---

# Action Diversity

Avoid repetitive conversational patterns.

Track

- Questions
- Reflections
- Encouragement
- Recommendations
- Celebrations

Planner SHOULD diversify.

---

# Recovery Mode

If

Loop detected

OR

Repeated clarification

OR

User frustration

Planner SHALL leave investigative mode.

Choose

Reflection

or

Summary

before continuing.

---

# Decision Table

| Situation | Preferred Action |
|-----------|-----------------|
| High uncertainty | Ask |
| High emotion | Validate |
| New understanding | Reflect |
| Success | Celebrate |
| Commitment | Encourage |
| Confusion | Clarify |
| Complete understanding | Recommend |
| Long investigation | Summarize |
| Fatigue | Pause |

---

# Acceptance Criteria

Implementation is complete when

✓ Questions become optional.

✓ Every response begins with an intentional action.

✓ Curiosity remains balanced.

✓ Reflection appears naturally.

✓ Recommendations occur only after understanding.

✓ Users receive value throughout conversations.

✓ Repetitive questioning disappears.

---

# Architecture Decision Record

## ADR-009

Decision

Replace Question Planning with Conversation Planning.

Status

Accepted.

Reason

The objective of a coaching conversation is not to maximize questions.

It is to maximize user understanding, trust, and behavior change.

Questions are only one of many conversational actions.


---

# Chapter 6 – Conversation Strategy & Value Optimization

---

# Purpose

The Conversation Strategy Layer governs **how conversations create value over time.**

Its purpose is to ensure that every conversation feels balanced, useful, respectful of the user's attention, and capable of producing meaningful behavior change.

Unlike the Conversation Planner, which decides the next action, the Strategy Layer decides **how much investigation is appropriate, when value should be delivered, and when the conversation should change pace.**

The Strategy Layer exists to maximize long-term trust rather than short-term information collection.

---

# Philosophy

The AI is not rewarded for asking questions.

The AI is rewarded for helping the user.

More questions do NOT mean better coaching.

More understanding does NOT require longer conversations.

Every conversational decision should maximize

- understanding
- trust
- usefulness
- behavior change

while minimizing

- fatigue
- repetition
- cognitive load
- frustration

---

# Core Principles

The Strategy Layer SHALL

- balance curiosity with value
- prevent interrogation
- adapt conversation depth
- optimize cognitive load
- maximize long-term engagement
- preserve user trust

The Strategy Layer SHALL NOT

- classify intent
- generate responses
- update memory
- select branches

---

# Conversation Value

Every AI response MUST deliver at least one type of value.

Supported value categories

| Value | Description |
|--------|-------------|
| Understanding | Learns something meaningful |
| Reflection | Helps the user understand themselves |
| Validation | Makes the user feel heard |
| Insight | Reveals a useful pattern |
| Recommendation | Suggests an action |
| Motivation | Increases confidence or momentum |
| Accountability | Reinforces commitments |
| Celebration | Reinforces success |

If a response provides none of these,

the planner SHOULD reconsider the action.

---

# Curiosity Budget

Curiosity is limited.

The orchestrator SHALL track

Questions Asked Since Last Value

Example

Question

↓

Question

↓

Question

↓

Reflection

Question

↓

Insight

Question

↓

Recommendation

The AI SHALL NOT continuously ask questions.

---

# Maximum Investigation Window

Default guidance

| Investigation Depth | Maximum Consecutive Questions |
|---------------------|-------------------------------:|
| Fast | 2 |
| Standard | 3 |
| Deep Coaching | 5 |

After the limit,

the AI MUST provide value before asking again.

---

# Cognitive Load

The orchestrator SHALL estimate cognitive load.

Signals include

- very short replies
- delayed replies
- repeated uncertainty
- emotional overwhelm
- frustration
- multiple unanswered questions

Load Levels

| Level | Strategy |
|--------|----------|
| Low | Explore deeper |
| Medium | Alternate questions with reflections |
| High | Reduce questions, summarize, validate |

---

# Conversation Energy

Estimate user conversational energy.

Levels

High

Medium

Low

High Energy

- longer responses
- more exploration
- deeper coaching

Low Energy

- concise questions
- immediate value
- shorter recommendations

The AI adapts naturally.

---

# Pacing Modes

The Strategy Layer SHALL choose one pacing mode.

| Mode | Purpose |
|------|----------|
| Discovery | Learn quickly |
| Coaching | Balance learning and guidance |
| Reflection | Help consolidate understanding |
| Planning | Convert understanding into action |
| Maintenance | Check in with minimal effort |

Pacing MAY change during the conversation.

---

# Information vs Value Ratio

Track

Information Collected

versus

Value Delivered

Example

```
Information

████████

Value

██
```

Bad.

Example

```
Information

██████

Value

██████
```

Healthy.

The ratio SHOULD remain balanced.

---

# Opportunity Detection

The Strategy Layer SHALL detect opportunities to reinforce positive behavior.

Examples

"I slept well."

"I completed my workout."

"I finally spoke to my manager."

Instead of moving on,

the AI SHOULD

Celebrate

↓

Understand why success happened

↓

Help repeat it

Positive moments are coaching opportunities.

---

# Resistance Detection

Indicators

- repeated "I don't know"
- changing topic
- avoiding questions
- rejecting suggestions
- sarcasm
- irritation

When resistance increases,

the AI SHOULD

Reduce pressure

Increase empathy

Ask simpler questions

Offer reflection instead of advice

---

# Silence Strategy

Silence has meaning.

If the user sends

"..."

or takes unusually long to respond,

the AI SHOULD avoid repeating the same question.

Preferred actions

- gentle check-in
- acknowledge difficulty
- simplify investigation

---

# Recommendation Timing

Recommendations SHALL only occur when

Required Knowledge

AND

User Readiness

AND

Conversation Timing

all meet acceptable thresholds.

Otherwise

Continue coaching.

---

# Ending Well

The final moments of a conversation strongly influence whether the user returns.

The AI SHOULD end conversations with one or more of

- summary
- encouragement
- commitment reminder
- reflection
- small next step

The AI SHOULD NOT end with only

"Anything else?"

---

# Long-Term Strategy

Across multiple conversations,

the orchestrator SHOULD

- reduce repeated investigations
- increase personalization
- identify recurring themes
- recognize progress
- reinforce successful habits
- retire ineffective coaching approaches

---

# Conversation Health Metrics

Track

- Question Density
- Reflection Frequency
- Insight Frequency
- Recommendation Acceptance
- User Engagement
- Conversation Completion
- Return Rate
- Average Cognitive Load
- Average Curiosity Budget
- Value Delivered

These metrics SHALL support continuous optimization.

---

# Failure Modes

Detect

- interrogation loops
- recommendation overload
- low-value conversations
- excessive questioning
- repetitive reflections
- cognitive overload
- poor pacing

Generate diagnostics for every occurrence.

---

# Acceptance Criteria

Implementation is complete when

✓ Users receive value throughout the conversation.

✓ Questions remain balanced.

✓ Recommendations occur at the right time.

✓ Positive moments are reinforced.

✓ Conversation pace adapts naturally.

✓ Users are not overwhelmed.

✓ The AI optimizes for long-term engagement instead of maximum conversation length.

---

# Architecture Decision Record

## ADR-010

Decision

Introduce a dedicated Conversation Strategy Layer responsible for pacing, curiosity management, value delivery, and long-term coaching quality.

Status

Accepted.

Reason

Conversation quality depends not only on choosing the correct action, but also on choosing the correct intensity, timing, and pacing.

Separating strategy from planning allows the orchestrator to produce conversations that feel adaptive rather than procedural.


---

# Chapter 7 – Adaptive Coaching Engine (ACE)

---

# Purpose

The Adaptive Coaching Engine (ACE) is responsible for selecting the most effective coaching style for an individual user.

Unlike traditional assistants that generate responses using one consistent personality, the Adaptive Coaching Engine continuously learns how a specific user responds to different coaching strategies.

Its objective is not simply to personalize language.

Its objective is to maximize long-term behavior change.

The same problem presented by two different users may result in two different coaching approaches.

---

# Philosophy

The AI does not ask

"What advice should I give?"

Instead it asks

"What coaching approach has historically helped this user the most?"

Coaching becomes adaptive rather than generic.

---

# Responsibilities

The Adaptive Coaching Engine SHALL

- learn user preferences
- learn coaching effectiveness
- adapt coaching intensity
- adapt challenge level
- adapt emotional support
- adapt pacing
- learn from outcomes

The Adaptive Coaching Engine SHALL NOT

- classify intent
- manage memory
- determine conversation branches
- generate natural language

---

# Coaching Profile

Every user SHALL maintain a Coaching Profile.

Example

```json
{
  "preferred_style": "reflective",
  "challenge_level": "medium",
  "encouragement_frequency": "high",
  "planning_preference": "small_steps",
  "reflection_preference": "high",
  "directness": "medium",
  "accountability": "weekly"
}
```

This profile evolves over time.

---

# Coaching Styles

The engine SHALL support multiple coaching styles.

| Style | Description |
|---------|-------------|
| Reflective | Uses questions and insights |
| Directive | Gives clear next steps |
| Collaborative | Plans together |
| Supportive | Prioritizes empathy |
| Challenging | Pushes growth respectfully |
| Analytical | Explains patterns using evidence |
| Accountability | Focuses on commitments |
| Exploratory | Encourages self-discovery |

One style is primary.

Others may support it.

---

# Coaching Dimensions

Instead of selecting one style,

ACE evaluates multiple dimensions.

Examples

Challenge

```
Low ───────────── High
```

Empathy

```
Low ───────────── High
```

Directness

```
Low ───────────── High
```

Reflection

```
Low ───────────── High
```

Planning

```
Low ───────────── High
```

Celebration

```
Low ───────────── High
```

Each user receives a unique coaching fingerprint.

---

# Coaching Fingerprint

The Coaching Fingerprint represents how the user responds to coaching.

Example

```
Reflection

██████████

Challenge

██████

Planning

████████

Validation

██████████

Accountability

████

```

No two users should have identical fingerprints after extended usage.

---

# Adaptation Signals

ACE continuously observes

- recommendation acceptance
- commitment completion
- conversation engagement
- response length
- emotional shifts
- topic avoidance
- conversation return frequency

Every signal updates the Coaching Profile.

---

# Recommendation Learning

Every recommendation SHALL receive an outcome.

Example

Recommendation

Sleep Earlier

↓

Completed

↓

Increase confidence

Recommendation

Meditation

↓

Rejected

↓

Reduce future frequency

The AI learns what works.

---

# Challenge Calibration

Not every user benefits from challenge.

Rules

If

High frustration

↓

Reduce challenge

If

High motivation

↓

Increase challenge

If

Repeated success

↓

Offer stretch goals

Challenge should adapt naturally.

---

# Emotional Calibration

The AI SHALL adjust emotional tone based on user state.

Examples

High distress

↓

Validation first

↓

Exploration second

↓

Planning last

High confidence

↓

Planning

↓

Challenge

↓

Growth

Tone follows emotional readiness.

---

# Habit Reinforcement

Positive behaviors SHALL be reinforced.

Example

User

"I exercised three times."

Planner

↓

Celebrate

↓

Identify success factors

↓

Encourage repetition

Success should receive as much attention as problems.

---

# Resistance Handling

Indicators

- repeated avoidance
- topic changes
- sarcasm
- dismissive responses
- rejected advice

Response

↓

Reduce pressure

↓

Increase curiosity

↓

Avoid forcing action

The AI coaches with the user,

not against them.

---

# Momentum Detection

ACE SHALL detect momentum.

Examples

Increasing

- optimism
- consistency
- motivation

Planner SHOULD

Introduce slightly larger goals.

Momentum is an opportunity.

---

# Regression Detection

Detect

- worsening sleep
- declining engagement
- repeated failures
- reduced motivation

Planner SHOULD

Simplify actions

Increase support

Reduce cognitive load

---

# Coaching Memory

The Adaptive Coaching Engine SHALL remember

- what coaching styles worked
- which recommendations succeeded
- preferred communication patterns
- successful intervention types
- motivation triggers

This memory is separate from factual memory.

The AI remembers

how to coach,

not only

what happened.

---

# Long-Term Adaptation

The engine SHALL gradually improve over time.

Examples

Conversation 1

Generic Coaching

↓

Conversation 20

Personalized Coaching

↓

Conversation 100

Predictive Coaching

The AI should become noticeably better as the relationship develops.

---

# Anti-Patterns

The engine SHALL avoid

- repeating identical encouragement
- recommending rejected strategies repeatedly
- overusing one coaching style
- excessive empathy without action
- excessive challenge without trust

---

# Success Metrics

Track

- recommendation acceptance
- commitment completion
- weekly engagement
- return frequency
- coaching satisfaction
- user progress
- habit consistency
- behavior change

These metrics evaluate coaching effectiveness.

---

# Acceptance Criteria

Implementation is complete when

✓ Different users receive different coaching styles.

✓ Coaching evolves over time.

✓ Successful interventions become more common.

✓ Failed interventions become less common.

✓ Emotional tone adapts naturally.

✓ Recommendations become increasingly personalized.

✓ Coaching effectiveness improves across conversations.

---

# Architecture Decision Record

## ADR-011

Decision

Introduce an Adaptive Coaching Engine responsible for learning how each individual user responds to coaching.

Status

Accepted.

Reason

Remembering facts is insufficient for long-term coaching.

A high-quality coach remembers both the user's history and the methods that help that specific user succeed.

Separating coaching adaptation from reasoning keeps the architecture modular while enabling continuously improving personalization.


---

# Chapter 8 – Learning & Continuous Improvement Engine (LCIE)

---

# Purpose

The Learning & Continuous Improvement Engine (LCIE) transforms every completed conversation into knowledge that improves future coaching.

Unlike the Memory Engine, which remembers user facts, the LCIE evaluates coaching effectiveness.

Its purpose is to answer one question:

**"What did we learn from this conversation that should improve future conversations?"**

Every conversation should make the AI a better coach.

---

# Philosophy

Memory remembers

**What happened.**

The Learning Engine remembers

**What worked.**

The AI should continuously optimize its coaching strategy using evidence rather than assumptions.

---

# Responsibilities

The LCIE SHALL

- evaluate conversation quality
- measure coaching effectiveness
- detect recurring patterns
- identify successful interventions
- identify failed interventions
- improve future coaching strategies
- generate long-term user insights

The LCIE SHALL NOT

- generate responses
- manage active conversations
- classify intent
- update conversation context

Learning occurs after the conversation ends.

---

# Learning Pipeline

Every completed conversation SHALL execute the following pipeline.

```

Conversation Ends

↓

Conversation Summary

↓

Evaluate Outcome

↓

Measure Coaching Effectiveness

↓

Update Coaching Profile

↓

Update User Patterns

↓

Generate Insights

↓

Store Learnings

```

---

# Learning Categories

The engine SHALL learn across five dimensions.

| Category | Example |
|----------|---------|
| Behavior | Exercise consistency improved |
| Coaching | Reflection worked better than advice |
| Preferences | User prefers concise conversations |
| Motivation | Small goals increase completion |
| Patterns | Poor sleep predicts poor focus |

---

# Conversation Outcome

Each conversation SHALL receive an outcome classification.

Supported outcomes

- Productive
- Neutral
- Unfinished
- Interrupted
- High Progress
- Regression
- Crisis
- Relationship Building

This outcome influences future planning.

---

# Intervention Evaluation

Every recommendation SHALL be evaluated.

Example

Recommendation

```
Sleep before 11 PM
```

Outcome

```
Completed
```

Confidence

```
Increase
```

Future probability of recommending similar interventions increases.

---

# Failed Intervention Analysis

Example

Recommendation

```
Meditate for 30 minutes
```

Outcome

```
Rejected
```

Learning

```
Recommendation too difficult.

User prefers smaller actions.
```

Future recommendations become more realistic.

---

# Pattern Detection

The Learning Engine SHALL continuously search for repeated relationships.

Example

```
Sleep ↓

↓

Focus ↓

↓

Task Completion ↓

```

Observed

```
7 times

```

Confidence

```
98%

```

Pattern becomes available to the Why Engine.

---

# Why Engine Integration

Patterns discovered by LCIE SHALL automatically become candidate explanations for future conversations.

Example

```
Late caffeine

↓

Poor sleep

↓

Low energy

↓

Reduced productivity

```

The AI now recognizes this before the user does.

---

# Positive Pattern Learning

The AI SHALL learn from success.

Example

User

```
Completed morning walk
```

Observed Effect

```
Higher mood

Better focus

```

Future coaching SHOULD reinforce morning walks.

---

# Coaching Effectiveness

Every conversation SHALL score each coaching dimension.

Example

| Dimension | Score |
|-----------|------:|
| Reflection | 92 |
| Advice | 54 |
| Encouragement | 87 |
| Challenge | 41 |
| Accountability | 78 |

Future coaching uses these scores.

---

# User Growth Model

The engine SHALL estimate growth over time.

Examples

- Self-awareness
- Consistency
- Motivation
- Confidence
- Emotional regulation
- Habit stability

Growth trends matter more than individual conversations.

---

# Pattern Confidence

Patterns SHALL only be promoted when

- repeated multiple times
- supported by evidence
- free of contradictions

Single conversations SHALL NOT define long-term coaching.

---

# Forgotten Learnings

Old learnings may become obsolete.

Examples

- Job changed
- New routine
- Relationship changed
- Health improved

Learning confidence SHALL decay over time unless reinforced.

---

# Weekly Insight Generation

The engine SHOULD automatically generate long-term insights.

Example

> "Over the past six weeks, your focus consistently improves on days after at least seven hours of sleep."

These insights are higher value than daily summaries.

---

# Monthly Reflection

Generate

- biggest improvements
- biggest obstacles
- strongest habits
- recurring struggles
- coaching effectiveness
- recommended focus

The AI becomes a long-term coach.

---

# Learning Metrics

Track

- recommendation success rate
- commitment completion
- coaching acceptance
- pattern confidence
- behavior improvement
- habit consistency
- conversation quality
- long-term engagement

---

# Failure Modes

Detect

- false pattern detection
- insufficient evidence
- contradictory patterns
- stale learnings
- coaching drift
- over-personalization

Patterns SHALL require validation before influencing coaching.

---

# Acceptance Criteria

Implementation is complete when

✓ Every conversation improves future coaching.

✓ Successful interventions become more common.

✓ Failed interventions become less common.

✓ Long-term patterns are detected automatically.

✓ Weekly and monthly insights become increasingly personalized.

✓ Learning remains evidence-based.

---

# Architecture Decision Record

## ADR-012

Decision

Introduce a dedicated Learning & Continuous Improvement Engine responsible for evaluating coaching outcomes after every conversation.

Status

Accepted.

Reason

A coaching system that does not learn from outcomes will always provide generic advice.

Separating post-conversation learning from real-time reasoning enables continuous improvement without increasing conversation latency.


---

# Chapter 9 – Predictive Insight & Why Engine

---

# Purpose

The Predictive Insight & Why Engine is responsible for discovering meaningful relationships between user behaviors, emotional states, routines, environments, and outcomes.

Unlike analytics systems that describe what happened, the Why Engine explains why it likely happened.

Its objective is to continuously answer one question:

> "What hidden patterns in this user's life explain their current outcomes?"

The Why Engine transforms observations into explanations and explanations into coaching opportunities.

---

# Philosophy

Most wellness apps stop at reporting.

Example

"You slept 5 hours."

Better systems summarize.

"Your average sleep decreased this week."

The Why Engine goes further.

"I've reviewed your last 8 weeks.

Every time your sleep stays below 6.5 hours for at least three consecutive days, your focus drops the following day.

This has happened four times.

Sleep appears to be one of your strongest predictors of productivity."

The AI should explain patterns—not merely describe data.

---

# Responsibilities

The Why Engine SHALL

- discover behavioral relationships
- estimate causal confidence
- explain observations
- generate personalized insights
- detect recurring triggers
- identify leading indicators
- predict future outcomes
- support coaching recommendations

The Why Engine SHALL NOT

- invent causal relationships
- diagnose medical conditions
- provide certainty where evidence is weak
- overwrite factual memory

---

# Evidence-First Principle

Every insight MUST be supported by evidence.

The AI SHALL distinguish

Observed

↓

Likely

↓

Possible

↓

Unknown

Example

Observed

Sleep decreased.

Observed

Focus decreased.

Observed

Occurred together 6 times.

Conclusion

Likely relationship.

Not

Guaranteed cause.

---

# Pattern Discovery Pipeline

```

Conversation Memory

↓

Behavior History

↓

Habit History

↓

Emotional History

↓

Event Timeline

↓

Pattern Mining

↓

Evidence Ranking

↓

Confidence Calculation

↓

Insight Generation

↓

Store Candidate Pattern

```

---

# Pattern Object

Every discovered pattern SHALL contain

```json
{
  "pattern_id": "",
  "title": "",
  "observation": "",
  "possible_explanation": "",
  "confidence": 0.91,
  "evidence_count": 8,
  "first_seen": "",
  "last_seen": "",
  "supporting_events": [],
  "contradicting_events": [],
  "status": "candidate"
}
```

---

# Pattern Categories

Supported categories

| Category | Example |
|----------|---------|
| Habit Pattern | Exercise improves sleep |
| Emotional Pattern | Work stress increases anxiety |
| Behavioral Pattern | Late caffeine reduces sleep |
| Productivity Pattern | Sleep affects focus |
| Social Pattern | Family conflict affects mood |
| Recovery Pattern | Walking reduces stress |
| Motivation Pattern | Small goals improve consistency |

---

# Leading Indicators

The Why Engine SHALL distinguish

Leading Indicator

↓

Future Outcome

Example

Poor Sleep

↓

Low Energy

↓

Missed Workout

↓

Lower Mood

Poor Sleep is the leading indicator.

The AI should intervene before the outcome occurs.

---

# Lagging Indicators

Examples

Weight gain

Burnout

Poor productivity

These are consequences.

Not starting points.

The AI SHOULD search upstream.

---

# Root Cause Graph

The Why Engine SHALL represent explanations as graphs.

Example

```

Late Work

↓

Less Sleep

↓

Low Energy

↓

Poor Focus

↓

Missed Tasks

```

This graph becomes the foundation for coaching.

---

# Pattern Confidence

Confidence depends on

| Factor | Weight |
|---------|--------|
| Repetition | 30% |
| Evidence Quality | 25% |
| Time Consistency | 20% |
| Cross-source Agreement | 15% |
| Contradictions | -10% |

Patterns SHALL never be treated as facts without sufficient confidence.

---

# Pattern Promotion

States

Candidate

↓

Observed

↓

Confirmed

↓

Core Pattern

Promotion requires

- repeated evidence
- high confidence
- minimal contradiction

---

# Contradiction Handling

Example

Pattern

Coffee causes poor sleep

Later

User drinks coffee

↓

Sleep excellent

Confidence decreases.

The pattern is re-evaluated.

The AI SHALL update explanations rather than defend previous assumptions.

---

# Predictive Insights

The Why Engine SHALL estimate future outcomes.

Example

"Based on your previous patterns, there's a high chance tomorrow's focus will be lower if tonight's sleep remains under six hours."

Predictions SHALL include confidence.

Predictions SHALL never be presented as certainty.

---

# Insight Generation Rules

Insights SHALL satisfy all of the following

✓ Personalized

✓ Evidence-based

✓ Actionable

✓ Understandable

✓ Relevant

The AI SHALL avoid generic observations.

---

# Insight Timing

Insights SHOULD appear

- after meaningful evidence accumulates
- during weekly reviews
- before recommendations
- after major behavior changes
- when users ask "why"

The AI SHOULD NOT interrupt investigations with unnecessary insights.

---

# Weekly Insight Examples

Example

"I noticed something interesting.

Across the last six weeks, every time you exercised at least three times, your average mood improved within two days.

That pattern has repeated five times."

---

Example

"Your stress doesn't seem to come directly from work.

It usually increases two days after poor sleep.

Sleep may be the earlier trigger."

---

# Recommendation Integration

Every recommendation SHOULD reference an insight whenever possible.

Instead of

"Try sleeping earlier."

Say

"Because your focus has repeatedly improved after longer sleep, I think improving bedtime may have a bigger impact than increasing your work hours."

Insights justify coaching.

---

# Why Confidence

The engine SHALL expose confidence.

Example

High Confidence

"I'm confident this pattern has repeated multiple times."

Medium

"I think this may be contributing."

Low

"I've only seen this once, so I'm not confident yet."

Transparency builds trust.

---

# User Challenge

Users MAY disagree.

Example

"I don't think that's true."

The AI SHALL

- accept feedback
- reduce confidence
- gather additional evidence

The AI SHALL NOT argue.

---

# Conversation Integration

The Conversation Planner SHALL consult the Why Engine before

- recommendations
- reflections
- summaries
- weekly reports

Insights become part of normal coaching.

---

# Failure Modes

Detect

- false correlations
- insufficient evidence
- contradictory data
- stale patterns
- duplicated explanations
- explanation loops

Generate diagnostics.

---

# Acceptance Criteria

Implementation is complete when

✓ The AI explains patterns rather than listing statistics.

✓ Predictions include confidence.

✓ Insights are evidence-based.

✓ Patterns improve over time.

✓ Recommendations reference discovered relationships.

✓ Contradictions reduce confidence.

✓ Weekly insights become increasingly personalized.

---

# Architecture Decision Record

## ADR-013

Decision

Introduce a dedicated Predictive Insight & Why Engine responsible for discovering, validating, and explaining personalized behavioral patterns.

Status

Accepted.

Reason

Long-term coaching value comes from helping users understand why outcomes occur, not simply reporting what happened.

Separating explanation from conversation planning enables transparent, evidence-based coaching while avoiding unsupported conclusions.

---

# Chapter 10 – Behavioral Intervention Engine (BIE)

---

# Purpose

The Behavioral Intervention Engine (BIE) is responsible for selecting the most effective intervention for the user at a specific moment.

Unlike traditional AI systems that immediately generate advice, the Behavioral Intervention Engine evaluates multiple possible interventions and selects the one with the highest probability of creating sustainable behavior change.

Its objective is not to provide the smartest recommendation.

Its objective is to provide the recommendation most likely to be followed.

---

# Philosophy

Bad coaching asks

"What advice should I give?"

Good coaching asks

"What action is this person actually capable of completing today?"

The Behavioral Intervention Engine optimizes for action completion, not advice quality.

---

# Responsibilities

The BIE SHALL

- rank interventions
- estimate intervention success probability
- personalize recommendations
- minimize cognitive load
- avoid repeated failed interventions
- build sustainable habits

The BIE SHALL NOT

- classify intent
- generate language
- update memory
- manage branches

---

# Intervention Pipeline

Every recommendation SHALL follow this pipeline.

```

Problem

↓

Root Cause Analysis

↓

Candidate Interventions

↓

Filter Unsafe Options

↓

Estimate User Readiness

↓

Rank Interventions

↓

Select Best Intervention

↓

Generate Follow-up Plan

↓

LLM

```

---

# Intervention Object

Every intervention SHALL contain

```json
{
  "id": "",
  "title": "",
  "goal": "",
  "difficulty": 0,
  "expected_benefit": 0,
  "estimated_completion": 0,
  "confidence": 0,
  "reason": "",
  "follow_up": ""
}
```

---

# Intervention Categories

Supported intervention types

| Category | Example |
|----------|---------|
| Education | Explain a concept |
| Reflection | Ask the user to reflect |
| Awareness | Track a behavior |
| Environment | Modify surroundings |
| Habit | Introduce a routine |
| Planning | Create a plan |
| Accountability | Set a commitment |
| Recovery | Reduce pressure |
| Motivation | Reinforce progress |
| Escalation | Recommend professional support |

---

# Root Cause First

The engine SHALL prioritize interventions targeting root causes rather than symptoms.

Example

Observed

```
Low Focus
```

Root Cause

```
Poor Sleep
```

Intervention

```
Improve Sleep Routine
```

Not

```
Download another productivity app
```

---

# User Readiness

Every intervention SHALL estimate readiness.

Dimensions

- Motivation
- Available Time
- Emotional Capacity
- Habit Strength
- Confidence

Readiness Score

```
0–100
```

Low readiness SHALL favor simpler actions.

---

# Intervention Difficulty

Every intervention SHALL include a difficulty estimate.

| Level | Description |
|-------|-------------|
| 1 | Extremely Easy |
| 2 | Easy |
| 3 | Moderate |
| 4 | Difficult |
| 5 | Major Lifestyle Change |

Difficulty SHALL influence ranking.

---

# Historical Effectiveness

The engine SHALL consult previous intervention outcomes.

Example

Past

Morning Walk

↓

Completed

7 times

Future score

↑

Example

Meditation

↓

Rejected

5 times

Future score

↓

The AI learns what actually works.

---

# Intervention Ranking Formula

Every candidate receives a score.

```

Expected Benefit

+

Historical Success

+

Readiness

+

Evidence Confidence

+

Urgency

-

Difficulty

-

Cognitive Load

```

Highest score wins.

---

# Micro Intervention Principle

Whenever possible,

prefer the smallest meaningful action.

Instead of

```
Exercise 60 minutes daily.
```

Prefer

```
Walk outside for 10 minutes after lunch.
```

Small wins build momentum.

---

# One Primary Intervention Rule

The AI SHALL recommend

ONE primary action.

Optional supporting actions may be suggested only if they do not significantly increase cognitive load.

Avoid overwhelming users.

---

# Timing Rules

Do NOT recommend

- during emotional crisis
- before understanding
- while ambiguity remains
- during active clarification

Recommendations SHOULD follow reflection.

---

# Follow-up Strategy

Every intervention SHALL define

- success criteria
- follow-up timing
- expected obstacles
- alternative plan

Example

```
Action

Sleep before 11 PM

↓

Follow-up

Tomorrow

↓

Obstacle

Late meetings

↓

Alternative

Reduce screen time by 30 minutes

```

---

# Intervention Diversity

Avoid repeating identical interventions.

Track

- category frequency
- recent recommendations
- recommendation outcomes

Diversify when appropriate.

---

# Intervention Escalation

Repeated failure SHALL trigger adaptation.

Example

Three failed exercise plans

↓

Reduce difficulty

OR

Investigate barriers

NOT

Repeat the same recommendation.

---

# Safety Rules

The engine SHALL never

- recommend unsafe behaviors
- provide medical diagnoses
- encourage guilt
- shame the user
- ignore crisis signals

Safety overrides recommendation quality.

---

# Opportunity-Based Coaching

Positive moments deserve interventions too.

Example

User

```
I slept really well yesterday.
```

Intervention

```
Identify what made yesterday successful.

Help repeat it.
```

Success is a coaching opportunity.

---

# Weekly Intervention Review

Every week evaluate

- completion rate
- recommendation quality
- abandoned actions
- successful habits
- intervention diversity

Future recommendations SHALL improve.

---

# Decision Table

| Situation | Preferred Intervention |
|-----------|-----------------------|
| Low Motivation | Very Small Action |
| High Motivation | Stretch Goal |
| High Stress | Recovery |
| Habit Formation | Consistency Action |
| Knowledge Gap | Education |
| Emotional Distress | Validation + Recovery |
| Repeated Failure | Barrier Investigation |
| Strong Momentum | Progressive Challenge |

---

# Failure Modes

Detect

- recommendation loops
- excessive difficulty
- repeated rejection
- intervention overload
- contradictory recommendations
- unsafe interventions

Generate diagnostics.

---

# Acceptance Criteria

Implementation is complete when

✓ Recommendations become increasingly personalized.

✓ Small actions are preferred.

✓ Failed interventions become less frequent.

✓ Root causes receive priority.

✓ Recommendations reference discovered insights.

✓ Follow-ups occur naturally.

✓ Recommendation quality improves over time.

---

# Architecture Decision Record

## ADR-014

Decision

Introduce a Behavioral Intervention Engine responsible for selecting interventions based on readiness, evidence, historical effectiveness, and expected completion probability.

Status

Accepted.

Reason

The success of a coaching system depends not on generating advice, but on recommending actions that users are realistically able and willing to complete.

Separating intervention selection from language generation ensures recommendations remain evidence-based, personalized, and measurable.


## Architecture Decisions

### ADR-001

Conversation is driven by understanding, not state.

Status:
Accepted

Reason:
State machines become rigid.
Understanding-driven orchestration allows adaptive conversations.