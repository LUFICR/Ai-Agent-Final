# M7 Migration Report — Engine Registry & Dependency Injection (RFC-002 Ch2)

Implements **Migration Task M7** of `docs/GAP_ANALYSIS.md` (K. Migration Plan):
EngineRegistry + DI replacing AgentRegistry — register once, resolve by
interface, lazy init, mocks. Scope frozen to M7 only. No Runtime Orchestrator
(M8), no conversation-logic changes, no planner changes, no streaming.

## New files

| File | Purpose |
|---|---|
| `wellness_agent/runtime/registry.py` | `EngineRegistry` DI container (RFC-002 Ch2): `register` (factories, deps declared, duplicate → `RegistrationError`), `register_instance`, `get` (lazy build, singleton per id, `UnknownEngineError`, `RegistrationError` for missing deps, `CircularDependencyError` for cycles, thread-safe via `RLock`), `replace` + `mock()` context manager (mock support, RFC-002:864-881), `health_check`/`health` (RFC-002:1645-1656), `initialize_all` (fails startup on unhealthy engine, RFC-002:936-947), `dispose_all`, `diagnostics` (registered/initialized engines, metadata, init times, dependency graph, health, version — RFC-002:922-933). |
| `tests/test_engine_registry.py` | 15 unit tests (offline, assert-based). |

## Modified files

| File | Change | Why |
|---|---|---|
| `wellness_agent/agents.py` | `AgentRegistry` internals replaced by `build_user_registry(user_id)` + a thin facade. Engine construction moved into registry factories (all 17 raw engines + 12 M6 adapters, 29 registrations, each exactly once, deps declared and validated). `AgentRegistry` now resolves every attribute through `registry.get(...)`; `get_agent`/`extract_and_store`/`reflection_response` kept verbatim. | GAP M7 "agents.py -> registry": the runtime now retrieves engines only through the registry; no engine instantiates another (factories receive the registry and resolve deps via `get`); lazy factories kill the ~10 per-user disk loads per `Orchestrator()` (only `memory` is built eagerly — `state_machine` still needs it at construction). `Orchestrator` untouched → conversation logic unchanged. |
| `wellness_agent/utils/storage.py` | `JsonFileStorage.save` now retries `os.replace` up to 5x (50–250 ms backoff) on transient Windows sharing violations (`EACCES`/`EPERM`/`EBUSY`). | Discovered during M7 regression runs: AV/Indexer intermittently locks freshly written files and `os.replace` failed with WinError 5 (flaky `memory_test`, flaky M5 suite). Retry keeps atomicity (single rename on success) and restores suite stability; 3 consecutive full-suite runs green after the fix. |

## RFC sections implemented

- RFC-002 Ch2 "Engine Registry & Dependency Injection" (L572-986) in full:
  - single source of truth, registry owns creation (L574-582)
  - dependency injection principle — every dependency injected, none constructed inside engines (L626-654)
  - registration exactly once, duplicates throw (L658-677)
  - runtime resolution by id (L680-694); engine interfaces/metadata (L697-713)
  - singleton policy, scoped objects, lifecycle, dependency graph (L716-845)
  - mock support (L864-881), thread safety (L910-919), diagnostics (L922-933), failure handling (L936-947), acceptance criteria (L950-966), ADR-003 (L970-982)
- Ch4 health checks + versioning honored: `health_check()` used by the registry; per-engine metadata surfaced in `diagnostics()`.

## Tests executed (all offline)

| Suite | Result |
|---|---|
| `tests/test_engine_registry.py` (registration, duplicate, resolution, singleton, mock, health, lifecycle, cycles, facade, orchestrator wiring) | 15/15 PASS |
| `tests/test_runtime_engine.py` (M6) | 22/22 PASS |
| `tests/test_storage_interface.py` (M5) | 12/12 PASS |
| `memory_test.py` (×3 consecutive after the storage retry fix) | ALL PASS |
| `coaching_test.py` | ALL PASS |
| `learning_test.py` | ALL PASS |
| `phase6_stress100.py` (100 sim runs) | OVERALL MEAN 82.0 — identical to baseline |
| CI import smoke (orchestrator + agents + runtime) | OK |
| `data/evaluations/index.json` | 620 entries (invariant preserved) |
| `git status` | `agents.py` + `storage.py` modified, `runtime/` + `tests/` new; engines untouched |

## Remaining work

- M8: Runtime Orchestrator — decompose `orchestrator.py` into a business-logic-free runtime that creates a request-scoped `RuntimeContext`, executes engines in RFC-002 Ch5 order via the registry, and merges `EngineUpdate`s into new contexts.
- M9/M10: LLM client hardening + PromptBuilder.
- M12-M26 per migration plan (registry diagnostics hardening, retry/timeout enforcement, streaming M18, etc.).

M7 complete. Stopping here as instructed; nothing committed. Say **save** to push `main` (auto-deploys to Render).
