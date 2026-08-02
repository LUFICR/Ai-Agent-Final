# M8 – Runtime Orchestrator Implementation Specification

---

# Status

Implementation Specification

---

# Version

1.0

---

# Depends On

RFC-001

RFC-002

M5

M6

M7

---

# Purpose

This specification defines the production implementation of the Runtime Orchestrator.

Unlike RFC-002, which describes architecture, this document defines the concrete implementation strategy.

It specifies

- classes
- methods
- execution flow
- update lifecycle
- dependency resolution
- persistence flow
- streaming lifecycle
- middleware
- hooks
- retry strategy

The goal is to remove architectural decision-making during implementation.

After completing this specification, the coding agent should only translate the design into production code.

---

# Goals

The Runtime Orchestrator SHALL

- coordinate every runtime engine
- remain completely stateless
- execute deterministic pipelines
- support streaming
- support retries
- support observability
- support future plugins

The Runtime Orchestrator SHALL NOT

- perform AI reasoning
- implement coaching
- classify intents
- update memory
- contain business logic

It is purely an execution engine.

---

# Design Philosophy

The Runtime Orchestrator is the operating system of the AI.

Every engine behaves like an application.

The Runtime never decides.

It only executes.

---

# High-Level Architecture

```

                     Client

                        │

                ConversationRuntime

                        │

               RuntimeOrchestrator

                        │

                Engine Registry

                        │

────────────────────────────────────────

Intent Resolver

Branch Manager

Knowledge Engine

Planner

Strategy

Coach

Why

Intervention

Prompt Builder

────────────────────────────────────────

                        │

                       LLM

                        │

                  Stream Manager

                        │

                   Persistence

                        │

                  Metrics / Events

```

---

# Runtime Rule

Every request creates

exactly one Runtime Orchestrator.

Every Runtime Orchestrator owns

exactly one Runtime Context.

Every engine receives

exactly the same Runtime Context.

No engine modifies it directly.

Only the Runtime merges updates.

---

# Runtime Responsibilities

The Runtime owns

- lifecycle
- execution
- dependency resolution
- retries
- diagnostics
- metrics
- persistence
- events
- streaming

Nothing else.

---

# Runtime Success Criteria

A runtime execution is successful when

- every engine executes in order
- updates merge successfully
- prompt generation succeeds
- response streams successfully
- persistence completes
- metrics recorded
- runtime disposed

---

# Out of Scope

This document does NOT define

- intent logic
- slot logic
- coaching
- memory algorithms
- recommendation algorithms

These remain owned by RFC-001.



---

# Chapter 1 — ConversationRuntime

## Purpose

ConversationRuntime is the public entry point into the AI system.

Every conversation request—whether from chat, voice, mobile, API, or future channels—must enter through this class.

No component may invoke the RuntimeOrchestrator directly.

ConversationRuntime exists to provide a stable, framework-independent API while delegating orchestration to the RuntimeOrchestrator.

---

# Design Principles

ConversationRuntime SHALL

- expose exactly one public execution method
- remain stateless
- validate requests
- create runtime scope
- invoke RuntimeOrchestrator
- return the final conversation response
- never contain business logic

ConversationRuntime SHALL NOT

- classify intents
- update memory
- call engines directly
- build prompts
- perform retries
- merge updates

Those responsibilities belong elsewhere.

---

# Responsibility

ConversationRuntime owns the request lifecycle.

Responsibilities include

- request validation
- runtime creation
- dependency resolution
- orchestration invocation
- response delivery
- runtime disposal

Everything else is delegated.

---

# Public Interface

The Runtime exposes a single public interface.

```typescript
class ConversationRuntime {

    async execute(

        request: ConversationRequest

    ): Promise<ConversationResponse>;

}
```

This method SHALL become the only entry point for runtime execution.

---

# Request Lifecycle

Every execution follows the same lifecycle.

```text

ConversationRequest

↓

Validate

↓

Create Runtime Scope

↓

Resolve Dependencies

↓

Create RuntimeContext

↓

Invoke RuntimeOrchestrator

↓

Receive Response

↓

Dispose Runtime

↓

Return ConversationResponse

```

