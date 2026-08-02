# Intent Resolver 2.0 Summary (AI Intelligence Phase)

**Spec:** `docs/architecture/RFC-001_ADAPTIVE_CONVERSATION_ORCHESTRATOR.md`
(Chapter 2 — Intent Resolution: 2.1 execution order, 2.2 Intent Object,
2.3 IntentGraph & relationships, 2.4 algorithms, 2.5 acceptance tests)
**Scope:** replace single-intent detection with a deterministic adaptive
Intent Resolver. Branch Manager / Planner / Coach / Memory / Runtime
foundation stay frozen; only the resolver and its wiring change.
**Status:** COMPLETE — unit + adversarial suites pass, full regression green.

---

## 1. What was built

### 1.1 `wellness_agent/runtime/intent_resolver.py` (new)
- **Intent object** (RFC Ch2.2): intent, confidence, priority, level,
  slot_updates, notes, evidence; `to_dict()` for the runtime contract.
- **IntentGraph** (RFC Ch2.3): primary / secondary / background intents,
  relationships, overall_confidence and conversation flags
  (`continue_branch`, `branch_change_requested`, `answered_current_question`,
  `new_slots_detected`, `topic_shift`, `emotion_shift`, `interruption`,
  `correction`, `requires_clarification`, `reason`, `reasoning`).
- **Relationships**: `cause` (with cause-clause re-ranking), `conflict`
  (memory contradiction), `reinforcement` (co-occurring emotions).
- **`resolve_intents(message, *, active_branch, previous_question,
  last_turns, memory_facts, current_state)`** — pure, deterministic.
- **`IntentResolverEngine(BaseEngine)`** — returns `EngineUpdate` owning the
  `intent_graph` context field; never reads/writes `RuntimeContext` directly
  (verified by tests). Diagnostics: `IntentGraphBuilt` / `IntentAmbiguous`.

### 1.2 Intent catalogue
crisis, correction, commitment, goal_update, answer, confirmation,
emotional_expression, topic_change, clarification, additional_information,
question, success, failure, rejection, meta, greeting, small_talk, goodbye,
unknown — with RFC priorities and confidence bands (>=0.80 high,
0.60-0.79 medium, 0.40-0.59 low/clarify, <0.40 unknown).

### 1.3 Behaviors implemented
- Free text over buttons: answers to pending questions with slot extraction
  (sleep_hours, duration, stress_level, energy_level, exercise_times).
- Multi-intent graphs with cause/reinforcement/conflict relationships;
  cause clauses re-rank the leading effect above the trail cause.
- Branch continuity (additive "also" and family topics) vs explicit
  topic change ("I actually want to talk about work", "Forget stress...").
- Corrections: marker + memory contradiction -> `conflict` relationship;
  marker without contradiction stays informational; same value is not a
  correction; "actually" inside a topic change is not a correction.
- Interruptions: non-answer to a pending question.
- Emotional vs task separation: emotion labels resolve to
  `emotional_expression`, never to topics; negated emotions are dropped.
- Negation is clause-boundary aware ("not stressed but my sleep is broken").
- Crisis overrides everything (rule-based `RISK_PATTERNS` — never LLM).
- Idioms ("I will sleep on it"), deflections ("I dont know", "..."),
  confirmations, questions, greetings, goodbyes, unknown with clarification.

### 1.4 Wiring
- `orchestrator.py`: registers `intent_resolver` first; `_process_turn`
  accepts `intent_graph` and prepends it to the turn dict; `_runtime_stages()`
  builds a 2-stage pipeline (`intent_resolver` -> `conversation`) with
  context-rich resolver inputs (last turns, memory facts, active branch).
- `runtime/conversation_engine.py`: passes `intent_graph` to the wrapped
  flow when the callable accepts it (M8 1-arg wrappers unchanged).
- `runtime/runtime_orchestrator.py`: stages execute and merge one at a time
  so the conversation stage sees the resolver's graph; `_DEFAULT_STAGES`
  remains the M8 single-stage default.
- `runtime/__init__.py`: exports `INTENT_PRIORITIES`, `Intent`,
  `IntentGraph`, `IntentRelationship`, `IntentResolverEngine`,
  `resolve_intents`.

## 2. Verification
- `tests/test_intent_resolver.py` — 34 unit tests (RFC Ch2.5 acceptance).
- `tests/test_intent_resolver_adversarial.py` — 24 adversarial tests
  (negations, idioms, substring traps, deflections, ambiguity, immutability).
- Full regression: storage 12/12, runtime_engine 22/22, engine_registry
  15/15, merge 12/12, pipeline 12/12, orchestrator 9/9, conversation_runtime
  7/7, integration 6/6; memory/coaching/learning ALL PASS;
  phase6 stress100 mean 82.0 (baseline); CI imports OK; eval index 620.
- End-to-end: `/chat`-equivalent turns produce `intent_graph` in the turn
  dict; topic change triggers `branch_change_requested`; crisis sets risk.

## 3. Out of scope (unchanged)
Branch Manager, Planner, Coach, Memory, Hypothesis/Why engines, LLM
decisions, safety detection (still rule-based), persistence writes.
