# M8 Migration Summary — Runtime Orchestrator

**Spec:** `docs/specifications/M8_RUNTIME_ORCHESTRATOR_IMPLEMENTATION.md.md` (Chapters 1–4)
**Scope:** runtime-architecture migration only — no intent/branch/why/coach/memory rewrites, no streaming improvements, no database changes. Existing conversation behavior is byte-identical.
**Status:** COMPLETE — all acceptance criteria met.

---

## 1. What was built

### 1.1 `ConversationRuntime` (spec Ch1, ADR-M8-001)
- New public entry point: exactly one method, `execute(ConversationRequest) -> ConversationResponse`.
- Validates the request (invalid → `ValueError` before orchestration), creates a unique request-scoped `RuntimeContext`, resolves the `RuntimeOrchestrator` **from the Engine Registry** (direct construction prohibited), invokes it, and returns the response contract `{response_id, message, data, diagnostics, metrics}`.
- Completely stateless; contains zero business logic.
- Empty messages remain valid requests (greeting flow — verified against `main.py`, which calls `process_message("")`).

### 1.2 `RuntimeOrchestrator` (spec Ch2, ADR-M8-002)
- Single public method `execute(RuntimeContext) -> RuntimeResult{context, response, metrics, diagnostics}`.
- Owns the full internal lifecycle: state transitions, deterministic pipeline execution, centralized update merging, events, metrics, streaming window, persistence phase, completion and disposal.
- Internal components, each with one responsibility: `PipelineExecutor`, `ContextMergeEngine`, `EventDispatcher`, `MetricsCollector`, `StreamCoordinator`, `PersistenceCoordinator`, plus centralized `RetryManager`/`TimeoutManager` (in `pipeline_executor.py`).
- Failure recovery: recoverable engine failures → retry policy → optional fallback; critical failures → `RuntimeFailed` event, context → FAILED → DISPOSED, `RuntimeExecutionError` raised. No corrupted context ever continues.
- Per-request isolation: dispatcher/metrics are per-execution; the orchestrator holds no mutable shared state (verified by an 8-thread concurrency test).

### 1.3 `PipelineExecutor` (spec Ch3, ADR-M8-003)
- Executes `PipelineStage`s in declared deterministic order, resolving every engine **only through the Engine Registry**.
- Per-stage preconditions (enabled, registered, healthy), stage inputs via `input_builder`, `RetryPolicy` retries with backoff, timeout enforcement (`ENGINE_TIMEOUT` diagnostic), optional-stage fallback (SKIPPED, pipeline continues), required-stage failure → `PipelineError`.
- Hooks: `PipelineStarted`, `EngineStarted`, `EngineCompleted`, `EngineFailed`, `StageCompleted`, `PipelineCompleted`, `PipelineFailed`.
- Reasoning stays strictly sequential (M8 spec: "Reasoning SHALL never execute in parallel").

### 1.4 RuntimeContext Merge Engine (spec Ch4, ADR-M8-004)
- **The only component permitted to modify a RuntimeContext.** Engines return immutable `EngineUpdate`s; every merge produces a new context version.
- Field ownership enforced (`conversation`/`intent_resolver`/`branch_manager`/`knowledge`/`runtime`/`persistence` owners); unauthorized writes → `ConflictDetected` → rollback (`MergeFailed` + `RollbackExecuted` events, `ok=False`, previous context restored — rollback can never expose partially merged state because merges are atomic immutable constructions).
- Immutable history: every successful merge appends `MergeHistoryEntry{version, timestamp, engine, update, snapshot, diagnostics}`; snapshots support replay/debugging.
- Merge metrics: version, merge latency, validation latency, rollback count, conflicts — accumulated in `MetricsContext.merge_metrics`.
- Diagnostics events: `MergeStarted`, `MergeCompleted`, `MergeFailed`, `RollbackExecuted`, `ConflictDetected`.
- Runtime state machine `Created → Validated → Executing → Streaming → Persisting → Completed → Disposed` (+ `Recovering`/`Failed` failure path); invalid transitions raise `MergeError`.