The ConversationRuntime SHALL never skip lifecycle stages.

---

# Execution Flow

ConversationRuntime SHALL execute the following sequence.

1.

Validate request.

↓

2.

Resolve runtime services.

↓

3.

Create RuntimeContext.

↓

4.

Create RuntimeOrchestrator.

↓

5.

Invoke execute().

↓

6.

Receive RuntimeResult.

↓

7.

Dispose request resources.

↓

8.

Return response.

---

# Dependency Resolution

ConversationRuntime SHALL obtain all dependencies from the Engine Registry.

Example

```typescript
const orchestrator =
registry.resolve<RuntimeOrchestrator>();
```

Direct construction is prohibited.

---

# Runtime Scope

Each request SHALL create a unique runtime scope.

Runtime Scope contains

- RuntimeContext
- Metrics
- Diagnostics
- StreamContext
- ExecutionState

No runtime scope SHALL survive request completion.

---

# Request Validation

Before execution

ConversationRuntime SHALL validate

- user identifier
- conversation identifier
- request schema
- channel
- authentication
- runtime compatibility

Invalid requests SHALL terminate before orchestration begins.

---

# Response Contract

Every successful execution SHALL return

```typescript
interface ConversationResponse {

    responseId: string;

    message: AssistantMessage;

    diagnostics?: RuntimeDiagnostics;

    metrics?: RuntimeMetrics;

}
```

The ConversationRuntime SHALL never expose internal implementation details.

---

# Failure Handling

ConversationRuntime SHALL distinguish

Recoverable

- temporary infrastructure failures
- retryable external failures

Critical

- invalid requests
- corrupted runtime state
- incompatible runtime versions

Recoverable failures MAY retry.

Critical failures SHALL terminate execution.

---

# Runtime Disposal

After execution completes

ConversationRuntime SHALL

- release RuntimeContext
- release StreamContext
- flush metrics
- emit completion events
- dispose diagnostics

No request-scoped resources may remain allocated.

---

# Thread Safety

ConversationRuntime SHALL remain completely stateless.

All mutable state SHALL exist only inside RuntimeContext.

This enables concurrent execution across multiple runtime instances.

---

# Sequence Diagram

```text

Client

↓

ConversationRuntime

↓

RuntimeContext

↓

RuntimeOrchestrator

↓

ConversationResponse

↓

Client

```

ConversationRuntime never communicates directly with engines.

---

# Acceptance Criteria

Implementation is complete when

✓ Exactly one public execute() method exists.

✓ Every request creates a RuntimeContext.

✓ RuntimeOrchestrator is always invoked.

✓ No business logic exists inside ConversationRuntime.

✓ Runtime resources are disposed after execution.

✓ Runtime remains stateless.

✓ Unit tests cover request lifecycle.

---

# ADR-M8-001

## Decision

Introduce ConversationRuntime as the single public entry point into the AI runtime.

## Status

Accepted

## Reason

A single entry point simplifies integration, testing, tracing, and future expansion while preventing external components from bypassing runtime orchestration.


---

# Chapter 2 – RuntimeOrchestrator

## Purpose

The RuntimeOrchestrator is the central execution coordinator of the AI platform.

It owns the complete lifecycle of a conversation request from the moment a RuntimeContext is created until the response has been persisted and all runtime resources have been released.

Unlike ConversationRuntime, which manages the external request lifecycle, the RuntimeOrchestrator manages the internal execution lifecycle.

The RuntimeOrchestrator SHALL NOT contain AI reasoning.

It coordinates reasoning engines but never performs reasoning itself.

---

# Design Principles

The RuntimeOrchestrator SHALL

- coordinate engine execution
- execute a deterministic pipeline
- merge engine updates
- manage retries
- emit runtime events
- collect metrics
- coordinate streaming
- coordinate persistence

The RuntimeOrchestrator SHALL NOT

- classify intents
- decide conversation strategy
- generate coaching
- retrieve memory directly
- perform prompt engineering

---

# Responsibilities

The RuntimeOrchestrator owns

- execution scheduling
- engine sequencing
- update merging
- runtime state transitions
- middleware execution
- failure recovery
- timeout enforcement
- persistence scheduling
- runtime completion

