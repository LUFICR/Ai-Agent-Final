# GAP_ANALYSIS.md

# Architectural Gap Analysis — AI Agent Final (Wellness Companion Coach)

**Scope:** Full architecture audit of the repository at `C:\test` against the authoritative specifications:
`docs/architecture/RFC-001_ADAPTIVE_CONVERSATION_ORCHESTRATOR.md` (AI behavior, complete),
`docs/architecture/RFC-002_RUNTIME_ARCHITECTURE.md.md` (runtime architecture, complete),
`docs/architecture/IMPLEMENTATION_ROADMAP.md.md` (implementation order, complete).
RFC-003 through RFC-008, all files under `docs/ai/`, and `docs/testing/TESTING_SPEC.md` are **empty (0 bytes)** — they declare an index entry but contain no specification.

**Assumption of scale:** 1,000,000 active users, horizontal scaling, multi-instance stateless runtime.

**Severity posture:** EXTREMELY CRITICAL. Every claim below is grounded in the RFCs (behavior/architecture sections) or in direct code inspection. Nothing is invented beyond the RFCs. Where the RFC is empty, the gap is reported as "unspecified."

**Verification note:** All code references verified by direct file read on 2026-08-02. Line numbers refer to the current working tree.

---

## A. Executive Summary

### A.1 Compliance Assessment

| Dimension | RFC Compliance | Progress | Trend |
|---|---|---|---|
| AI Behavior (RFC-001) | ~45% | ~55% of behavioral surface approximated | 6 of 10 chapters partially implemented |
| Runtime Architecture (RFC-002) | ~10% | ~15% (no runtime foundation exists) | Monolithic orchestrator instead |
| Database (RFC-003) | 0% | RFC is empty; no database exists | JSON files only |
| Engine Interfaces (RFC-004) | 0% | RFC empty; no engine contract exists | No `RuntimeEngine` interface |
| Execution Pipeline (RFC-005) | 0% | RFC empty; fixed pipeline not implemented | Hand-rolled order in one method |
| Memory Architecture (RFC-006) | 0% | RFC empty; memory exists but no DB/vector | Per-user JSON documents |
| Observability & Evals (RFC-007) | 0% | RFC empty; proto-eval tooling exists | Offline judge, no runtime tracing |
| Deployment (RFC-008) | 0% | RFC empty; Docker/Render deploy exists | Not stateless, no DR, no security |
| Implementation (Roadmap) | 0% | Roadmap says "Not Started" | All 6 phases Pending |

**Overall compliance: ~25%.** The project built a substantial *behavioral* surface (RFC-001 intent) on **zero runtime foundation** (RFC-002). The Roadmap explicitly states: *"No AI engine implementation should begin until the Runtime Foundation has been completed and verified"* (IMPLEMENTATION_ROADMAP.md.md:376) and *"Never implement memory before the database schema exists"* (line 28). **Both rules were violated.**

### A.2 Top 10 Critical Risks (priority order)

1. **No authentication + arbitrary `session_id`** — anyone can read/overwrite any user's memory, sessions, reports via `/chat`, `/summary/{id}`, `/report/{id}`, `/reset/{id}` (app.py:19-24, 47-144). Total IDOR on personal wellness data. RFC-002 Ch9 requires "authenticated APIs, authorization" (RFC-002:3919-3923).
2. **Sessions lost on restart, state in-memory** — `_sessions` dict (MAX_SESSIONS=50, FIFO eviction, app.py:15-24); Orchestrator holds ~25 mutable instance fields; Render free tier restarts wipe all sessions. RFC-002 Ch9 mandates *stateless runtime instances* (RFC-002:3683-3695).
3. **JSON-file persistence with no atomicity/locking** — `utils/storage.py` `save_json` writes non-atomically; concurrent requests on the same `user_id` corrupt files (storage.py:20-24). 13 separate JSON documents per user. No database. RFC-002 Ch9: PostgreSQL for users/conversations/commitments/coaching profile, Redis for transient state, vector store for semantic retrieval (RFC-002:3711-3747).
4. **Monolithic orchestrator** — `orchestrator.py` (1,186 lines) mixes emotion, risk, memory, state machine, routing, reasoning, response generation, persistence, judging. RFC-002 Ch1: *Runtime Orchestrator contains no business logic* (RFC-002:244-246). Violated.
5. **No streaming** — zero streaming anywhere; frontend is blocking `fetch`/FormData POST; RFC-002 Ch6 mandates token streaming, first-token <300 ms, barge-in (RFC-002:2397-2827). Violated.
6. **No error recovery architecture** — no retry policy (`max_retries=0` in GroqLLM, llm_service.py:27), no exponential backoff, no circuit breaker, no failure classification, no diagnostics. RFC-002 Ch7 violated.
7. **No observability** — no trace IDs, no per-engine metrics, no percentiles, no alerting, no `/ready` `/metrics` `/version` (only `/health`). RFC-002 Ch8 violated. Engine exceptions propagate as opaque 500s (app.py has zero try/except).
8. **CI tests are a smoke import only** — `.github/workflows/ci.yml` runs `from wellness_agent.orchestrator import Orchestrator`; all real suites live outside the repo. Regression can reach production. RFC-002 Ch8: "Regression SHALL block production deployment" (RFC-002:3463).
9. **XSS surface in frontend** — chat.html renders `data.response` via `innerHTML` (chat.html:240); any LLM output injected as HTML. No Content-Security-Policy.
10. **Docker image ships secrets/data** — `COPY . .` with no `.dockerignore` copies `.env` and `data/` into the image (Dockerfile:9). RFC-002 Ch9: "Secrets SHALL NOT exist in source code" (RFC-002:3818-3829).

### A.3 Strengths (must preserve during migration)

- **LLM boundary discipline is excellent and RFC-aligned:** LLM never decides objectives/hypotheses/interventions/pillars/routing; deterministic engines pre-decide; `reasoning_context.py` (108 lines) enforces the "LLM only writes prose" invariant. Matches RFC-001 Ch5 "SHALL NOT classify intent/manage memory/store slots/generate language" and ADR-003.
- **Safety is deterministic and rule-based:** `RISK_PATTERNS` (23 regexes) in `utils/nlp_utils.py:30-54`, risk short-circuit with hardcoded 988 protocol, crisis override everywhere. Matches RFC-001 Intent 16 (Crisis) and RFC-001 Ch10 Safety Rules.
- **Memory engine quality:** facts with confidence/evidence_count/source_history/contradiction-to-confirmation/decay (memory.py:488) — the closest engine to RFC compliance; differs from RFC-001 Ch4 only in storage substrate.
- **Offline evaluation loop:** `conversation_judge.py` (13 dimensions, deterministic), `simulation/` (8 personas, direct in-process runs), `stress/` (19 scenario definitions), leaderboards — a genuine proto-RFC-007; but no runtime integration.
- **Deterministic engines with persistence:** behavior/belief/hypothesis/why/objective/intervention engines are testable, stateless-in-signature, file-persisted — good raw material for RFC-004 refactoring.

### A.4 Weaknesses (summary)

