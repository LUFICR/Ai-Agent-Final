# M5 Migration Summary — StorageInterface (atomic writes + file locking)

Implements **Migration Task M5** of `docs/GAP_ANALYSIS.md`, scope frozen to M5 only.
No RFCs were authored. No later migration tasks (M6+) were touched.

## Scope (as specified in GAP_ANALYSIS.md)
- **M5:** StorageInterface: atomic write (temp+rename), file lock, JSON impl;
  engines depend on interface not on storage module.
- **Acceptance criteria:** two concurrent writers on the same user file lose
  no data; all suites pass.

## Files changed

| File | Change | Why |
|---|---|---|
| `wellness_agent/utils/storage.py` | Rewritten (38 → ~215 lines). Added `StorageInterface` (ABC) and `JsonFileStorage` implementation; `load_json`/`save_json` now delegate to a module-level `default_storage` instance. `now_iso`/`days_since`/`merge_dicts` unchanged. | Core M5 deliverable. Atomic writes via temp file in the same directory + `os.replace`; cross-platform advisory file lock (`fcntl` on POSIX, `msvcrt` on Windows, PID-file O_EXCL fallback with stale detection); per-path in-process thread lock; dead-process locks auto-release (OS-level) or expire (fallback, 30 s stale). |
| `tests/test_storage_interface.py` | NEW — 12 standalone tests (assert-based, offline, no pytest). | Required by M5. Covers interface contract (abstract, cannot instantiate), missing-file → `{}`, roundtrip + unicode literals, full overwrite, parent-dir creation, temp-file cleanup, 8 threads × 15 writes, cross-process 4 × 8 writes via `spawn`, file lock blocks second holder, legacy API compat, unchanged engine imports. |

## Files NOT modified (by design)
- All 14 engine call sites (`orchestrator.py`, `memory.py`, `learning.py`,
  `belief_engine.py`, `hypothesis_engine.py`, `behavior_engine.py`,
  `why_engine.py`, `objective_engine.py`, `proactive_engine.py`,
  `conversation_planner.py`, `conversation_judge.py`, `leaderboards.py`,
  `reports.py`, `self_evaluation.py`) — unchanged. They keep calling
  `load_json`/`save_json`, which now route through the interface. This is the
  "engines depend on the interface" requirement: the JSON backend can be
  swapped (e.g. PostgreSQL, M15) by replacing `default_storage` without
  touching a single engine. Constructor injection of a storage handle is
  deferred to M6/M7 (EngineRegistry/DI), per M5 scope.
- No new dependencies added (`requirements.txt` untouched).

## Deviation found & fixed during implementation
Initial lock design used a persistent `<file>.lock` sidecar next to the data
file. `learning_test.py` globs the learning dir for names starting with
`lrn_`, and the sidecar (`lrn_u_a_learning.json.lock`) broke its file-count
assertion. Fix: lock sidecars now live in `%TEMP%\opencode_locks\<sha256>.lock`
(hash of resolved path), so they can never collide with data-directory globs.
No behavior change; the regression was caught by the existing suite and is
covered by the new `test_no_temp_files_left_behind` test.

## Verification
| Check | Result |
|---|---|
| `tests/test_storage_interface.py` | 12/12 PASS |
| `memory_test.py` | ALL PASS |
| `coaching_test.py` | ALL PASS |
| `learning_test.py` | 12/12 ALL PASS |
| `phase6_stress100.py` (100 sim runs) | OVERALL MEAN 82.0 (identical to pre-M5 baseline) |
| CI import smoke (`from wellness_agent.orchestrator import Orchestrator`) | OK |
| `data/evaluations/index.json` | 620 entries (invariant preserved) |
| `git status` | only `storage.py` modified + new `tests/` (untracked `docs/` is the pre-existing audit deliverable, not part of M5) |

## Migration order preserved
M5 completed standalone. M6+ not started. Stopping here as instructed.