---

# Public Interface

```typescript
class RuntimeOrchestrator {

    async execute(

        context: RuntimeContext

    ): Promise<RuntimeResult>;

}
```

This SHALL be the only public method.

---

# Internal Components

The RuntimeOrchestrator SHALL coordinate

```text
RuntimeOrchestrator

├── PipelineExecutor

├── UpdateMerger

├── MiddlewareManager

├── RetryManager

├── TimeoutManager

├── EventDispatcher

├── MetricsCollector

├── StreamCoordinator

└── PersistenceCoordinator
```

Each component owns one responsibility.

---

# Execution Pipeline

The RuntimeOrchestrator SHALL execute

```text
Initialize Runtime

↓

Execute Middleware (Before)

↓

Execute Intelligence Pipeline

↓

Merge Updates

↓

Build Prompt

↓

Call LLM

↓

Stream Response

↓

Persist Changes

↓

Execute Middleware (After)

↓

Finalize Runtime
```

The execution order SHALL remain deterministic.

---

# Engine Scheduling

The Runtime SHALL execute reasoning engines in the following order.

```text
Intent Resolver

↓

Branch Manager

↓

Knowledge Engine

↓

Conversation Planner

↓

Conversation Strategy

↓

Adaptive Coach

↓

Why Engine

↓

Behavioral Intervention Engine

↓

Prompt Builder
```

No engine SHALL reorder execution.

---

# Runtime State Machine

The RuntimeOrchestrator SHALL maintain exactly one runtime state.

```text
Initializing

↓

Loading

↓

Executing

↓

Streaming

↓

Persisting

↓

Completed

↓

Disposed
```

On failure

```text
Executing

↓

Recovering

↓

Completed

or

Failed
```

State transitions SHALL be validated.

---

# Engine Execution Loop

Each engine SHALL execute using the same process.

```text
Load Engine

↓

Validate Input

↓

Execute

↓

Receive EngineUpdate

↓

Validate Update

↓

Merge Update

↓

Record Metrics

↓

Continue
```

This loop SHALL be identical for every engine.

---

# Update Merge Process

The RuntimeOrchestrator SHALL merge updates sequentially.

```text
RuntimeContext V1

↓

EngineUpdate

↓

Merge

↓

RuntimeContext V2

↓

Next Engine
```

Engines SHALL NEVER merge updates themselves.

---

# Retry Coordination

If an engine fails

```text
Failure

↓

Retry Policy

↓

Retry

↓

Success

↓

Continue

↓

Failure

↓

Fallback

↓

Continue
```

Retries SHALL be coordinated by the RuntimeOrchestrator.

---

# Middleware Execution

The Runtime SHALL support

Before Middleware

```text
Authentication

Validation

Rate Limiting

Diagnostics
```

After Middleware

```text
Persistence

Metrics

Events

Cleanup
```

Middleware SHALL NOT contain business logic.

---

# Timeout Coordination

Each engine SHALL execute within its configured timeout.

If timeout expires

```text
Cancel Engine

↓

Retry

↓

Fallback

↓

Continue

or

Terminate
```

The Runtime SHALL own timeout enforcement.

---

# Event Dispatch

The Runtime SHALL emit

- RuntimeStarted
- EngineStarted
- EngineCompleted
- EngineFailed
- RuntimeCompleted
- RuntimeFailed

Events SHALL be asynchronous.

---

# Metrics Collection

For every engine record

- start time
- finish time
- latency
- retries
- warnings
- diagnostics

Metrics SHALL be attached to RuntimeResult.

---

# Runtime Result

The RuntimeOrchestrator SHALL return

```typescript
interface RuntimeResult {

    context: RuntimeContext;

    response: ConversationResponse;

    metrics: RuntimeMetrics;

    diagnostics: RuntimeDiagnostics;

}
```

The RuntimeResult SHALL be immutable.

---

# Failure Recovery

The Runtime SHALL distinguish

Recoverable

- retry
- fallback
- continue

Critical

- terminate
- release resources
- emit failure event

No corrupted RuntimeContext SHALL continue execution.

---