- No runtime foundation (orchestrator/registry/context/pipeline/streaming/errors/events).
- No database, no schema (RFC-003 empty).
- Config sprawl: every engine hardcodes thresholds/tables; topic keywords duplicated across 6+ files; `config.STATE_TRANSITIONS` is decorative (state machine ignores it).
- Dead code: `TRANSITION_SYSTEM`/`decide_transition` (llm_service.py:97-101), `REPORT_SYSTEM`/`generate_report` LLM path (llm_service.py:215-222) — never called.
- Frontend is static, unauthenticated, no streaming, no history persistence.
- Test suites live outside the repo (`C:\Users\Admin\AppData\Local\Temp\opencode\`); eval index "620 entries" invariant maintained by an out-of-repo script.

### A.5 Effort Remaining

| Phase (Roadmap) | Current State | Estimated Effort to Complete |
|---|---|---|
| Phase 1 — Runtime Foundation | 0% (must be built) | 8–12 engineer-days |
| Phase 2 — Conversation Intelligence | ~40% (objective engine, FSM, planner partial) | 8–10 engineer-days |
| Phase 3 — Memory System (DB) | ~30% of behavior, 0% of substrate | 6–8 engineer-days + infra |
| Phase 4 — Coaching Intelligence | ~50% (traits, why, intervention) | 5–7 engineer-days |
| Phase 5 — Learning System | ~40% (learning.py, judge, reports) | 4–6 engineer-days |
| Phase 6 — Production Hardening | ~10% | 6–10 engineer-days + infra |

---

## B. Current Project Architecture

```
Browser (chat.html, fetch/FormData, innerHTML rendering)
        |  POST /chat  (Form: message, session_id)
        v
app.py (157 lines, 11 routes, no auth/CORS/middleware/lifespan)
        |  _sessions: dict[str, Orchestrator]  (MAX_SESSIONS=50, FIFO eviction)
        v
Orchestrator.process_message(user_message)   <- THE single entry point (orchestrator.py:99)
  |  ~25 instance fields (current_pillar, last_turns[10], avoidance_count,
  |     current_objective, _repeat_count, _judged_objective, ...)
  |  [1] emotion (LLM -> EmotionEngine)        [2] risk short-circuit -> 988 protocol
  |  [3] self-eval previous turn               [4] avoidance counter (2 hits -> rapport)
  |  [5] exit-offer handling                   [6] memory extract (LLM -> rules)
  |  [7] confirmation resolve (deterministic)  [8] trust adjust
  |  [9] state machine transition              [10] route (deterministic + LLM supplement)
  |  [11] reasoning pipeline: behavior -> belief -> hypothesis -> why -> objective
  |       -> reasoning_context
  |  [12] _generate_response decision chain (~16 branches) -> LLM prose (fallback templates)
  |  [13] _save_turn (append session JSON)     [14] auto-judge + learn at conversation end
  v
AgentRegistry (agents.py:101)  <- manual composition root, 17 engines eagerly constructed
  |-- MemorySystem  EmotionEngine  ConversationPlanner  QuestionPlanner
  |-- RootCauseAnalyzer  RoutineGenerator  ObjectiveEngine  BehaviorEngine
  |-- HypothesisEngine  WhyEngine  ProactiveEngine  InterventionRankingEngine
  |-- SelfEvaluator  BeliefEngine  ConversationJudge  LearningLayer  ReportGenerator
  `-- get_agent() legacy map - only 8 of 17 exposed; stale
  v
Persistence: utils/storage.py (load_json/save_json, no atomicity, no lock)
  `-- data/ : 13 JSON docs per user (memory, sessions, behaviors, beliefs,
              hypotheses, whys, evaluations, learning, reports, ...)
  `-- data/evaluations/index.json (620 entries) <- offline eval corpus
```

**Key architectural statement:** there is no "runtime." The Orchestrator *is* the pipeline, the state, the persistence driver, and the LLM caller, all in one class. Engines are not invoked through a contract — they are bound Python objects called directly.

## C. Folder Analysis

Per-file verdict scale: **KEEP** (reusable as-is) / **REFACTOR** (needs modification for RFC compliance) / **REWRITE** (concept must be rebuilt) / **DELETE** (no value or dead).

### C.1 `wellness_agent\` (28 .py files, 7,965 lines)

| File | Lines | Current Responsibility | RFC Mapping | Compliance | Verdict | Priority |
|---|---|---|---|---|---|---|
| `orchestrator.py` | 1,186 | Everything: pipeline, state, persistence, LLM calls | RFC-002 Ch1+Ch5 (Runtime) | **FAIL** — contains business logic; violates "runtime has no business logic" (RFC-002:244); no update-merging, no event bus, no streaming | REWRITE (decompose into Runtime + engines) | CRITICAL |
| `agents.py` | 101 | Manual DI container; 17 eager constructions; ~10 disk loads per `Orchestrator()` | RFC-002 Ch2 (Registry & DI) | **FAIL** — no registry contract, no singleton/scoped separation, no mock support, stale `get_agent` (8 of 17 exposed) | REWRITE (to EngineRegistry) | CRITICAL |
| `llm_service.py` | 256 | Groq client; 9 prompt constants; 8 callers | RFC-002 Ch5/6 (Prompt Builder, LLM invocation) | **FAIL** — no prompt builder, no retries (max_retries=0), no token tracking, no streaming, 2 dead prompts | REFACTOR (to LLM client + PromptBuilder) | HIGH |
| `config.py` | 85 | Static settings, paths, PRODUCT_CONTEXT | RFC-002 Ch9 (env-driven config) | FAIL — hardcoded config prohibited (RFC-002:860); `STATE_TRANSITIONS` unused by state machine | REFACTOR | HIGH |
| `state_machine.py` | 198 | 13-state FSM, flat if-chain | RFC-001 Ch2.7 (Lifecycle) + Ch3 (Branch) | **PARTIAL** — lifecycle approximated; no branch trees, no pause/resume persistence | REFACTOR (to Branch Manager + Lifecycle) | HIGH |
| `conversation_planner.py` | 117 | Pillar selection only | RFC-001 Ch5 (Planner) | **PARTIAL** — planner is a topic picker, not a decision engine; no next-action semantics | REFACTOR | HIGH |
| `objective_engine.py` | 259 | Per-turn objective (1 of 10) with stability | RFC-001 Ch5/6 (Planner+Strategy) | **PARTIAL** — good determinism; no curiosity budget, no pacing modes, no value tracking | REFACTOR (absorb into Planner/Strategy) | MEDIUM |
| `memory.py` | 488 | Facts, confidence, evidence, contradiction-to-confirmation, decay | RFC-001 Ch4 (Knowledge Model) + RFC-006 (empty) | **STRONG PARTIAL** — behavior near-spec; substrate is JSON, no DB/vector; SHALL NOT history-storage respected (sessions file separate) | KEEP (behavior) + REFACTOR (substrate) | MEDIUM |
| `belief_engine.py` | 199 | 7 deterministic belief rules | RFC-001 Ch4 (Beliefs) | PARTIAL — hardcoded lambdas; confidence formula project-specific | KEEP | MEDIUM |
| `hypothesis_engine.py` | 291 | 11 canonical hypotheses; support/contradict/expiry | RFC-001 Ch4 (Hypotheses) + Ch2.6 CCM | PARTIAL — good mechanics; no intent-graph integration | KEEP | MEDIUM |
| `emotion_engine.py` | 172 | Rule-based emotion fallback (19 dims) | RFC-001 Ch2.2 Intent 8 | PARTIAL — fallback role fine; magic numbers | KEEP | LOW |
| `behavior_engine.py` | 501 | 18 traits from phrase evidence; decay; calibration | RFC-001 Ch7 (ACE) | PARTIAL — traits approximate coaching dimensions; no Coaching Profile object, no fingerprint | KEEP + EXTEND | MEDIUM |
| `why_engine.py` | 514 | Recurring co-deviation patterns; confidence 45+7xrepeats | RFC-001 Ch9 (Why Engine) | **PARTIAL** — no root-cause graph, no leading/lagging indicators, no predictions; confidence weights differ from RFC (30/25/20/15/-10) | REFACTOR | MEDIUM |
| `intervention_ranking.py` | 306 | Score = impactx4+urgencyx3+conf/10x2+(10-diff)x1.5 | RFC-001 Ch10 (BIE) | PARTIAL — approximates RFC formula; no readiness estimation, no follow-up plan, no diversity tracking | REFACTOR | MEDIUM |
| `routine_generator.py` | 181 | Canned routines; fallback only | RFC-001 Ch10 | PARTIAL — acceptable fallback; output always re-ranked by intervention engine | KEEP | LOW |
| `root_cause.py` | 219 | Per-pillar RCA chains; correlational caveat | RFC-001 Ch9/10 | PARTIAL — sound fallback; not graph-based | KEEP | LOW |
| `question_planner.py` | 376 | Template question bank (10 pillars x 9 types); options; dedupe | RFC-001 Ch2.4 Algo 12-13 (info gain/cost) | **PARTIAL** — bank is good; random choice instead of information-gain scoring | REFACTOR | MEDIUM |
| `reasoning_context.py` | 108 | Fused decision object passed to LLM; enforces "prose only" | RFC-001 Ch5 + RFC-002 Ch3 (Context) | GOOD — closest thing to a context contract; must survive refactor | KEEP | — |
| `proactive_engine.py` | 202 | Evidence-backed check-in questions | RFC-001 Ch2.7 (resume) | PARTIAL — good; cross-imports `why_engine.SIGNAL_META` | KEEP | LOW |
| `self_evaluation.py` | 256 | Objective success scoring; evaluation track | RFC-001 Ch8 (LCIE) | PARTIAL — deterministic proxy for coaching effectiveness; cross-engine constant imports | KEEP | LOW |
| `conversation_judge.py` | 749 | 13-dim offline conversation scorer; writes eval index | RFC-007 (empty) | **GOOD TOOL** — but not a runtime component; index invariant is manual | KEEP (tooling) | MEDIUM |
| `learning.py` | 321 | Per-user experience: boosts, weights, styles (EMA) | RFC-001 Ch8 (LCIE) | PARTIAL — good privacy (per-user); no outcome classification (Productive/Neutral/...) | REFACTOR | MEDIUM |
| `reports.py` | 668 | WHY-first weekly/monthly/daily reports from engines | RFC-001 Ch8/9 | PARTIAL — strong; LLM report path dead | KEEP | LOW |
| `leaderboards.py` | 157 | Eval aggregates/deltas | RFC-007 (empty) | Tooling; DIMENSIONS duplicated from judge | KEEP (tooling) | LOW |
| `synthetic_data.py` | 178 | Scripted conversations for sims | RFC-007 (empty) | Tooling; includes "adhd-like symptoms"/"medication adherence" categories — **conflicts with product HARD BOUNDARIES** (non-clinical) | KEEP but REMOVE those categories | MEDIUM |
| `__init__.py` | 1 | Version constant | — | — | KEEP | — |
| `utils\storage.py` | 38 | JSON load/save; no atomicity; no lock | RFC-002 Ch9 (persistence) | **FAIL** for concurrency | REWRITE (to StorageInterface; atomic writes; Postgres impl) | CRITICAL |
| `utils\nlp_utils.py` | 119 | Risk patterns, emotion keywords, sentiment, softmax | RFC-001 Ch2.2/16 (Crisis) | **CRITICAL-SAFETY, GOOD** — safety source of truth | KEEP (dedupe copies elsewhere) | — |

### C.2 Other folders

| Path | Verdict | Notes |
|---|---|---|
| `app.py` (157 L) | REWRITE | No auth/CORS/middleware/error handling; `reload=True` in `__main__`; raw `read_text()` HTML |
| `main.py` (CLI REPL) | KEEP | Local debug entry: `/summary /memory /state /report /insight /routine /synthetic /reset` |
| `templates\chat.html` (371 L) | REWRITE | `innerHTML` injection (line 240); no streaming; no history; hardcoded `/chat` |
| `templates\login.html` (66 L) | KEEP (UI) | Name capture only; becomes `session_id` — must be replaced by real auth |
| `static\` (empty) | DELETE | Nothing served, nothing mounted |
| `simulation\` (personas 325 L, simulator 727 L, runner 134 L, evaluate 94 L) | KEEP | Strong offline eval harness; direct in-process import (not HTTP) |
| `stress\` (scenarios 363 L, engine 127 L, runner 178 L, scorer 279 L) | KEEP | 19 scenarios defined but `SCENARIO_IDS` lists 14 — **bug** (scenarios.py:15-20 vs 69-334) |
| `replay_app.py` (8001), `metrics_app.py` (8002) | KEEP | Read-only debug viewers |
| `diff_app.py` (8003) | REFACTOR | Imports and runs production `Orchestrator` — must not ship in image |
| `outcome_app.py` (8004) | REFACTOR | Only debug app that WRITES (`data/outcomes/learned_methods.json`) |
| `data\` (gitignored) | — | 13 stores/user; 54 memory, 63 sessions, 620 eval entries, 629 sim files; `learning/` empty (0 files) |
| `docs\` | REFACTOR | RFC-003..008 empty (0 bytes); `docs/ai/*` + `TESTING_SPEC.md` empty |
| `Dockerfile` | REWRITE | `COPY . .` includes `.env` + `data/`; no `.dockerignore` |
| `render.yaml` | REFACTOR | Free plan (sleeps, no volume); needs DB/Redis/vector + healthcheck |
| `.github/workflows/ci.yml` | REWRITE | Import-smoke "test"; no suite runs; deploy via curl (functional but blind) |
| `.gitignore` | KEEP | `data/`, `.env`, logs, caches correct |
| `.env.example` | KEEP | Correct |
| Root `*.md` (AUDIT_REPORT, ARCHITECTURE_AUDIT, ARCHITECTURE_FLOWCHART, PERFORMANCE_REPORT, PRODUCTION_READINESS_REPORT, TEST_RESULTS, FIXES) | KEEP | Historical; should be consolidated into `docs/` |

---

## D. Engine Analysis

Mandated minimum of 13 engines. Status: **GAP** = does not exist; **PARTIAL** = exists but non-compliant; **GOOD** = exists and largely compliant in behavior (substrate may still be wrong).

### D.1 Runtime Orchestrator — **GAP (implemented as monolith)**
- RFC-002 Ch1: orchestrator SHALL own execution order, lifecycle, diagnostics, retries, persistence, streaming; SHALL contain **no business logic** (RFC-002:244-246); one public `ConversationRuntime.execute(request)` entry (RFC-002:336-341); request-scoped runtime state (RFC-002:400-417); components: EngineRegistry, ContextLoader, PromptBuilder, PersistenceManager, MetricsCollector, EventBus, ErrorHandler, StreamManager (RFC-002:351-363).
- Reality: `Orchestrator.process_message` (orchestrator.py:99-309) performs emotion analysis, risk triage, memory extraction, state transitions, routing, reasoning, response generation, persistence, auto-judging — all business logic. Runtime state persists as ~25 instance fields across requests (violates request-scoped, RFC-002:327). No event emission (RFC-002 Ch5: ConversationStarted/IntentResolved/PlannerCompleted/..., RFC-002:2195-2209). No update-merging (RFC-002:499-517).

### D.2 Intent Resolver — **GAP (distributed, no contract)**
- RFC-001 Ch2.2/2.3/2.4: single `resolveIntent()` interface (RFC-001:1283-1309); 16 intents with confidence thresholds (0.95-1.00 execute; <0.60 must clarify — RFC-001:802-814); intent priority order (Crisis > Correction > ... > Goodbye, RFC-001:1196-1213); Intent Graphs with Primary/Secondary/Background + relationships (RFC-001:1390-1500); 16 deterministic algorithms incl. information gain (Algo 12) and ambiguity-to-clarify (Algo 5, RFC-001:2065-2102).
- Reality: intent is spread across `objective_engine.py` (10 objectives), `orchestrator._decide_route` (line 445, rule + LLM supplement), `conversation_planner.py` (pillar matching), `state_machine.py` (transitions). **No intent object, no confidence, no priority, no graph, no clarification-on-ambiguity, no information-gain scoring.** Greeting/crisis/topic-change/commitment/success/failure handled ad hoc. RFC-001 Ch2.5 acceptance tests (categories A-O) do not exist as tests; some behaviors pass incidentally (free text, skip logic via memory facts).

### D.3 Branch Manager — **PARTIAL (13-state FSM instead of branches)**
- RFC-001 Ch3: single active investigation; preserve unfinished; prevent loops; nested branches; deterministic recovery. Branch SHALL NOT generate responses / store memory / ask questions / recommend.
- Reality: `state_machine.py` flat if-chain over 13 states; `config.STATE_TRANSITIONS` **is decorative — the machine hardcodes its own transitions**. No branch tree, no pause/resume persistence (state lost on restart), no preservation of unfinished investigations across sessions (only `proactive_engine` partially resumes). Violates RFC-001 Ch3 "SHALL NOT generate responses" — state machine is deeply embedded in `orchestrator._generate_response`.

### D.4 Slot Intelligence — **GAP (absent)**
- RFC-001 Ch2.6 CCM Slot State (value/confidence/source/timestamp; mutable until high confidence, RFC-001:3462-3488); Ch2.4 Algorithm 9 (slot extraction); Algorithm 12 (information gain drives question selection).
- Reality: no slot abstraction anywhere. Memory facts are a proxy; the only "slot" is the `deep_investigation` question counter (question_planner.py). No skip-logic scoring, no slot confidence, no "user answers three future questions in one sentence" handling (RFC-001 Test B2).

### D.5 Conversation Planner — **PARTIAL (pillar picker only)**
- RFC-001 Ch5: central decision-maker; SHALL decide next action; SHALL NOT classify intent / manage memory / store slots / generate language; LLM only expresses the decision.
- Reality: `conversation_planner.py` selects a *pillar* (topic), not an action. The actual "next action" is decided inside `orchestrator._generate_response`'s 16-branch chain interleaved with response generation — **planner decision and language generation are fused**, violating RFC-001 Ch5's separation. The one RFC-aligned achievement: objectives/hypotheses/interventions are decided deterministically before the LLM sees them (`reasoning_context.py`).

### D.6 Conversation Strategy — **PARTIAL**
- RFC-001 Ch6: curiosity budget (max consecutive questions: fast 2 / standard 3 / deep 5 — RFC-001:6243-6255); pacing modes (Discovery/Coaching/Reflection/Planning/Maintenance, RFC-001:6310-6324); value categories (8, RFC-001:6184-6201); cognitive load estimation; resistance/silence strategies; info-vs-value ratio; conversation health metrics (RFC-001:6498-6513).
- Reality: `objective_engine.py` per-turn objective with stability is the strongest strategy piece. `state_machine.py` caps questions (deep_investigation max 5). But: no curiosity-budget counter, no pacing mode, no value accounting, no load estimation, no health metrics. Avoidance/deflection handling is present (avoidance_count, exit offers) but heuristic.

### D.7 Memory Engine — **STRONG PARTIAL (behavioral compliance; wrong substrate)**
- RFC-001 Ch4 (Knowledge Model): Facts/Beliefs/Unknowns/Hypotheses separation; SHALL NOT store conversation history; SHALL NOT generate recommendations. RFC-002 Stage 4: MemoryContext profile/episodic/semantic/coaching/insights (RFC-002:1129-1151).
- Reality: `memory.py` (488 L) is the most spec-faithful engine: facts with confidence (init 60), evidence_count, source_history (cap 8), importance scoring (cap 95), contradiction-to-pending-confirmation-to-resolve (never silent overwrite — matches RFC-001 Algo 11), decay rules, pillar coverage. **But**: substrate is one JSON file per user, write-on-every-mutation (write-heavy, non-atomic); no PostgreSQL, no vector retrieval (RFC-002:3737-3747), no episodic/semantic separation. SHALL NOT rules respected (memory never stores raw turns; sessions file does).

### D.8 Adaptive Coaching Engine (ACE) — **PARTIAL**
- RFC-001 Ch7: Coaching Profile per user (RFC-001:6633-6643); 8 styles; coaching dimensions/fingerprint; adaptation signals; recommendation learning; challenge/emotional calibration; coaching memory separate from factual memory; anti-patterns.
- Reality: `behavior_engine.py` infers 18 traits from phrase evidence with decay; `learning.py` blends confidences (EMA) — a functional approximation of a coaching profile. But: no `CoachingProfile` object, no fingerprint, no style taxonomy, no per-recommendation outcome learning on the coaching side, no anti-pattern detection.

### D.9 Why Engine — **PARTIAL**
- RFC-001 Ch9: pattern object (pattern_id/title/observation/explanation/confidence/evidence_count/contradicting_events/status, RFC-001:7677-7695); confidence weights Repetition 30% / Evidence 25% / Time consistency 20% / Cross-source 15% / Contradictions -10% (RFC-001:7797-7809); promotion Candidate->Observed->Confirmed->Core (RFC-001:7813-7835); root-cause graph; leading/lagging indicators; predictions with confidence.
- Reality: `why_engine.py` detects co-deviating signal pairs (confidence = 45 + 7xrepeats, cap 97) and singles — **confidence formula does not match RFC weights**; no pattern-object status lifecycle; no root-cause graph; no leading-indicator logic; no predictions. Contradiction handled at hypothesis level only. Insight *usage* in conversation is good (insight before recommendation).

### D.10 Behavioral Intervention Engine (BIE) — **PARTIAL**
- RFC-001 Ch10: pipeline Problem->RCA->Candidates->Filter unsafe->Estimate readiness->Rank->Select->Follow-up plan->LLM (RFC-001:8105-8145); readiness dimensions (motivation/time/emotional capacity/habit strength/confidence, 0-100); difficulty 1-5; historical effectiveness; formula (Benefit+Success+Readiness+Confidence+Urgency-Difficulty-Load); one primary action; micro-intervention; timing rules (no recs during crisis/before understanding); escalation on repeated failure.
- Reality: `intervention_ranking.py` formula (impactx4+urgencyx3+conf/10x2+(10-difficulty)x1.5) is a reasonable approximation; every recommendation (LLM or template) flows through it; `reason` strings quote user facts; learning weights multiply (0.75-1.25). **Gaps**: no user-readiness estimation (emotion/facts proxy only), no follow-up plan (`follow_up` key absent), no intervention-diversity tracking, no explicit "filter unsafe" step, no escalation on repeated failure (partially in learning weights).

### D.11 Prompt Builder — **GAP (prompts are class constants)**
- RFC-002 Ch5: after pipeline, Prompt Builder assembles RuntimeContext + PlannerDecision + CoachingStyle + WhyInsights + Intervention + RelevantMemory, minimum information only (RFC-002:2116-2129); deterministic; latency <20 ms (RFC-002:2353).
- Reality: 9 prompts hardcoded as class constants in `llm_service.py`; context assembled inline in `orchestrator._generate_question/_generate_response`; no builder module, no versioning, no token budgeting. `PRODUCT_CONTEXT` formatted inline (orchestrator.py:72).

### D.12 Streaming — **GAP (absent entirely)**
- RFC-002 Ch6: Stream Manager; first-token <300 ms; streaming begins immediately after first token (RFC-002:2585-2595); barge-in/interruption; partial-response handling (no duplicate output); timeouts (LLM connect 5 s / first token 3 s / token gap 10 s, RFC-002:2735-2747); retry only before streaming begins.
- Reality: **zero streaming code** in package, frontend, or API. Frontend uses blocking fetch with a typing indicator (chat.html:270-283). Every turn pays full LLM latency before any output. Hard violation of RFC-002 Ch6.

### D.13 Persistence — **GAP (RFC-compliant substrate missing)**
- RFC-002 Ch9: PostgreSQL (users, conversations, commitments, coaching profile, structured knowledge — RFC-002:3711-3721), Redis (locks, cache, rate limiting, queues, streaming metadata — RFC-002:3723-3735), vector store (semantic memory/insight retrieval — RFC-002:3737-3747); runtime instances stateless (RFC-002:3683-3695).
- Reality: `utils/storage.py` — non-atomic JSON writes, no locks, no transactions, no migrations, 13 documents per user, all ephemeral on Render (no volume). No connection pooling, no index, no vector search. RFC-003 (the schema) does not exist. Two concurrent turns on the same `user_id` can corrupt JSON files.

## E. Conversation Flow Analysis

### E.1 Current flow (per turn, orchestrator.py:99-309)

```
POST /chat (Form) -> get_orch() -> process_message()
  1. LLM emotion extract (fallback: EmotionEngine)   2. RISK short-circuit -> 988 protocol
  3. self-eval previous turn (SelfEvaluator)         4. avoidance counter (2 hits -> rapport)
  5. exit-offer handling                              6. memory extract (LLM -> rules)
  7. confirmation resolve (deterministic)             8. trust adjust
  9. state_machine.transition()                      10. _decide_route (base + rules + LLM supplement)
 11. reasoning pipeline: behavior -> belief -> hypothesis -> why -> objective
     -> reasoning_context
 12. _generate_response: ~16-branch chain (greeting / avoidance / category tree /
     question / insight / routine / close / cycler) -> LLM prose (fallback: templates)
 13. _save_turn (append JSON)  14. auto-judge (conversation end) + learning (try/except: pass)
```

### E.2 Required flow (RFC-002 Ch5, RFC-001 Ch2.7)

```
Client -> Auth -> Create RuntimeContext -> Load Conversation (parallel with Memory)
-> Normalize -> [Intent Resolver -> Branch Manager -> Knowledge Engine -> Planner
                 -> Strategy -> ACE -> Why -> BIE] (SEQUENTIAL, fixed)
-> Prompt Builder -> LLM -> Stream response -> Persist (parallel metrics/conversation)
-> Emit events -> Metrics -> Destroy runtime
```

### E.3 Delta table

| Stage | Required (RFC-002) | Current | Gap |
|---|---|---|---|
| Auth | Stage 1 validation | None | Critical |
| RuntimeContext | Immutable, request-scoped | ~25 mutable instance fields | Critical |
| Context/Memory load | Parallel, pre-engine | Inline per-call reads | High |
| Intent Resolver | First engine, deterministic | Distributed, no contract | Critical |
| Branch Manager | Second engine | FSM embedded in generation | High |
| Knowledge Engine | Third engine | Memory (facts) partially covers | Medium |
| Planner/Strategy | 4th/5th, sequential | Fused into response chain | High |
| ACE/Why/BIE | 6th/7th/8th | Present but reordered after objective | Medium |
| Prompt Builder | After pipeline | Inline, constants | High |
| LLM | Streaming, retries, token tracking | Blocking, no retries, no tokens | Critical |
| Streaming | First-token push | None | Critical |
| Persistence | Async, parallel, DB | Sync JSON append | High |
| Events | Async runtime events | None | High |
| Cleanup | Destroy runtime | Fields persist | Medium |

### E.4 Lifecycle compliance (RFC-001 Ch2.7)

- Initializing = greeting (partial); Investigating = guided_discovery/deep_investigation (partial); Exploring = partial (category tree); Reflecting = reflection state (partial); Planning = routine_planning (partial); **Committing — absent** (commitments never captured/reminded; only proactive check-in reads last objective); Closing = follow_up/goodbye (partial); Completed = auto-judge trigger (informal).
- Interruption handling (RFC-001:4217-4248): mid-flight topic changes handled by category tree, but illegal-transition table (RFC-001 Ch2.7) not enforced.
- Timeout recovery (RFC-001:4270-4288): `proactive_engine.checkin()` approximates "summarize + ask continue" but there is no pause/resume persistence.

---

## F. Database Analysis

| Requirement (RFC-002 Ch9 + RFC-003) | Status |
|---|---|
| PostgreSQL: users, conversations, commitments, coaching profile, structured knowledge (RFC-002:3711-3721) | **MISSING** — no database of any kind |
| Redis: locks, cache, rate limiting, queues, streaming metadata (RFC-002:3723-3735) | **MISSING** |
| Vector store: semantic memory, insight retrieval (RFC-002:3737-3747) | **MISSING** |
| Object storage: logs/exports (RFC-002:3749) | MISSING |
| RFC-003 database schema document | **EMPTY (0 bytes)** — the spec does not exist |
| Data integrity: transactions, atomicity, migrations | MISSING — non-atomic JSON writes (storage.py:20-24) |
| Backups / disaster recovery (RFC-002:3898-3909) | MISSING |
| Schema versioning; mismatch blocks startup (RFC-002:3969-3979) | MISSING |
| Current substrate: 13 JSON docs per user under `data/` | Not a database; gitignored; **deleted on every Render restart** (free plan, no volume) |

**Verdict:** the single largest substrate gap. Roadmap Phase 3 (Memory System) requires "PostgreSQL schema, Vector database" (IMPLEMENTATION_ROADMAP.md.md:132-139) and the guiding principle *"Never implement memory before the database schema exists"* (line 28) was violated — `memory.py` and 10 other engines persist user data with no schema, no migration path, no durability. At 1M users: JSON-per-user files cannot scale (filesystem limits, no indexing, no sharding), and session memory loss on restart destroys trust.

---

## G. API Analysis

| Route | Method | RFC-002 Ch9 Requirement | Verdict |
|---|---|---|---|
| `/` (login.html) | GET | Auth | **No auth** — name capture only |
| `/chat` (chat.html) | GET | — | Static file read per request |
| `/chat` | POST | Form: message, session_id | **IDOR**: session_id user-controlled; no validation; 500s propagate raw |
| `/judge/{session_id}` | POST | — | State-mutating, unauthenticated; pollutes eval index with `source:"live"` |
| `/summary/{session_id}` | GET | — | Unauthenticated read of any user's session |
| `/memory/{session_id}` | GET | — | Unauthenticated read of any user's facts (**privacy critical**) |
| `/insight/{session_id}` | GET | — | Unauthenticated |
| `/routine/{session_id}` | GET | — | Unauthenticated |
| `/report/{session_id}` | POST | — | Unauthenticated; state-mutating |
| `/reset/{session_id}` | POST | — | Unauthenticated; destroys a user's session |
| `/health` | GET | Health endpoints (RFC-002:3867-3881) | OK but instantiates `GroqLLM` per call |
| `/ready`, `/metrics`, `/version` | — | REQUIRED (RFC-002:3869-3876) | **MISSING** |

Additional failures:
- No CORS, no middleware, no lifespan/startup hooks, no rate limiting (RFC-002:3921).
- `_sessions` (app.py:15-24): plain dict, FIFO eviction, no TTL; Orchestrator construction loads ~10 JSON files -> cold-start latency.
- Error handling: **zero** try/except in app.py; `orch.process_message()` exceptions -> opaque FastAPI 500.
- Concurrency: no locking — simultaneous POSTs on the same session_id can corrupt JSON stores.

---

## H. Frontend Analysis

| Area | Current | Required | Verdict |
|---|---|---|---|
| Transport | Blocking `fetch` + FormData POST per turn (chat.html:300-308) | Token streaming (RFC-002 Ch6) | **REWRITE** — perceived latency = full LLM latency |
| Rendering | `div.innerHTML = text` (chat.html:240) | Safe DOM/text rendering, CSP | **Critical XSS surface** |
| Options | `.option-btn` buttons re-sending text (chat.html:251-268) | RFC-001 Ch2.2 "buttons become optional" — they already are text | Acceptable |
| Crisis | Hardcoded 988 append on `data.crisis` (chat.html:320-325) | — | OK |
| Session identity | `params.get('user')` -> session_id (chat.html:227-229) | Real auth | REWRITE |
| History | None (refresh = new conversation) | Restore via persisted session | Missing |
| Typing indicator | 3-dot CSS animation (chat.html:270-283) | Replace with real stream | — |
| Login | Static form, no JS (login.html:60-63) | Auth | REWRITE |
| Static assets | `static/` empty; nothing mounted | — | DELETE dir |

---

## I. AI Prompt Analysis

| Prompt (llm_service.py) | Used by | Verdict |
|---|---|---|
| `ROUTER_SYSTEM` (L76) / `route_turn` (L87) | orchestrator `_decide_route` (L445) | SUPPLEMENT ONLY — cannot override deterministic route; acceptable per RFC-001 Ch5, but adds a full LLM call per turn |
| `TRANSITION_SYSTEM` (L97) / `decide_transition` (L101) | **never called** | **DEAD CODE — delete** |
| `MEMORY_SYSTEM` (L111) / `extract_memory` (L117) | orchestrator `_extract_memory` (L421) | Deterministic fallback exists; OK |
| `EMOTION_SYSTEM` (L131) / `extract_emotion` (L140) | orchestrator `_analyze_emotion` (L413) | Temp 0.1; risk guidance "err toward true"; fallback OK |
| `QUESTION_SYSTEM` (L149) / `generate_question` (L166) | orchestrator `_generate_question` (L701) | Temp 0.7, 256 tokens; fallback question bank OK |
| `RCA_SYSTEM` (L177) / `analyze_root_cause` (L184) | orchestrator `_generate_insight` (L906) | Only canonical hypothesis names may be strengthened (L930-932) — **good invariant** |
| `ROUTINE_SYSTEM` (L194) / `generate_routine` (L205) | orchestrator `_generate_routine_suggestion` (L967) | Output always re-ranked by intervention engine — good |
| `REPORT_SYSTEM` (L215) / `generate_report` (L222) | **never called** (reports.py fully deterministic) | **DEAD CODE — delete or wire** |
| `CRISIS_SYSTEM` (L232) / `generate_crisis_response` (L240) | `_risk_response` (L1077) | Fallback = hardcoded 988 text; OK |
| `REFLECTION_SYSTEM` (L246) / `generate_reflection` (L252) | close path | OK |

**LLM client failures:**
- `max_retries=0`, timeout 15 s, no backoff (RFC-002 Ch7 retry policy violated — llm_service.py:27).
- No token tracking (RFC-002 Ch5: "token tracking enabled", RFC-002:2141).
- `_extract_json` (L58) accepts partial dicts silently — fragile.
- **LLM call budget:** full path = up to ~6 LLM calls per turn (emotion, memory, route, question, insight?, routine?) — no budget/circuit-breaker; at 1M users this is cost-critical and latency-critical.
- Prompts are not versioned, not templated, not assembled by a builder; no prompt-vs-prompt A/B evaluation.

**What is GOOD (preserve):** the "LLM expresses only the decision" invariant; every LLM call has a deterministic fallback; risk is never decided by the LLM.

## J. Technical Debt Register

### J.1 Critical

| # | Debt | Evidence | Consequence |
|---|---|---|---|
| C1 | No authentication; full IDOR on all per-user stores | app.py:19-24, 47-144; session_id user-supplied | Any user's wellness data readable/writable by anyone |
| C2 | Non-atomic, unlocked JSON persistence | storage.py:20-24; 13 docs/user | Data corruption under concurrency; total loss on restart |
| C3 | Stateful, non-durable sessions | `_sessions` dict, ~25 orchestrator fields; Render free sleep | Conversations lost; no horizontal scaling (RFC-002 Ch9 stateless violated) |
| C4 | Monolithic orchestrator mixing all concerns | orchestrator.py:99-309 (1,186 L) | Untestable at unit level; violates RFC-002 Ch1 |
| C5 | No streaming | whole repo | User-perceived latency = full LLM time; RFC-002 Ch6 hard violation |
| C6 | No retries/backoff/circuit breaker | llm_service.py:27 (max_retries=0) | Transient LLM failure = degraded turn; no recovery (RFC-002 Ch7) |
| C7 | XSS via innerHTML | chat.html:240 | Malicious LLM/system output executes in user's browser |
| C8 | Docker image contains `.env` + `data/` | Dockerfile:9; no `.dockerignore` | Secret exfiltration risk; image bloat; stale data baked in |
| C9 | CI tests = import smoke only | ci.yml check job | Regressions ship to production; RFC-002 Ch8 "regression blocks deploy" violated |
| C10 | RFC-003..008 empty; DB/memory/observability specs absent | docs/architecture 0-byte files | No target spec to migrate toward; memory-before-DB violation permanent until authored |
| C11 | Opaque 500s; zero error handling in API layer | app.py (no try/except anywhere) | Internal errors/stack traces reach users; no diagnostics (RFC-002 Ch7 "never expose internal errors") |
| C12 | LLM call budget unbounded (~6 calls/turn) | orchestrator LLM call sites | Cost explosion at 1M users; latency stack-up; no circuit breaker |

### J.2 High

| # | Debt | Evidence |
|---|---|---|
| H1 | Config sprawl: thresholds/tables hardcoded in every engine; topic keywords duplicated 6+ files | behavior_engine, orchestrator, memory, conversation_planner, objective_engine, why_engine, learning, intervention_ranking, nlp_utils |
| H2 | `config.STATE_TRANSITIONS` decorative; duplicate transition logic in state machine | config.py:37-51 vs state_machine.py:35-152 |
| H3 | Dead code: `TRANSITION_SYSTEM`/`decide_transition`, `REPORT_SYSTEM`/`generate_report` | llm_service.py:97-101, 215-222 |
| H4 | `stress/scenarios.py`: 19 scenarios but `SCENARIO_IDS` lists 14 (5 never run) | scenarios.py:15-20 vs 69-334 |
| H5 | Eval index "620 entries" invariant maintained by out-of-repo script; live `/judge` pollutes index | Temp\opencode\cleanup_eval_index.py; AGENTS.md:26 |
| H6 | `synthetic_data.py` includes non-clinical categories ("adhd-like symptoms", "medication adherence") conflicting with product HARD BOUNDARIES | synthetic_data.py |
| H7 | Cross-engine constant imports (`why_engine.SIGNAL_META`, `hypothesis_engine.canonical`, behavior_engine phrase tables in self_evaluation) | proactive_engine, orchestrator:930, self_evaluation |
| H8 | No tests inside repo; no `tests/` dir; no pytest config | root listing |
| H9 | Static folder empty; debug apps (8003/8004) run/write production code with no gating | static/; diff_app.py; outcome_app.py:401-414 |
| H10 | Session state not persisted; state machine fields lost on restart | state_machine 14 fields; orchestrator fields |
| H11 | `reload=True` in `__main__` bootstrap | app.py:157 |
| H12 | Duplicate 13-dim lists between judge and leaderboards | conversation_judge.py vs leaderboards.py |
| H13 | Per-request disk I/O: every Orchestrator construction loads ~10 JSON files; `/health` constructs GroqLLM per call | agents.py:21-45; app.py:147-151 |

### J.3 Medium

| # | Debt | Evidence |
|---|---|---|
| M1 | 13 root-level report .md files not consolidated into docs/ | root listing |
| M2 | `learning/` dir empty (0 files) though LearningLayer writes there — feature effectively unused in live runs | data\learning |
| M3 | Judge issues/recommendations keyword-matched; leftover no-op `pass` branch | conversation_judge.py:564-636, 598-600 |
| M4 | `_extract_json` silently accepts partial dicts | llm_service.py:58 |
| M5 | Inline `import logging` inside methods; no structured logger | orchestrator.py:657, 669, 682 |
| M6 | `try/except: pass` around `_learn_from_conversation` (silent swallow) | orchestrator.py:385 |

### J.4 Low

| # | Debt | Evidence |
|---|---|---|
| L1 | Magic numbers throughout engines (deltas, thresholds) with no constants table | behavior_engine, emotion_engine, self_evaluation, ... |
| L2 | Type coercion/normalization duplicated (4/5-tuple fact forms) | agents.py:60-93 |
| L3 | `state_machine` has `set_state` without validation of transition legality | state_machine.py:194 |

---

## K. Migration Plan

Order follows the Roadmap (foundation before engines; memory after DB). Each task is <=1 engineer-day, single subsystem, with acceptance criteria. Dependency = must-complete-first task IDs.

### Phase 1 — Runtime Foundation (Roadmap Phase 1)

| ID | Task | Affected Files | Depends On | Why | Acceptance Criteria | Effort | Risk |
|---|---|---|---|---|---|---|---|
| M1 | Author RFC-003 (Database Schema): users, conversations, commitments, coaching profile, structured knowledge tables + vector/memory tables; schema versioning | docs/architecture/RFC-003_DATABASE_SCHEMA.md.md | — | Roadmap Phase 3 gate; RFC-002 Ch9 lists required stores; current docs empty | Document with full DDL, version field, migration strategy; roadmap updated to mark RFC-003 complete | 1 d | Low |
| M2 | Author RFC-004 (Engine Interfaces): RuntimeEngine contract, EngineUpdate, metrics, result states, retry policy | docs/architecture/RFC-004_ENGINE_INTERFACES.md.md | M1 | RFC-002 Ch4 mandatory contracts | Spec matches RFC-002 Ch4 exactly; engines enumerated with signatures | 1 d | Low |
| M3 | Author RFC-005 (Execution Pipeline) + RFC-006 (Memory) | RFC-005/006 .md.md | M2 | RFC-002 Ch5 pipeline + Ch4 memory context; both empty | Pipeline stages/order/latency budgets; MemoryContext structure | 1 d | Low |
| M4 | Author RFC-007 (Observability & Evals) + RFC-008 (Deployment) | RFC-007/008 .md.md | M2 | RFC-002 Ch8/Ch9; both empty | Trace model, metrics, alerts; stateless deployment topology | 1 d | Low |
| M5 | StorageInterface: atomic write (temp+rename), file lock, JSON impl; engines depend on interface not on storage module | wellness_agent/utils/storage.py + all engine constructors | M1 | C2/C3 — concurrency corruption; substrate swap later | Two concurrent writers on same user file lose no data; all suites pass | 1 d | Medium |
| M6 | RuntimeContext (immutable, request-scoped) + EngineUpdate + RuntimeEngine Protocol; wrap the 12 deterministic engines with `execute(input, ctx) -> EngineUpdate` | new wellness_agent/runtime/; engine modules | M2, M5 | RFC-002 Ch3 immutable context; RFC-002 Ch4 contract | Every engine exposes execute(); unit tests with mocked deps; no engine mutates context | 1 d | Medium |
| M7 | EngineRegistry + DI (replace AgentRegistry): register once, resolve by interface, lazy init, mocks | agents.py -> registry; orchestrator | M6 | RFC-002 Ch2; kills ~10 disk loads per Orchestrator() | No engine instantiates another; registry diagnostics (version/health); tests use mocks | 1 d | Medium |
| M8 | Decompose orchestrator.py: runtime orchestrator (no business logic) + decision logic moved into engines; fixed execution order per RFC-002 Ch5 | orchestrator.py -> runtime/orchestrator.py + engine modules | M6, M7 | C4 — RFC-002 Ch1 "no business logic" | process flow = validate -> load -> 8 engines sequential -> prompt -> LLM -> persist -> events; orchestrator <250 lines; all offline suites pass | 1-2 d | High |
| M9 | LLM client hardening: retry+exponential backoff, per-call timeout config, token tracking, structured errors | llm_service.py | M8 | C6 — RFC-002 Ch7 retry policy | max_retries configured (>=2), backoff visible in metrics, token usage recorded per call | 1 d | Low |
| M10 | PromptBuilder module: assemble context+decision+style+insights+intervention+memory; deterministic; min info | new wellness_agent/prompt_builder.py; llm_service.py | M8, M9 | D11 — RFC-002 Ch5 prompt assembly; removes inline context | Identical inputs -> identical prompts; <20 ms; prompts versioned | 1 d | Low |

### Phase 2 — Conversation Intelligence (Roadmap Phase 2)

| ID | Task | Affected Files | Depends On | Why | Acceptance Criteria | Effort | Risk |
|---|---|---|---|---|---|---|---|
| M11 | Intent Resolver: 16 intents, confidence, priority, ambiguity->clarify, intent graph; port RFC-001 Ch2.5 categories A-O as pytest | new wellness_agent/intent_resolver.py; objective_engine.py slimmed | M8 | D2 — GAP; RFC-001 Ch2.2-2.4 | All Ch2.5 tests A-O pass; same input -> same intent | 1 d | Medium |
| M12 | Slot Intelligence: slot state (value/confidence/source/timestamp), extraction, information-gain question scoring | new wellness_agent/slot_resolver.py; question_planner.py | M11, M10 | D4 — GAP; RFC-001 Algo 9/12 | "I've been sleeping five hours for two weeks" fills 2 slots; skip-logic works; highest-gain question chosen | 1 d | Medium |
| M13 | Branch Manager: branch tree, pause/resume persistence, unfinished-investigation preservation, loop prevention | state_machine.py -> branch_manager.py | M11 | D3 — RFC-001 Ch3 | Topic change preserves progress across sessions; completed branches stay closed; no loops | 1 d | Medium |
| M14 | Conversation Planner/Strategy: planner decides next action (not pillar); strategy adds curiosity budget, pacing modes, value accounting, health metrics | conversation_planner.py, objective_engine.py merge | M12, M13 | D5/D6 — RFC-001 Ch5/6 | Action decided pre-LLM; budget caps questions (2/3/5); every response carries a value category | 1 d | Medium |

### Phase 3 — Memory System + Database (Roadmap Phase 3)

| ID | Task | Affected Files | Depends On | Why | Acceptance Criteria | Effort | Risk |
|---|---|---|---|---|---|---|---|
| M15 | PostgreSQL schema migration (from RFC-003 DDL) + PostgresStorage implementation behind StorageInterface; data migration script for JSON stores | storage.py -> db/storage.py; migrations/ | M5, M1 | F — largest substrate gap; C2/C3 | All engines run unchanged against Postgres; memory survives restart; migration preserves existing 13 stores | 1 d | Medium |
| M16 | Redis integration: session state, distributed locks, rate limiting, cache | app.py, registry | M15 | RFC-002 Ch9 Redis; C3 stateless | Two instances serve the same conversation; rate limit enforced; locks prevent double-write | 1 d | Medium |
| M17 | Vector store for semantic memory/insight retrieval; MemoryContext (profile/episodic/semantic/coaching/insights) | memory.py + db/vector.py | M15 | RFC-002 Stage 4 memory loading; D7 | Retrieval returns relevant facts before engine execution; latency <40 ms target (RFC-002:2352) | 1 d | Medium |

### Phase 4 — Coaching Intelligence + Streaming (Roadmap Phases 4 & 6)

| ID | Task | Affected Files | Depends On | Why | Acceptance Criteria | Effort | Risk |
|---|---|---|---|---|---|---|---|
| M18 | Streaming: StreamManager + SSE endpoint `/chat/stream`; first-token push; cancellation; partial-response no-duplicate | new runtime/streaming.py; app.py; chat.html | M8, M9 | C5 — RFC-002 Ch6 hard violation | First token <300 ms; tokens flow before completion; interrupt cancels; no duplicate output | 1-2 d | Medium |
| M19 | ACE coaching profile: profile object, fingerprint, styles, per-recommendation outcome learning, anti-patterns | behavior_engine.py, learning.py | M14 | D8 — RFC-001 Ch7 | Distinct fingerprints per user; recommendation outcomes update profile; anti-patterns detected | 1 d | Medium |
| M20 | Why Engine alignment: RFC confidence weights, pattern status lifecycle, root-cause graph, leading indicators, predictions with confidence | why_engine.py | M17 | D9 — RFC-001 Ch9 | Confidence formula matches RFC weights; patterns promote Candidate->Observed->Confirmed->Core; predictions include confidence | 1 d | Medium |
| M21 | BIE readiness: readiness estimation (0-100), follow-up plan, diversity tracking, filter-unsafe step, escalation | intervention_ranking.py | M20 | D10 — RFC-001 Ch10 | Readiness dimension output; follow_up present; repeated failure triggers difficulty reduction not repetition | 1 d | Medium |
| M22 | Observability: traceId, structured JSON logs, per-engine latency, `/ready` `/metrics` `/version`, alerting hooks | runtime/observability.py; app.py | M8, M4 | C11/H — RFC-002 Ch8 | Every request traceable; P50/P90/P95 exposed; regression gate in CI | 1 d | Low |
| M23 | Security: auth (session token), rate limiting, input validation, CORS, CSP; fix IDOR | app.py, chat.html, login.html | M16 | C1/C7 — privacy critical | No endpoint accepts raw user_id for other users' data; XSS test passes; 429 on burst | 1 d | Medium |
| M24 | Docker hygiene: `.dockerignore` (data/, .env, logs, tests), secrets env-only, debug apps gated behind env flag | Dockerfile, .dockerignore, render.yaml | — | C8 — secrets in image | Image build contains no .env/data; secret scan clean | 0.5 d | Low |
| M25 | CI: move offline suites into repo `tests/`, pytest runner in check job, eval regression gate blocks deploy | tests/; ci.yml | M4 | C9 — regressions ship today | CI runs full offline suite (memory/coaching/learning/stress); failing gate blocks deploy | 1 d | Low |
| M26 | Dead code + cleanup: remove TRANSITION_SYSTEM/REPORT_SYSTEM paths, fix SCENARIO_IDS 14->19, remove non-clinical synthetic categories, consolidate root reports into docs/ | llm_service.py, scenarios.py, synthetic_data.py, root md files | — | H3/H4/H6/M1 | grep dead prompts = 0; stress runner covers 19 scenarios | 0.5 d | Low |

**Ordering rationale:** M1-M4 (spec authoring) gate everything because RFC-003..008 are empty — the roadmap's "update the RFC before code" rule applies. M5-M10 build the runtime foundation the roadmap demands before any engine work. M11-M14 fix the intelligence layer. M15-M17 land the database substrate (roadmap gate: memory before DB violated — corrected here). M18-M23 deliver streaming, coaching depth, observability, and security. M24-M26 are hygiene.

---

## L. Reuse Report

### L.1 Safe To Keep (adopt into new architecture as-is or near-as-is)

| Item | Why | Caveat |
|---|---|---|
| `utils/nlp_utils.py` | Safety source of truth (RISK_PATTERNS); deterministic; zero deps | Make it the ONLY risk lexicon; remove copies |
| `memory.py` (behavior) | RFC-001 Ch4-aligned facts, contradiction->confirmation, decay | Swap storage substrate; keep logic |
| `belief_engine.py`, `hypothesis_engine.py` | Clean deterministic update/read; persistence | Add execute() wrapper (M6) |
| `behavior_engine.py` (traits) | Evidence-based trait learning with decay | Extend to Coaching Profile (M19) |
| `intervention_ranking.py` | Scoring + fact-quoting reasons; learning weights | Add readiness/follow-up (M21) |
| `objective_engine.py` | Deterministic objective selection with stability | Absorb into Planner/Strategy (M14) |
| `reasoning_context.py` | Enforces LLM-prose-only invariant | Preserve verbatim; becomes part of RuntimeContext |
| `conversation_judge.py`, `leaderboards.py`, `simulation/`, `stress/`, `synthetic_data.py` (minus 2 categories) | Mature offline eval loop | Convert suites into in-repo tests (M25); keep index invariant but enforce in CI |
| `question_planner.py` (bank) | Large deterministic question bank | Add info-gain scoring (M12) |
| `proactive_engine.py`, `root_cause.py`, `routine_generator.py`, `reports.py`, `self_evaluation.py`, `emotion_engine.py` | Good fallbacks; engine-shaped | Wrap in contract (M6) |

### L.2 Needs Refactor

| Item | Refactor |
|---|---|
| `orchestrator.py` | Decompose into runtime orchestrator + engines (M8) — the biggest refactor |
| `agents.py` | Replace with EngineRegistry (M7) |
| `llm_service.py` | Split into LLM client (retries/streaming/tokens) + PromptBuilder (M9/M10) |
| `app.py` | Auth, error handling, streaming, health endpoints (M18/M22/M23) |
| `state_machine.py` | Rebuild as Branch Manager + lifecycle states (M13) |
| `config.py` | Externalize all thresholds/tables; env-driven (H1) |
| `conversation_planner.py` | Expand from pillar picker to action planner (M14) |
| `why_engine.py` | RFC confidence weights, graph, indicators, predictions (M20) |
| `learning.py` | Add outcome classification (Productive/Neutral/...) per RFC-001 Ch8 |
| `utils/storage.py` | StorageInterface + atomicity (M5), then Postgres impl (M15) |
| `chat.html` | Safe rendering, streaming, auth flow (M18/M23) |
| `stress/scenarios.py` | SCENARIO_IDS 14->19 (M26) |
| `diff_app.py` / `outcome_app.py` | Gate behind env flag; exclude from image (M24) |
| `render.yaml` | Paid plan + DB/Redis/vector services + healthcheck (M15/M16) |

### L.3 Replace Completely

| Item | Replace With |
|---|---|
| JSON persistence substrate | PostgreSQL + Redis + vector store (RFC-002 Ch9) |
| In-memory `_sessions` dict | Redis-backed session store (stateless runtime) |
| Inline prompt assembly | PromptBuilder module (RFC-002 Ch5) |
| `config.STATE_TRANSITIONS` dead table | Lifecycle state machine per RFC-001 Ch2.7 |
| `TRANSITION_SYSTEM` / `REPORT_SYSTEM` prompts | Deleted (dead code) |
| `static/` empty dir | Deleted |

---

## M. Final Readiness Scores (0-100)

| Dimension | Score | Justification |
|---|---|---|
| Architecture | **25** | Behavioral layers present; no runtime; RFC-003..008 empty; roadmap order violated |
| Runtime | **10** | No registry/context/pipeline/events; monolithic orchestrator; request state leaks across turns |
| Conversation Intelligence | **45** | Good deterministic engines (objective, FSM, question bank); intent/slots/branches/strategy formally absent |
| Memory | **40** | Behavior strong (facts/contradiction/decay); substrate JSON-only, no DB/vector, non-durable |
| Coaching | **50** | Traits + why + intervention ranking functional; no profile/fingerprint/readiness/follow-up |
| Streaming | **0** | Entirely absent (API, runtime, frontend) |
| Database | **0** | No database, no schema, RFC-003 empty |
| Observability | **15** | Excellent offline eval tooling; zero runtime tracing/metrics/alerting |
| Production Readiness | **15** | No auth/rate-limit/CORS; sessions ephemeral; CI blind; Docker ships secrets |
| **Overall Readiness** | **22** | Not production-ready for any scale; at 1M users the current architecture fails on every substrate dimension |

---

## N. Next Recommended Milestone

**Milestone: "Phase 1 — Runtime Foundation (RFC-compliant)."**

Scope (from the Migration Plan): M1 (author RFC-003 schema) + M2 (RFC-004 engine interfaces) + M5 (atomic StorageInterface) + M6 (RuntimeContext + EngineUpdate + RuntimeEngine contract) + M7 (EngineRegistry/DI) + M8 (decompose orchestrator into a business-logic-free runtime). M9/M10 (LLM client + PromptBuilder) follow immediately.

Justification:
1. The Roadmap is explicit and authoritative: *"Begin Phase 1 — Runtime Foundation. No AI engine implementation should begin until the Runtime Foundation has been completed and verified"* (IMPLEMENTATION_ROADMAP.md.md:372-376).
2. RFC-003..008 must exist before any DB/memory work (M1-M4) — the current "memory before database schema" violation is frozen in place until then.
3. Every other critical risk (streaming, auth, scaling, observability) depends on the runtime contract existing first — engines cannot be wrapped, parallelized, or instrumented until the RuntimeEngine contract (M6) exists.
4. The deterministic engines are the project's strength and will survive the refactor as first-class RFC-004 engines with zero behavioral loss — suites memory_test/coaching_test/learning_test/phase6_stress100 must stay green throughout.

Exit criteria for the milestone: runtime starts, context loads, engines execute in RFC-002 Ch5 order through the registry, updates merge immutably, offline suites pass, and the orchestrator contains no business logic.