### 1.5 Orchestrator wiring (behavior unchanged)
- `Orchestrator.process_message` now delegates to `ConversationRuntime.execute(...)` and returns the **same turn dict** as before. The old body lives on as `_process_turn` (unchanged) and is wrapped by the registered `conversation` engine.
- Three engines registered per user (once): `conversation` (wraps `_process_turn`), `persistence` (runtime persistence-phase marker — durable writes stay inside the conversation flow, no double writes), `runtime_orchestrator`.
- LLM calls stay inside the conversation flow exactly as before (hybrid LLM+rule calls, offline fallback) — externalizing the LLM into its own pipeline stage is deferred (would require rewriting the engine's hybrid calls).

---

## 2. Runtime Sequence Diagram (M8 deliverable)

```
Client / /chat
   │
   │ POST message
   ▼
Orchestrator.process_message(user_message)          [unchanged public API]
   │  builds ConversationRequest
   ▼
ConversationRuntime.execute(request)                [Ch1 — stateless entry point]
   │  1. validate request (user_id; message may be empty)
   │  2. RuntimeContext.create(...)                → CREATED
   │  3. resolve "runtime_orchestrator" from Engine Registry
   ▼
RuntimeOrchestrator.execute(context)                [Ch2 — lifecycle owner]
   │  validate → transition VALIDATED → EXECUTING
   │  emit RuntimeStarted, EngineStarted, ... events (EventDispatcher)
   ▼
PipelineExecutor.execute({"message": ...}, ctx)     [Ch3 — execution]
   │  ┌──────────────────────────────────────────────────────────┐
   │  │ stage "conversation" (registered engine, via registry)   │
   │  │   ConversationEngine._process_turn(message)              │
   │  │     → emotion/memory/state/behavior/beliefs/hypotheses/  │
   │  │       why/objective/interventions/LLM response generation│
   │  │       (rule-based offline) — EXACT pre-M8 flow           │
   │  └──────────────────────────────────────────────────────────┘
   │  returns StageResult{status, EngineUpdate{turn}, latency}
   ▼
ContextMergeEngine.merge(ctx, update, "conversation") [Ch4 — only mutator]
   │  validate update → ownership check → apply → validate new ctx
   │  → snapshot + history entry → RuntimeContext V2 (immutable)
   ▼
transition STREAMING → StreamingContext recorded   (StreamCoordinator)
transition PERSISTING → stage "persistence" (optional) (PersistenceCoordinator)
   ▼
finalize: flush events + execution metadata → transition COMPLETED → DISPOSED
   ▼
RuntimeResult{context, response, metrics, diagnostics}
   ▼
ConversationResponse{response_id, message, data=turn, diagnostics, metrics}
   ▼
Orchestrator returns response.data — the identical turn dict as pre-M8
```

---

## 3. Acceptance criteria — verification

| Criterion | Verified |
|---|---|
| Existing AI works identically | memory/coaching/learning suites pass; stress100 mean **82.0** (baseline unchanged); `/chat` offline flows byte-identical |
| Runtime executes through ConversationRuntime | `process_message` → `runtime.execute` (integration test) |
| RuntimeOrchestrator controls execution | lifecycle test: states, events, disposal (9/9 tests) |
| PipelineExecutor executes engines via registry | order/precondition/retry/timeout/hooks (12/12 tests) |
| Merge Engine performs all merges | every context mutation flows through `merge()` (12/12 tests) |
| No engine mutates RuntimeContext | frozen contexts; mutation attempts raise; concurrency test (9/9 + 8-thread) |
| Runtime state transitions validated | invalid transitions rejected (merge tests) |
| All existing tests pass | see section 4 |
| Integration tests added | `tests/test_runtime_integration.py` (6/6) |

---

## 4. Test results (all offline, no LLM)

| Suite | Result |
|---|---|
| `tests/test_merge_engine.py` (new) | 12/12 |
| `tests/test_pipeline_executor.py` (new) | 12/12 |
| `tests/test_runtime_orchestrator.py` (new) | 9/9 |
| `tests/test_conversation_runtime.py` (new) | 7/7 |
| `tests/test_runtime_integration.py` (new) | 6/6 |
| `tests/test_storage_interface.py` | 12/12 |
| `tests/test_runtime_engine.py` | 22/22 |
| `tests/test_engine_registry.py` | 15/15 |
| `memory_test.py` | 11/11 |
| `coaching_test.py` | 9/9 |
| `learning_test.py` | 12/12 |
| `phase6_stress100.py` | mean 82.0 (baseline 82.0) |
| CI import smoke + live-form flow | OK |
| Eval index | exactly 620 entries |
| Data hygiene (`rt_m8_*` files) | 0 leftovers; eval index untouched |

---

## 5. Files changed

**New — runtime layer (`wellness_agent/runtime/`):**
- `merge_engine.py` — `ContextMergeEngine`, `MergeHistoryEntry`, `MergeSummary`, `MergeResult`, `MergeError`, `RuntimeEvent`
- `pipeline_executor.py` — `PipelineExecutor`, `PipelineStage`, `StageResult`, `RetryManager`, `TimeoutManager`, `PipelineError`
- `runtime_orchestrator.py` — `RuntimeOrchestrator`, `RuntimeResult`, `RuntimeExecutionError`, `EventDispatcher`, `MetricsCollector`, `StreamCoordinator`, `PersistenceCoordinator`
- `conversation_runtime.py` — `ConversationRequest`, `ConversationResponse`, `ConversationRuntime`
- `conversation_engine.py` — `ConversationEngine`, `PersistenceEngine`
- `__init__.py` — exports extended

**Modified:**
- `wellness_agent/runtime/runtime_context.py` — `RuntimeState` enum; `RequestContext.message`, `ConversationContext.turn`, `DiagnosticsContext.events`, `MetricsContext.merge_metrics`, `RuntimeContext.version/lifecycle/history` (all defaulted, backward compatible)
- `wellness_agent/orchestrator.py` — registers runtime engines; `process_message` delegates to `ConversationRuntime`; business flow renamed `_process_turn` (unchanged)

**Tests (new):** `tests/test_merge_engine.py`, `test_pipeline_executor.py`, `test_runtime_orchestrator.py`, `test_conversation_runtime.py`, `test_runtime_integration.py`

---

## 6. Remaining work (out of scope for M8, per instructions)

1. **Intent Resolver rewrite** — the emotion/route analysis stays inside the conversation flow; a dedicated Intent Resolver engine would replace `_decide_route`/`_analyze_emotion` (spec Ch1 pipeline).
2. **Branch rewrite** — state machine stays internal to the conversation engine; a `branch_manager` pipeline stage could own `active_branch` (ownership table already reserved).
3. **Why Engine rewrite** — `why` stays inside the flow; the registry owner entry exists (`whyInsights` per spec Ch4 ownership table).
4. **Coach rewrite** — the response-generation flow stays in the conversation engine; splitting it into Planner/Strategy/Coach/BIE/PromptBuilder pipeline stages would require re-implementing the interleaved LLM+rule calls.
5. **Memory rewrite / database changes** — unchanged (per instructions).
6. **Streaming improvements** — the runtime records the streaming window (`StreamingContext`); real token streaming is a separate migration.
7. **LLM as a dedicated pipeline stage** — LLM calls currently execute inside the conversation engine (hybrid LLM+rule, offline fallback); externalizing them requires the engine rewrites above.
8. **Per-stage runtime persistence** — durable writes (session/memory) still occur inside the conversation flow; routing them through the `persistence` engine is a follow-up.

---

## 7. Notes

- `ConversationRuntime` resolves `runtime_orchestrator` from the per-user registry; the orchestrator itself is stateless and safe to share across requests (thread test).
- Merge snapshots are deep copies per merge — acceptable at current turn sizes; a larger history replay feature can page snapshots later.
- The `conversation` pipeline stage is registered with a 120 s timeout (LLM budget) and no retries — matching pre-M8 behavior (no retry on failure).