# Thread Safety

The RuntimeOrchestrator SHALL contain no mutable shared state.

Every request SHALL receive a new RuntimeOrchestrator execution context.

This enables concurrent execution across multiple runtime instances.

---

# Acceptance Criteria

Implementation is complete when

✓ Engine execution is deterministic.

✓ Update merging is centralized.

✓ Middleware executes correctly.

✓ Runtime states are validated.

✓ Metrics are collected.

✓ Events are emitted.

✓ Retries remain centralized.

✓ Runtime remains stateless.

---

# ADR-M8-002

## Decision

Adopt a centralized RuntimeOrchestrator responsible for coordinating all runtime execution while delegating reasoning to independent engines.

## Status

Accepted

## Reason

Separating orchestration from reasoning enables deterministic execution, independent engine evolution, easier debugging, and long-term scalability.

---

# Chapter 3 – PipelineExecutor & Engine Scheduling

## Purpose

The PipelineExecutor is responsible for executing every runtime engine in the correct order.

It acts as the execution engine of the Runtime Orchestrator.

The Runtime Orchestrator owns lifecycle management.

The PipelineExecutor owns execution.

The PipelineExecutor SHALL never perform reasoning.

It SHALL only execute engines according to the runtime pipeline.

---

# Responsibilities

The PipelineExecutor SHALL

- load engines
- validate dependencies
- determine execution order
- execute engines
- collect EngineUpdates
- coordinate retries
- coordinate timeouts
- notify RuntimeOrchestrator after every execution

The PipelineExecutor SHALL NOT

- classify intent
- update memory
- merge RuntimeContext
- build prompts
- perform persistence

---

# High-Level Architecture

```text

RuntimeOrchestrator

        │

        ▼

PipelineExecutor

        │

──────────────────────────────────────

Engine Registry

        │

──────────────────────────────────────

Intent Resolver

↓

Branch Manager

↓

Knowledge Engine

↓

Conversation Planner

↓

Conversation Strategy

↓

Adaptive Coach

↓

Why Engine

↓

Behavioral Intervention Engine

↓

Prompt Builder

──────────────────────────────────────
```

The PipelineExecutor SHALL retrieve engines only from the Engine Registry.

---

# Pipeline Definition

The execution pipeline SHALL be immutable during runtime.

Default pipeline

```text

Context Validation

↓

Intent Resolver

↓

Branch Manager

↓

Knowledge Engine

↓

Conversation Planner

↓

Conversation Strategy

↓

Adaptive Coach

↓

Why Engine

↓

Behavioral Intervention

↓

Prompt Builder

```

No engine may modify the execution sequence.

---

# Pipeline Stage

Every pipeline stage SHALL contain

```typescript
interface PipelineStage {

    id: string;

    engine: RuntimeEngine;

    enabled: boolean;

    optional: boolean;

    timeoutMs: number;

    retryPolicy: RetryPolicy;

}
```

---

# Engine Discovery

The PipelineExecutor SHALL request engines from the Engine Registry.

Example

```typescript
const engine = registry.resolve("IntentResolver");
```

The executor SHALL never instantiate engines directly.

---

# Execution Loop

Every stage SHALL execute using the same algorithm.

```text

Load Stage

↓

Validate Stage

↓

Check Preconditions

↓

Execute Engine

↓

Receive EngineUpdate

↓

Validate Update

↓

Return Update

↓

Continue

```

This loop SHALL remain identical for every engine.

---

# Preconditions

Before executing a stage

The executor SHALL verify

- stage enabled
- dependencies satisfied
- RuntimeContext valid
- timeout configured
- engine healthy

Failed preconditions SHALL skip execution or terminate according to policy.

---

# Conditional Execution

Stages MAY be skipped when

- disabled
- dependencies unavailable
- planner explicitly disables stage
- fallback policy activated

Skipped stages SHALL produce a Skipped EngineResult.

---

# Sequential Execution

Reasoning engines SHALL execute sequentially.

```text

Intent

↓

Branch

↓

Knowledge

↓

Planner

↓

Coach

↓

Why

↓

Intervention

```

Reasoning SHALL never execute in parallel.

---

