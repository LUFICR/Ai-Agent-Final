# M6 Migration Report — Runtime Foundation (RFC-002 Ch3/Ch4)

Implements **Migration Task M6** of `docs/GAP_ANALYSIS.md` (K. Migration Plan):
RuntimeContext (immutable, request-scoped) + EngineUpdate + RuntimeEngine
contract; wrap the 12 deterministic engines with `execute(input, ctx) -> EngineUpdate`.
Scope frozen to M6 only. No Engine Registry (M7), no Runtime Orchestrator (M8),
no streaming — all deferred per the migration plan.

## New files

| File | Purpose |
|---|---|
| `wellness_agent/runtime/__init__.py` | Package exports (`__all__`). |
| `wellness_agent/runtime/engine_result.py` | `EngineResult` enum: SUCCESS / PARTIAL / FAILED / SKIPPED with `ok` helper (RFC-002 Ch4 "Engine Result States"). |
| `wellness_agent/runtime/engine_metrics.py` | `EngineMetrics` frozen dataclass: `latency_ms`, `started_at`, `finished_at`, `retry_count` (RFC-002:1593-1603). |
| `wellness_agent/runtime/diagnostics.py` | `Diagnostic` + `DecisionTrace` frozen records for `DiagnosticsContext` (RFC-002:1179-1197). |
| `wellness_agent/runtime/engine_update.py` | `EngineUpdate` frozen dataclass: `result`, `data`, `diagnostics`, `warnings`, `metrics`, `success` (derived from result); factories `success/partial/failed/skipped` (RFC-002:1564-1622). |
| `wellness_agent/runtime/runtime_context.py` | `RuntimeContext` + the eight sub-contexts (Request/Conversation/Memory/Execution/Diagnostics/Metrics/Streaming/Metadata), `RuntimeStage` enum, `RuntimeContext.create(...)` factory (deep-copies inputs), `validate()` (required IDs), `snapshot()` (RFC-002 Ch3). |
| `wellness_agent/runtime/runtime_engine.py` | `EngineCategory` enum, `EngineMetadata`, `RetryPolicy`, `RuntimeEngine` ABC (`id/name/version/metadata/execute/health_check/initialize/dispose`, RFC-002:1492-1656), and `BaseEngine` which guarantees engines never throw (exceptions → `EngineUpdate.failed` with `ENGINE_EXCEPTION` diagnostic) and attaches metrics automatically (RFC-002:1606-1607, 1673-1693). |
| `wellness_agent/runtime/adapters.py` | 12 thin contract adapters wrapping the existing deterministic engines: `MemoryAdapter`, `LearningAdapter`, `BeliefAdapter`, `HypothesisAdapter`, `BehaviorAdapter`, `WhyAdapter`, `ProactiveAdapter`, `RootCauseAdapter`, `RoutineAdapter`, `ReportsAdapter`, `SelfEvaluationAdapter`, `EmotionAdapter`. Each injects the existing engine instance (DI per RFC-002 Ch2; no engine instantiates another), maps input keys, calls the existing public method, and returns `EngineUpdate`. Adapters never import concrete engine modules. |
| `tests/test_runtime_engine.py` | 22 unit tests (offline, assert-based, no pytest). |

## Modified files

| File | Change | Why |
|---|---|---|
| `wellness_agent/runtime/engine_update.py` | `success` implemented as a field derived in `__post_init__` from `result.ok` | Initial version used a property named `success`, which collided with the `success()` classmethod factory and shadowed it on instance lookup; caught by the unit tests. Final design keeps the RFC field and the factory API. |
| No existing engine modules modified | — | M6 requirement: existing business logic unchanged. The 12 engines are untouched; adapters call their existing public methods with the same arguments the orchestrator passes today. |

## Why each change was made (requirements mapping)

- **Immutable request-scoped RuntimeContext** → `runtime_context.py`: all frozen dataclasses; `FrozenInstanceError` on any mutation; created per request via `create()`; never cached; inputs deep-copied.
- **RuntimeEngine exactly per RFC-002** → `runtime_engine.py` `execute(input, context) -> EngineUpdate` + `id/version/name` + health check + retry/timeout declarations.
- **EngineUpdate contract** → `engine_update.py` with the four `EngineResult` states and auto-metrics.
- **EngineMetrics** → collected automatically by `BaseEngine.execute`; engines never build them by hand.
- **Do NOT change engine behavior** → adapters are pass-through; zero edits to engine modules.
- **No engine may mutate RuntimeContext** → frozen context + adapters only read; verified by `test_engine_does_not_mutate_context` (snapshot equality before/after execution).
- **Every engine independently testable** → constructor-injected dependencies; every adapter unit-tested with real engine instances and mocked deps (the exploding-engine test).

## RFC sections implemented

- RFC-002 Ch3 "Runtime Context & State Management" (L987-1462): full hierarchy, immutability, update-flow contract, ownership, lifetime, validation, acceptance criteria.
- RFC-002 Ch4 "Engine Interface Contracts" (L1464-1832): Runtime Engine Contract, Engine Metadata, Engine Input/Output, Engine Metrics, Engine Result States, lifecycle hooks, health checks, versioning, error contract, categories, dependency rules, testing contract.
- RFC-002 Ch2 (L697-713) DI principle honored: engines injected, none instantiated internally (full registry deferred to M7).

## Not implemented (per M6 scope + migration plan)

- Engine Registry / DI container (M7)
- Runtime Orchestrator / pipeline execution / update merging (M8)
- Streaming (M18)
- Engine Registry diagnostics, retry execution, timeout enforcement (runtime responsibilities; declared as metadata now)

## Verification

| Check | Result |
|---|---|
| `tests/test_runtime_engine.py` | 22/22 PASS |
| `tests/test_storage_interface.py` (M5) | 12/12 PASS |
| `memory_test.py` | ALL PASS |
| `coaching_test.py` | ALL PASS |
| `learning_test.py` | ALL PASS |
| `phase6_stress100.py` (100 sim runs) | OVERALL MEAN 82.0 — identical to pre-M6 baseline |
| CI import smoke (`from wellness_agent.orchestrator import Orchestrator` + runtime imports) | OK |
| `data/evaluations/index.json` | 620 entries (invariant preserved) |
| `git status` | only `wellness_agent/runtime/` (new) + `tests/` + `docs/`; engine modules untouched |

## Remaining work

- M7: EngineRegistry + DI (replace AgentRegistry; register once, resolve by interface, mocks).
- M8: decompose `orchestrator.py` into a business-logic-free runtime orchestrator that creates RuntimeContext per request, executes engines in RFC-002 Ch5 order, and merges EngineUpdates into new contexts.
- M9/M10: LLM client hardening + PromptBuilder.