# Parallel Execution

Infrastructure stages MAY execute concurrently.

Allowed examples

```text

Metrics

┐

├── Parallel

┘

Diagnostics

```

```text

Persistence

┐

├── Parallel

┘

Analytics

```

Business reasoning SHALL remain sequential.

---

# Retry Coordination

Each stage SHALL follow

```text

Execute

↓

Success?

↓

No

↓

Retry?

↓

Retry

↓

Success?

↓

Fallback

↓

Continue

```

Retries SHALL respect RetryPolicy.

---

# Timeout Handling

Every stage SHALL enforce

```text

Execution

↓

Timeout?

↓

Cancel

↓

Retry

↓

Fallback

↓

Continue

```

Timeouts SHALL be configurable.

---

# Stage Result

Every stage SHALL return

```typescript
interface StageResult {

    stageId: string;

    status: EngineResult;

    update: EngineUpdate;

    latencyMs: number;

}
```

The RuntimeOrchestrator SHALL consume StageResults.

---

# Engine Scheduling Rules

The scheduler SHALL guarantee

- deterministic execution
- stable ordering
- repeatable pipelines
- dependency validation
- timeout enforcement

The scheduler SHALL never optimize by reordering reasoning engines.

---

# Pipeline Hooks

The executor SHALL expose

Before Pipeline

```text

PipelineStarted

```

After Every Stage

```text

StageCompleted

```

Pipeline Finished

```text

PipelineCompleted

```

Pipeline Failed

```text

PipelineFailed

```

Hooks SHALL support observability.

---

# Diagnostics

Every stage SHALL record

- engine
- stage
- latency
- retries
- timeout
- diagnostics
- warnings

The Runtime SHALL aggregate diagnostics.

---

# Failure Strategy

Pipeline failures SHALL follow

```text

Recoverable

↓

Retry

↓

Fallback

↓

Continue

Critical

↓

Terminate Pipeline

↓

Dispose Runtime

```

---

# Acceptance Criteria

Implementation is complete when

✓ Pipeline execution is deterministic.

✓ Engines execute through the Engine Registry.

✓ Sequential reasoning is enforced.

✓ Parallel infrastructure execution is supported.

✓ Retry and timeout policies are centralized.

✓ Stage results are validated.

✓ Pipeline hooks emit correctly.

✓ Diagnostics are collected for every stage.

---

# ADR-M8-003

## Decision

Introduce a dedicated PipelineExecutor responsible for engine scheduling and execution.

## Status

Accepted

## Reason

Separating execution from orchestration keeps the RuntimeOrchestrator focused on lifecycle management while enabling deterministic scheduling, centralized retries, timeout handling, and future extensibility.

---

# Chapter 4 – RuntimeContext Merge Engine & State Transitions

## Purpose

The RuntimeContext Merge Engine is responsible for applying every EngineUpdate to the RuntimeContext.

It is the only component permitted to modify RuntimeContext.

Every reasoning engine produces immutable updates.

The Merge Engine combines those updates into a new RuntimeContext while preserving consistency, validating integrity, and maintaining complete execution history.

The Merge Engine SHALL never perform AI reasoning.

Its responsibility is limited to state management.

---

# Design Principles

The Merge Engine SHALL

- merge immutable updates
- validate RuntimeContext
- detect conflicts
- preserve history
- create snapshots
- support rollback
- enforce state transitions

The Merge Engine SHALL NOT

- execute engines
- perform reasoning
- retrieve memory
- schedule runtime execution

---

# High-Level Architecture

```text
RuntimeContext V1

↓

EngineUpdate

↓

Merge Engine

↓

Validation

↓

Conflict Resolution

↓

RuntimeContext V2

↓

History Snapshot

↓

Next Engine
```

The RuntimeContext SHALL never be modified directly.

---

# RuntimeContext Versioning

Each merge SHALL create a new immutable RuntimeContext.

Example

```text
Context V1

↓

Intent Resolver

↓

Context V2

↓

Branch Manager

↓

Context V3

↓

Planner

↓

Context V4
```

Previous versions SHALL remain immutable for diagnostics and replay.

---

# Merge Process

Every merge SHALL follow the same sequence.

```text
Receive EngineUpdate

↓

Validate Update

↓

Validate Current Context

↓

Apply Merge

↓

Validate New Context

↓

Store Snapshot

↓

Return RuntimeContext
```

The Merge Engine SHALL reject invalid updates.

---

# EngineUpdate Contract

Every EngineUpdate SHALL contain only changes.

Example

```typescript
interface EngineUpdate<T> {

    success: boolean;

    data: T;

    diagnostics: Diagnostic[];

    metrics: EngineMetrics;

}
```

Complete RuntimeContext replacement is prohibited.

---

# Merge Rules

Allowed

- append diagnostics
- update intent graph
- update slot graph
- update planner decision
- add new insight
- update execution metadata

Forbidden

- overwrite unrelated engine output
- remove previous history
- mutate immutable identifiers
- replace RuntimeContext entirely

---

# Context Ownership

Each runtime field SHALL have exactly one owner.

Example

| Context Field | Owner |
|--------------|-------|
| intentGraph | Intent Resolver |
| activeBranch | Branch Manager |
| slotGraph | Knowledge Engine |
| plannerDecision | Conversation Planner |
| coachingStyle | Adaptive Coach |
| whyInsights | Why Engine |
| interventions | Behavioral Intervention Engine |

The Merge Engine SHALL reject updates from unauthorized owners.

---

# Conflict Detection

Conflicts occur when multiple updates modify the same owned field during the same execution stage.

Example

```text
Planner

↓

plannerDecision

Coach

↓

plannerDecision

↓

Conflict
```

Conflicts SHALL terminate the merge.

---

# Merge Validation

After every merge validate

- RuntimeContext schema
- ownership
- required fields
- state integrity
- reference integrity

Invalid RuntimeContexts SHALL never continue.

---

# Runtime Snapshots

A snapshot SHALL be created after every successful merge.

Example

```text
Context V1

↓

Snapshot

↓

Context V2

↓

Snapshot

↓

Context V3
```

Snapshots SHALL support replay and debugging.

---

# Rollback Strategy

If validation fails

```text
Merge

↓

Validation Failed

↓

Restore Previous Snapshot

↓

Record Diagnostics

↓

Continue or Terminate
```

Rollback SHALL never restore partially merged state.

---

# Runtime State Machine

RuntimeContext SHALL move through

```text
Created

↓

Validated

↓

Executing

↓

Streaming

↓

Persisting

↓

Completed

↓

Disposed
```

Invalid transitions SHALL be rejected.

---

# State Transition Rules

Allowed

Executing

↓

Streaming

Streaming

↓

Persisting

Persisting

↓

Completed

Forbidden

Completed

↓

Executing

Disposed

↓

Executing

---

# Context History

The Merge Engine SHALL preserve

- version number
- timestamp
- originating engine
- applied update
- diagnostics

History SHALL be immutable.

---

# Merge Metrics

Every merge SHALL record

- merge latency
- validation latency
- rollback count
- conflicts detected
- context version

Metrics SHALL be attached to RuntimeMetrics.

---

# Diagnostics

Every merge SHALL emit

- MergeStarted
- MergeCompleted
- MergeFailed
- RollbackExecuted
- ConflictDetected

Events SHALL support observability.

---

# Thread Safety

The Merge Engine SHALL contain no shared mutable state.

Every RuntimeContext SHALL remain isolated to its runtime instance.

Concurrent conversations SHALL never share RuntimeContext.

---

# Acceptance Criteria

Implementation is complete when

✓ RuntimeContext remains immutable.

✓ Every merge creates a new version.

✓ Ownership rules are enforced.

✓ Invalid updates are rejected.

✓ Snapshots are created.

✓ Rollbacks restore previous state.

✓ Context history is preserved.

✓ State transitions are validated.

---

# ADR-M8-004

## Decision

Adopt a centralized RuntimeContext Merge Engine responsible for all RuntimeContext mutations and state transitions.

## Status

Accepted

## Reason

A centralized merge engine guarantees deterministic execution, prevents state corruption, enables replay, simplifies debugging, and provides a complete history of every reasoning step performed during a conversation.