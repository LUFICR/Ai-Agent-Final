# Architecture Audit — Wellness Companion AI Agent

Audited repository root: `C:\test` (copied from `C:\Users\Admin\Downloads\final ai agent`)
Audit date: 2026-07-31
Version marker: `wellness_agent/__init__.py` → `WELLNESS_AGENT_VERSION = "1.0.0"`

> This is a descriptive + analytical audit. Nothing in the audited repo was modified.

---

## SECTION 1 — PROJECT OVERVIEW

### Tech stack

| Layer | Technology | Version constraint |
|---|---|---|
| Language | Python | 3.12 target (Dockerfile `python:3.12-slim`); runs on 3.14 locally |
| Web framework | FastAPI (`fastapi`) | `>=0.115.0` |
| ASGI server | uvicorn | `>=0.32.0` |
| LLM provider SDK | `groq` | `>=0.12.0` |
| LLM model | `llama-3.3-70b-versatile` | hardcoded default in `llm_service.py:19` |
| Templating | jinja2 (dependency declared) | **declared but never used** — HTML templates are served via `Path.read_text()` |
| Form parsing | python-multipart | `>=0.0.12` |
| Env loading | python-dotenv | `>=1.0.0` |
| Persistence | **None** — flat JSON files on disk | no database of any kind |
| Frontend | Vanilla HTML/CSS/JS (no framework, no build step) | — |

### Frameworks / patterns

- **Agent orchestration**: custom "multi-agent" pattern. There is no agent framework (no LangChain, no CrewAI). "Agents" are plain Python classes registered in `AgentRegistry` (`wellness_agent/agents.py`).
- **State machine**: hand-rolled deterministic conversation state machine (`wellness_agent/state_machine.py`, transitions in `wellness_agent/config.py`).
- **LLM integration**: a single thin wrapper class `GroqLLM` (`wellness_agent/llm_service.py`) with ~10 prompt templates. **No function/tool calling is used** — the LLM is only used for text→JSON classification/generation, and every LLM call has a rule-based fallback.
- **Web**: FastAPI with synchronous handler logic inside `async def` endpoints (event-loop blocking, see Section 15).

### Folder structure

```
C:\test
├── app.py                         # FastAPI web entry point
├── main.py                        # CLI entry point
├── requirements.txt
├── Dockerfile                     # Deploy image (python:3.12-slim)
├── render.yaml                    # Render.com deploy config
├── .env                           # GROQ_API_KEY (gitignored)
├── .env.example
├── .gitignore                     # ignores data/sessions, data/memory, .env, __pycache__
├── AUDIT_REPORT.md                # prior manual audit notes
├── FIXES.md                       # prior fix plan (unverified status)
├── .github/workflows/ci.yml       # CI: import smoke test + Render deploy trigger
├── templates/
│   ├── login.html                 # name-entry page
│   └── chat.html                  # chat SPA (single-file, inline CSS/JS)
├── data/
│   ├── memory/   <user_id>_memory.json    (per-user long-term memory)
│   ├── sessions/ <user_id>_session.json   (per-user turn log)
│   └── reports/  <user_id>_<period>.json  (created on demand; empty at audit time)
├── wellness_agent/
│   ├── __init__.py
│   ├── config.py                  # constants: pillars, states, transitions, system prompt
│   ├── llm_service.py             # GroqLLM — ALL prompts live here
│   ├── orchestrator.py            # the entire turn pipeline (661 lines)
│   ├── agents.py                  # AgentRegistry (composition root)
│   ├── state_machine.py           # deterministic transitions
│   ├── emotion_engine.py          # rule-based emotion scoring fallback
│   ├── memory.py                  # JSON memory store + regex fact extraction
│   ├── conversation_planner.py    # pillar selection heuristics
│   ├── question_planner.py        # question templates per pillar/type
│   ├── root_cause.py              # rule-based causal chain builder
│   ├── routine_generator.py       # canned routine templates
│   ├── reports.py                 # deterministic report generator
│   ├── synthetic_data.py          # scripted test conversation generator
│   └── utils/
│       ├── storage.py             # load_json/save_json/now_iso/days_since/merge_dicts
│       ├── nlp_utils.py           # keyword lexicons + regex detectors
│       └── __init__.py            # (empty)
```

### Main entry points

1. **`app.py`** — FastAPI app. Started via `uvicorn app:app --host 0.0.0.0 --port 8000` (Dockerfile CMD) or `python app.py` (dev mode, `reload=True`). Serves login page, chat page, and a JSON API.
2. **`main.py`** — REPL CLI wrapper around the same `Orchestrator`, with slash commands (`/summary`, `/memory`, `/state`, `/report`, `/insight`, `/routine`, `/synthetic`, `/reset`).

### Build system

None. `requirements.txt` is the only dependency manifest; `pip install -r requirements.txt` is the build. No pyproject/setup.py, no tests, no lint config.

### Environment variables

| Variable | Required | Read where | Effect |
|---|---|---|---|
| `GROQ_API_KEY` | Yes | `llm_service.py:20` | Enables LLM; without it the whole system runs rule-based |
| `PORT` | No | `app.py:125`, Dockerfile CMD | HTTP port (default 8000) |
| `GROQ_MODEL` | No | **never read** | Documented in `.env.example` but dead config — model is hardcoded in `GroqLLM.__init__` |
| `APP_NAME`, `HOST` | No | **never read** | Documented in `.env.example`; dead config |
| `RENDER_API_KEY` | Yes (deploy only) | `.github/workflows/ci.yml` | GitHub secret used to trigger Render deploys |

### External services

- **Groq API** — the only external dependency. All LLM traffic flows here (`client.chat.completions.create`).
- **Render.com** — deployment target (web service `wellness-companion`, `render.yaml`), deployed via CI webhook.
- **GitHub Actions** — CI (import smoke test) + deploy trigger.

---

## SECTION 2 — AI ARCHITECTURE: LIFECYCLE OF ONE USER MESSAGE

> There is **no tool calling** in this system (Section 6). The pipeline is: frontend → REST → one synchronous Python pipeline → JSON response.

### 2.1 End-to-end flow

```
User
 ↓ (types / taps an option button)
templates/chat.html (sendMessage → fetch POST /chat, FormData: message, session_id)
 ↓
app.py POST /chat  (async def chat → calls orch.process_message() — blocking)
 ↓
Orchestrator.process_message(user_message)            [orchestrator.py:81]
 │
 ├─ 1. _analyze_emotion(message)                      [orchestrator.py:202]
 │      llm.extract_emotion()  → JSON scores           [llm_service.py:140 EMOTION_SYSTEM]
 │      fallback: EmotionEngine.analyze() (regex+lexicon heuristics) [emotion_engine.py:13]
 │
 ├─ 2. risk_flag check → SHORT-CIRCUIT crisis path     [orchestrator.py:100]
 │      _risk_response() → llm.generate_crisis_response() or canned 988 text
 │      (risk detection itself: LLM risk_flag, or RISK_PATTERNS regex in nlp_utils.py:30)
 │
 ├─ 3. Deterministic avoidance counter                 [orchestrator.py:110-128]
 │      short message + no topic keyword → avoidance_count++
 │
 ├─ 4. Exit-offer handler (one-shot, _exit_offered)    [orchestrator.py:136-161]
 │
 ├─ 5. _extract_memory(message, emotion)               [orchestrator.py:210]
 │      llm.extract_memory() → fact list                [llm_service.py:117 MEMORY_SYSTEM]
 │      fallback: agents.extract_and_store() → memory.extract_facts_from_message() (regex)
 │      → memory.add_fact() / update_fact() (JSON write, per fact)
 │
 ├─ 6. Trust score adjustment (avoidance −3, engagement +2) [orchestrator.py:167-170]
 │
 ├─ 7. state_machine.transition(emotion, message)      [state_machine.py:20]
 │      deterministic rule table, no LLM
 │
 ├─ 8. _decide_route(emotion, message)                 [orchestrator.py:233]
 │      base route ["emotion_detection","memory_manager"]
 │      + state rules (question_planner / root_cause_engine / routine_generator)
 │      + optional LLM supplementation: llm.route_turn()  [llm_service.py:87 ROUTER_SYSTEM]
 │        (LLM can add agents, cannot remove base/state agents)
 │
 ├─ 9. _generate_response(route, emotion, message)     [orchestrator.py:269]
 │      giant if/elif dispatch: greeting → avoidance branches →
 │      category quick-tree (fuzzy match) → question_planner →
 │      root_cause → routine → reflection → response cyclers
 │      Each branch may call LLM first, fallback to templates:
 │        - questions:  llm.generate_question()  → QuestionPlanner.generate_question()
 │        - insight:    llm.analyze_root_cause() → RootCauseAnalyzer.analyze()
 │        - routine:    llm.generate_routine()   → RoutineGenerator.generate()
 │        - reflection: llm.generate_reflection()→ reflection_response()
 │      Repetition safeguard (verbatim-repeat detection, forced variant/state break)
 │
 └─ 10. _save_turn() — append turn to data/sessions/<user>_session.json (full-file rewrite)
      turn_result → app.py serializes {response, options, state, emotion, risk, llm, pillar, crisis}
 ↓
templates/chat.html renders message + option buttons (div.innerHTML — see Section 15 XSS)
 ↓
User
```

### 2.2 Files involved (complete list)

| File | Role in pipeline |
|---|---|
| `templates/chat.html` | UI; POSTs `message` + `session_id`; renders options; no websocket/streaming |
| `app.py` | REST API; owns in-memory `_sessions: dict[str, Orchestrator]`; routes |
| `wellness_agent/orchestrator.py` | The entire turn lifecycle (steps 1–10 above) |
| `wellness_agent/llm_service.py` | Every LLM call, all prompt templates, JSON extraction, fallback flag |
| `wellness_agent/agents.py` | Composition root `AgentRegistry`; `extract_and_store`; reflection templates |
| `wellness_agent/state_machine.py` | State transition decisions (step 7) |
| `wellness_agent/memory.py` | Long-term fact store + regex fallback extraction + trust score |
| `wellness_agent/emotion_engine.py` | Rule-based emotion fallback (step 1) |
| `wellness_agent/nlp_utils.py` (in utils) | Keyword lexicons, avoidance/risk regex, sentiment |
| `wellness_agent/conversation_planner.py` | Pillar targeting when no pillar is selected |
| `wellness_agent/question_planner.py` | Template question bank + state option rules |
| `wellness_agent/root_cause.py` | Rule-based insight fallback |
| `wellness_agent/routine_generator.py` | Rule-based routine fallback |
| `wellness_agent/config.py` | States, transitions, pillars, `PRODUCT_CONTEXT` system prompt |
| `wellness_agent/utils/storage.py` | JSON read/write, timestamps |

### 2.3 Key architectural facts

- **Prompt building** is minimal: each LLM call is stateless. The only context injected is a `json.dumps` of small slices: last 3–5 turns (`last_turns`), a memory snapshot, emotion scores, or a memory summary. **The full conversation is never sent to the LLM.**
- **Memory update** happens before response generation (step 5 before step 9), so a turn can both write memory and read it.
- **Crisis handling bypasses everything**: risk short-circuit happens at step 2 — before memory writes, state transitions, routing, and response generation.
- **Two separate memory write paths** exist: LLM extraction (`llm.extract_memory`) and rule extraction (`extract_facts_from_message`), plus a third implicit path (`EmotionEngine._update_memory_from_emotion`) that writes emotion facts. These can duplicate/conflict (Section 15).
- **Latency**: worst case is **5+ sequential LLM calls** in one turn (emotion → memory → route → question → [insight/routine]) on a free-tier model, all inside a blocking `async def` endpoint.

---

## SECTION 3 — PROMPTS

All LLM prompts live in **`wellness_agent/llm_service.py`**. There is also a system-context string in `config.py`. Model used for every call: `llama-3.3-70b-versatile` (default parameter of `GroqLLM.__init__`; not configurable at runtime).

| # | Constant | Filename | Purpose | Variables injected | Model |
|---|---|---|---|---|---|
| 1 | `PRODUCT_CONTEXT` | `wellness_agent/config.py:7` | Global system context (business goal, boundaries, non-clinical guardrails) | `{APP_NAME}` | — |
| 2 | `ROUTER_SYSTEM` | `llm_service.py:76` | Decide which agents run this turn | `user_message`, `current_state`, `memory_snapshot`, `last_3_turns` | llama-3.3-70b-versatile |
| 3 | `TRANSITION_SYSTEM` | `llm_service.py:97` | Decide state exit/next-state | `current_state`, `exit_conditions`, `latest_exchange`, `memory_snapshot` | same |
| 4 | `MEMORY_SYSTEM` | `llm_service.py:113` | Extract durable facts → memory updates | `message`, `existing_memory_for_topic` | same (t=0.2) |
| 5 | `EMOTION_SYSTEM` | `llm_service.py:131` | Score 20 emotion dimensions | `message`, `recent_context` (last 5 turns) | same (t=0.1) |
| 6 | `QUESTION_SYSTEM` | `llm_service.py:149` | Write next question with type + options | `target_pillar`, `current_state`, `preferred_type_hint`, `memory_context` | same (t=0.7, max 256) |
| 7 | `RCA_SYSTEM` | `llm_service.py:177` | Causal chain → likely root cause | `pillar`, `memory_facts`, `emotion_history`, `habit_trends` | same (t=0.4, max 512) |
| 8 | `ROUTINE_SYSTEM` | `llm_service.py:196` | Generate 3–5 action routine plan | `root_cause_or_goal`, `memory_facts`, `past_adherence`, `constraints` | same (t=0.5, max 512) |
| 9 | `REPORT_SYSTEM` | `llm_service.py:214` | Generate report JSON from metrics | `period`, `metrics`, `prior_period_metrics`, `achievements` | same (t=0.3, max 512) |
| 10 | `CRISIS_SYSTEM` | `llm_service.py:232` | Warm crisis response with resources | `user_message`, `risk_indicator` | same (t=0.5, max 256) |
| 11 | `REFLECTION_SYSTEM` | `llm_service.py:246` | Closing message | `state_info`, `recent_exchange` (last 2) | same (t=0.6, max 200) |

### Prompt 1 — PRODUCT_CONTEXT (system context)

```python
PRODUCT_CONTEXT = """
You are one component of an AI wellness companion system called {APP_NAME}.

BUSINESS GOAL: Build daily engagement through genuine insight, not novelty — retention comes from users feeling understood, not from features.
USER GOAL: Understand themselves better, build sustainable habits, feel supported without judgment or lecturing.
AI GOAL: Narrow down the real root cause of what a user is experiencing through structured, adaptive conversation — never generic advice, never a survey.
WELLNESS GOAL: Strictly non-clinical and non-diagnostic. This is a wellness companion, not a therapist, doctor, or crisis service.
SUCCESS METRICS: session depth (turns to insight), 7/30-day return rate, per-topic resolution rate, user-reported clarity, D7/D30/D90 retention.

HARD BOUNDARIES:
1. Never diagnose a mental health condition (no "you have depression/anxiety/ADHD").
2. Never suggest starting, stopping, or changing medication.
3. Never provide medical, legal, or financial advice beyond wellness habit guidance.
4. If any signal of self-harm, suicidal ideation, or risk to others appears, immediately flag risk=true and hand off to the Risk Detection protocol.
5. Speak like a grounded, warm human coach — never clinical, never saccharine, never robotic.
6. Never invent user data. If a fact isn't in memory or the current message, don't assume it.
"""
```

**Note**: `PRODUCT_CONTEXT` is stored as `Orchestrator.context` (orchestrator.py:63) but **is never sent to the LLM in any call** — it is effectively dead configuration (verified: no other reference). The LLM operates only on the per-call `_SYSTEM` prompts above.

### Prompt 2 — ROUTER_SYSTEM

```python
ROUTER_SYSTEM = """You are the Conversation Orchestrator. You decide which internal agents should run for this turn.
Available agents: emotion_detection, memory_manager, root_cause_engine, recommendation_engine, question_planner, routine_generator, report_generator, reflection_agent.

Rules:
- Always include emotion_detection first.
- If risk signal detected, route ONLY to risk_protocol.
- Only call agents that are needed this turn.

Output JSON only:
{ "risk_detected": boolean, "route": ["agent_name", ...], "reason": "one sentence", "next_state_hint": "state or null" }"""
```

Injected: `json.dumps({"user_message", "current_state", "memory_snapshot", "last_3_turns"})`.
Note: the prompt advertises a `recommendation_engine` agent that does not exist anywhere in the codebase.

### Prompt 3 — TRANSITION_SYSTEM

```python
TRANSITION_SYSTEM = """You decide conversation state transitions. You are given the current state, its exit conditions, and the latest exchange. Determine if an exit condition is met, and if so, which state to move to.
Output JSON only:
{ "exit_met": boolean, "next_state": "...", "confidence": 0-100, "reason": "one sentence" }"""
```

Injected: `current_state`, `exit_conditions`, `latest_exchange`, `memory_snapshot`.
**Dead code** — `decide_transition()` is never called; transitions are fully deterministic (`state_machine.py`).

### Prompt 4 — MEMORY_SYSTEM

```python
MEMORY_SYSTEM = """You extract durable facts from a single conversation turn to update long-term memory.
For each fact found, output category (identity|goals|habits|emotional_history|personality), key, value, confidence (0-100), and source ("conversation").
Only extract what's actually stated or strongly implied — never invent. Omit anything under 40 confidence.
If a fact conflicts with existing memory, set action to "update".
Output JSON array only: [{"action":"add|update","category":"...","key":"...","value":"...","confidence":0-100,"source":"conversation"},...]"""
```

Injected: `{"message", "existing_memory_for_topic"}` where the latter is `memory.get_session_summary()` — **not** the full existing memory (the prompt says "existing_memory_for_topic" but the orchestrator passes a session summary with no topic detail). The `action` field is parsed but ignored (`add_fact` handles upsert by key itself).

### Prompt 5 — EMOTION_SYSTEM

```python
EMOTION_SYSTEM = """You analyze one user message and score it across the dimensions below. Scores are relative signals for tracking trends over time, NOT clinical measurements.
Score every dimension. Infer conservatively from tone, word choice, and context.

Dimensions: primary_emotion (string), secondary_emotion (string), emotional_intensity (0-100), confidence (0-100), avoidance (0-100), stress (0-100), motivation (0-100), hope (0-100), energy (0-100), engagement (0-100), trust (0-100), loneliness (0-100), frustration (0-100), burnout (0-100), anxiety (0-100), depression_risk (0-100), self_esteem (0-100), risk_flag (boolean), risk_reason (string or null).

Set risk_flag=true ONLY for explicit or strongly implied self-harm, suicidal ideation, or intent to harm others — not for general sadness. When in doubt on risk_flag, err toward true.

Output JSON only matching the full schema."""
```

Injected: `{"message", "recent_context": last 5 turns}`.

### Prompt 6 — QUESTION_SYSTEM

```python
QUESTION_SYSTEM = """You write the next question to ask the user, given a target topic and conversation state. Match tone to state — warmer in Rapport Building, more direct in Deep Investigation.

Question types and when to use them:
- Open: broad entry into a new topic
- Reflective: mirrors back what they said to deepen it
- Choice: 3-5 options when the user likely wants low-effort input
- Scaling: numeric/intensity check ("On a scale of 1-10...")
- Clarifying: resolves ambiguity in a prior answer
- Future: forward-looking
- Motivational: connects to stated goals
- Narrative: invites a short story
- Challenge: gently questions a pattern

Choose the type that fits, don't default to Open every time.

Output JSON only: {"question_type":"...","question_text":"...","response_options":["..."] or null}"""
```

Injected: `target_pillar`, `current_state`, `preferred_type_hint`, `memory_context` (`{trust_score, pillar, recent_topic}`).

### Prompt 7 — RCA_SYSTEM

```python
RCA_SYSTEM = """You build a causal reasoning chain from accumulated memory and emotion data for one wellness pillar. Find correlations and plausible explanations — NOT proof. Frame conclusions probabilistically.

Build the chain as linked observations, each with confidence, ending in a most-likely root cause with overall probability. Use only data actually present in the input.

Output JSON only:
{"chain":[{"observation":"...","confidence":0-100}],"likely_root_cause":"...","probability":0-100,"caveat":"Correlational, based on self-reported data — not a diagnosis."}"""
```

Injected: `pillar`, `memory_facts` (confidence ≥ 60 pre-filtered in `orchestrator._generate_insight`), `emotion_history` (confidence ≥ 60), `habit_trends`.

### Prompt 8 — ROUTINE_SYSTEM

```python
ROUTINE_SYSTEM = """You generate a routine plan based on a root cause or user-stated goal, plus known constraints.

Rules:
- Ground every recommendation in the user's actual data
- Keep to 3-5 concrete, small actions
- Never recommend anything requiring medical supervision without disclaimer
- Reference existing habit data so it feels like a next step

Output JSON only:
{"routine_type":"morning|work|stress|sleep|exercise|...","actions":[{"action":"...","why":"grounded in data","time_of_day":"...","difficulty":"easy|medium"}],"review_after_days":7}"""
```

Injected: `root_cause_or_goal`, `memory_facts` (all facts, unfiltered), `past_adherence` (always `{}`), `constraints` (always `{}`).

### Prompt 9 — REPORT_SYSTEM

```python
REPORT_SYSTEM = """You generate a wellness report strictly from the structured data provided. Never invent a number or observation not present in the input.

Include: trend summary, 2-3 observations connecting metrics (correlational framing only), and 1-2 suggested goals.

Output JSON only:
{"summary":"2-3 sentences","trends":[{"metric":"...","direction":"up|down|flat","value":"...","change":"..."}],"observations":["..."],"suggested_goals":["..."]}"""
```

Injected: `period`, `metrics`, `prior_period_metrics`, `achievements`.
**Dead code** — `GroqLLM.generate_report()` is never called; reports are generated deterministically by `wellness_agent/reports.py`.

### Prompt 10 — CRISIS_SYSTEM

```python
CRISIS_SYSTEM = """You are responding to a user who may be in crisis. Your response must:
1. Thank them for sharing
2. Provide crisis resource information (988 in US, or local equivalent)
3. Be warm, grounded, and non-clinical
4. Not try to diagnose or therapize

Output a short, warm paragraph."""
```

Injected: `{"user_message", "risk_indicator"}`.

### Prompt 11 — REFLECTION_SYSTEM

```python
REFLECTION_SYSTEM = """You are closing out a wellness conversation. Generate a warm, brief closing message that:
- Acknowledges what was discussed
- Leaves the door open for next time
- Is 1-3 sentences
"""
```

Injected: `state_info`, `recent_exchange` (last 2 turns).

### Response parsing

Every LLM call routes through `GroqLLM._call()` (max_tokens 200–1024, `temperature` 0.1–0.7, `timeout=15.0`, `max_retries=0`) and `_extract_json()` which strips ``` fences, falls back to first `{...}` regex match, and returns `{}` on failure. **Any malformed response silently degrades to the rule-based fallback.**

---

## SECTION 4 — MEMORY

### 4.1 Architecture summary

- **No database. No vector database. No embeddings. No semantic search. No ranking. No summarization. No deletion.**
- Memory = per-user JSON files. Two stores + one derived report store:

| Store | Path | Content |
|---|---|---|
| Long-term memory | `data/memory/{user_id}_memory.json` | facts[], trust_score, pillar_coverage, session_count, avoided/deprioritized pillars |
| Short-term (session) | `data/sessions/{user_id}_session.json` | full turn log (unbounded), reloaded last 10 turns into memory |
| Reports | `data/reports/{user_id}_{period}.json` | generated report snapshots |

### 4.2 Long-term memory schema (`MemorySystem`, `memory.py`)

```json
{
  "user_id": "default",
  "facts": [
    {
      "category": "emotional_history",   // identity|goals|habits|emotional_history|personality
      "key": "work_stress",
      "value": "high",
      "confidence": 80,                  // 0-100
      "source": "conversation",
      "last_updated": "2026-07-31T20:35:18.851419",
      "resolved": false                  // written but never read anywhere
    }
  ],
  "trust_score": 30,                     // 0-100, starts at 30
  "pillar_coverage": {
    "stress": { "confidence": 90, "last_updated": "...", "fact_count": 3 }
  },
  "last_updated": "...",
  "session_count": 6,
  "avoided_pillars": {},
  "deprioritized_pillars": []
}
```

### 4.3 Short-term memory

- **In-process**: `Orchestrator.last_turns` — list of the last ≤10 `{user, assistant, state, emotion}` turns (orchestrator.py:189–196). This is the only "conversation history" ever shown to the LLM (slices of 2–5 turns).
- **Persisted**: `data/sessions/...` — every turn appended in `_save_turn()`; on boot, `_load_session()` restores the last 10 turns.

### 4.4 Retrieval strategy

Pure in-memory scans of the facts list (`memory.py`):

- `get_fact(key)` — exact key equality.
- `get_facts_by_category(category)` — equality on category.
- `get_facts_by_pillar(pillar)` — **substring** `pillar in key` or `pillar in fact.get("tags", [])` (tags are never written — effectively substring-only).
- `get_emotional_history(limit=10)` — category filter + sort by `last_updated` desc.
- `get_habit_trends()` — category filter grouped by key stem (strips `_trend` suffix).
- `get_known_pillars()` / `get_unknown_pillars()` — derived from `pillar_coverage`.
- `get_session_summary()` — counts + known/unknown pillars, fed into the LLM memory-extraction prompt.

**Retrieval is O(n) linear scans; there is no ranking, scoring, or recency weighting** except the sort in `get_emotional_history`. `pillar_coverage` (the closest thing to an index) is maintained only when a fact's **key string contains the pillar name** (memory.py:82–92).

### 4.5 Writes / updates

- `add_fact()` — append; if `get_fact(key)` exists → routes to `update_fact()` (upsert-by-key semantics). **Conflicts are resolved by key overwrite: new value + (optionally) new confidence win. No versioning, no provenance beyond `source`.**
- `update_fact()` — overwrites `value`, `source`, `last_updated`; keeps old confidence if none passed.
- `EmotionEngine._update_memory_from_emotion()` — **side-effect writes**: every non-neutral primary emotion becomes a `emotion_<name>` fact, and `stress > 70` becomes a `stress_level` fact. This runs *inside* `EmotionEngine.analyze()` — the rule-based fallback — but the LLM emotion path does **not** write these facts (LLM path only persists what the memory LLM extracts). **Result: memory content differs depending on whether the LLM was up at emotion-detection time.**
- `adjust_trust_score(delta)` — clamped 0–100, persisted. Called in orchestrator with −3 (avoidance) / +2 (engagement) — the *only* trust driver.
- `mark_avoided_pillar()` / `increment_session()` — counters; `mark_avoided_pillar` is **never called** (dead).
- No summarization, no TTL, no deletion, no compaction. `resolved` is never set to `true`.

### 4.6 Rule-based extraction (`extract_facts_from_message`, memory.py:144)

Regex patterns with hardcoded confidences:

```python
sleep_patterns = [
    ("sleep_hours", r'(\d+(?:\.\d+)?)\s*(?:hours?|hrs?)\s*(?:of\s*)?sleep', 80),
    ("sleep_quality", r'sleep\s*(?:quality|was|is)\s*(bad|poor|terrible|okay|good|great|amazing)', 70),
    ("bedtime", r'(?:went to|hit the|to)\s*bed\s*(?:at\s*)?(\d+\s*(?::\d{2})\s*(?:am|pm)?)', 60),
]
```

plus mood regexes (`i'm feeling <sad|anxious|happy|lonely|tired>`), work-stress regexes, exercise frequency (`\d+ times/days`), nutrition mention, stress mention. LLM extraction runs first; regex path is the fallback (orchestrator.py:210–229).

### 4.7 What is "remembered" per turn (summary)

1. Emotion facts (rule path only) — every non-neutral primary emotion.
2. LLM-extracted facts (LLM path) — capped `confidence=min(95, ...)`.
3. Regex facts (fallback path).
4. State/pillar markers — `current_pillar` is **not** persisted to memory (only `pillar_coverage` if the fact key happens to contain a pillar name).

---

## SECTION 5 — DATABASE

**There is no database.** All persistence is flat JSON files (Section 4). Therefore:

- **Schema**: implicit, defined by dict shapes in `MemorySystem._load()` (memory.py:16–25), `_save_turn()` (orchestrator.py:612–623), and `ReportGenerator.generate()` (reports.py:24–31).
- **Tables**: none. Equivalent entities: `memory/<user>.json`, `sessions/<user>.json`, `reports/<user>_<period>.json`.
- **Relationships**: none — user_id is the only key, embedded in both filename and payload (`user_id` field).
- **Indexes**: none. `pillar_coverage` (memory.py:82) is a hand-maintained aggregate.
- **Migrations**: none. Schema drift would silently corrupt older files (e.g., older memories without `avoided_pillars` key are handled via `.get()` defaults, but new fields like `pillar_coverage` entries are never backfilled).
- **Concurrency**: no locking anywhere. Concurrent requests for the same `session_id` can interleave `load_json` → mutate → `save_json` and lose turns (Section 15).

There is no AI-specific database layer beyond this.

---

## SECTION 6 — TOOL CALLING

**The LLM has zero tool/function calling.** No OpenAI/Groq `tools=` parameter is used anywhere (`llm_service.py` only calls `client.chat.completions.create(model, messages, temperature, max_tokens)`). "Routing" is deterministic Python code, optionally *supplemented* by the LLM router prompt (which may add agent names to a list — but those names are only advisory; the response generator doesn't actually invoke agents by name).

The *internal* "tools" (deterministic functions the pipeline can invoke):

| Function | Input | Output | When used | Registered where |
|---|---|---|---|---|
| `EmotionEngine.analyze` | message, recent_context | 19-dimension emotion dict + risk flags | Every turn, as fallback to LLM emotion | `AgentRegistry` registry dict (agents.py:22) |
| `AgentRegistry.extract_and_store` | message, emotion_result | stored facts list | Every turn, as fallback to LLM memory extraction | registry (agents.py:23) |
| `MemorySystem.add_fact/update_fact` | category, key, value, confidence, source | fact dict / update result | All fact writes | direct calls |
| `QuestionPlanner.generate_question` | target_pillar, current_state, preferred_type_hint, memory_context | `{question_type, question_text, response_options}` | `question_planner` in route | registry (agents.py:25) + direct call (orchestrator.py:512) |
| `ConversationPlanner.select_target_pillar` | known/unknown pillars, state, emotion scores, message | `{target_pillar, reason, urgency}` | Pillar selection in `_generate_question` | registry (agents.py:28) + direct call (orchestrator.py:481) |
| `RootCauseAnalyzer.analyze` | pillar, memory_facts, emotion_history, habit_trends | `{chain, likely_root_cause, probability, caveat}` | `root_cause_engine` in route | registry (agents.py:24) + direct call (orchestrator.py:548) |
| `RoutineGenerator.generate` | root_cause_or_goal, memory_facts, ... | `{routine_type, actions, review_after_days}` | `routine_generator` in route | registry (agents.py:26) + direct call (orchestrator.py:584) |
| `ReportGenerator.generate` | period, metrics, ... | report dict | API `/report` only — never part of chat routing | registry (agents.py:27) |
| `reflection_response` | state_info | closing text | `state == "reflection"` fallback | registry (agents.py:29) + direct call (orchestrator.py:403) |
| `GroqLLM.route_turn` | message, state, memory snapshot, turns | route list (LLM advisory) | Every turn when LLM available | `_decide_route` (orchestrator.py:260) |

**Important**: `AgentRegistry.get_agent(name)` exists but is **never called** — the orchestrator bypasses the registry and calls agent methods directly. The registry dict is dead code, and the `route` list built by `_decide_route` does not drive agent invocation; `_generate_response` uses its own independent if/elif on state and route-membership.

---

## SECTION 7 — CONVERSATION STATE

There **is** an explicit state machine: `wellness_agent/state_machine.py` + `config.py` (`STATES`, `STATE_TRANSITIONS`).

### 7.1 States (config.py:31)

```python
STATES = [
    "greeting", "free_conversation", "rapport_building",
    "avoidance_detection", "soft_exploration", "guided_discovery",
    "pillar_selection", "deep_investigation", "insight_generation",
    "routine_planning", "reflection", "weekly_review", "follow_up"
]
```

`STATE_TRANSITIONS` in config.py declares next/fallback/max_turns per state, but **`state_machine.py` never reads `next`/`fallback`/`max_turns`** — it has its own hardcoded rule ladder in `_evaluate_transition()`. The config table is documentation-by-accident, not executable configuration (two sources of truth that already disagree).

### 7.2 Transition rules (deterministic, emotion-threshold driven)

- **greeting** → `free_conversation` (>2 words) or `guided_discovery` (>2 words + topic signal); stays in greeting forever on short replies (loops observed in real session data, `default_session.json`).
- **free_conversation** → `avoidance_detection` (avoidance > 50), `guided_discovery` (topic signal, intensity > 50, or 2 turns elapsed).
- **rapport_building** → `free_conversation` on trust ≥ 50, engagement > 65, or 4 turns.
- **avoidance_detection** → `soft_exploration` after 2 avoidance detections, else `free_conversation` after 3 turns.
- **soft_exploration** → `guided_discovery` (engagement > 50) or `free_conversation` (3 turns).
- **guided_discovery** → `pillar_selection` (pillar signal) or `deep_investigation` (selected_pillar set).
- **pillar_selection** → `deep_investigation` on selection; back to `guided_discovery` after 2 turns.
- **deep_investigation** → `insight_generation` after 5 questions or explicit pillar exit (`pillar_exit_explicitly` — setter `mark_pillar_exit()` is dead code).
- **insight_generation** → `routine_planning` (after insight delivered or 3 turns).
- **routine_planning** → `reflection` (routine created or 4 turns).
- **reflection** → `follow_up` after 2 turns.
- **weekly_review** → `free_conversation` (state itself is **unreachable** — nothing transitions into `weekly_review`).
- **follow_up** → `free_conversation` after 1 turn.

Two avoidance counters exist independently: `Orchestrator.avoidance_count` (orchestrator.py:69, drives exit offers) and `ConversationStateMachine.avoidance_count` (state_machine.py:12, drives soft_exploration). They are never synchronized.

### 7.3 What to ask next

Decided in `_generate_response` / `_generate_question`:
1. If `deep_investigation` + `current_pillar` → keep the pillar; else `ConversationPlanner.select_target_pillar` (priority: continuing pillar → context keyword regex match → emotion spike threshold → stale pillar >3 days → uncovered pillar → lowest-confidence known pillar → default "mood").
2. Question type from a **fixed cycle** for deep investigation: `["clarifying", "scaling", "clarifying", "reflective", "narrative"]` (question_planner.py:139) — the `free_slots`/open-slot rule in `STATE_OPTION_RULES` is declared but not enforced.
3. LLM question first, template bank fallback (`questions` dict, ~60 canned questions across 10 pillars and 8 types). Used questions tracked in `used_questions` set; on exhaustion the set clears.

### 7.4 What to remember

The LLM memory prompt decides; fallback regex decides; plus emotion side-effect writes (Section 4). **There is no explicit "ignore" policy** — anything the LLM or regex returns is stored. Low-confidence facts (even `confidence: 30–40`, as seen in `default_memory.json` emotion facts) are stored and can reach user-facing insight text (the pre-filter in `_generate_insight` is `>= 60`, but `get_facts_by_pillar` consumers elsewhere do not filter).

### 7.5 When to summarize

**Never.** There is no summarization anywhere in the codebase. "Summary" in `main.py /summary` and `app.py /summary/{id}` refers to `Orchestrator.get_summary()` — a **live state/trust/counts snapshot**, not a summary of prior conversations.

### 7.6 When to end the conversation

- Explicit exit path: after 3 avoidance detections the bot offers "check in tomorrow" (`_exit_offered`); user saying yes → hardcoded goodbye (orchestrator.py:151–155). **No follow-up is actually scheduled.**
- State machine termination: `reflection` → `follow_up` → `free_conversation` (infinite loop — conversations never "end" in the state machine; there is no terminal state).
- CLI: `/quit`.

---

## SECTION 8 — USER PROFILE

- **Storage**: per-user long-term memory file `data/memory/{user_id}_memory.json`. There is no dedicated profile entity (no name, age, timezone, contact, preferences). The `identity` category exists in `MEMORY_CATEGORIES` (config.py:68) and facts like `user_id`/`initiated_conversation` have been stored historically.
- **Identity resolution**: `user_id` arrives as the `session_id` form field / `?user=` query param / path segment, **completely unauthenticated** (Section 13). The name typed on the login page is never stored server-side.
- **Retrieval**: `MemorySystem(user_id)` loads the file at construction; every read is an in-memory list scan.
- **Update**: `add_fact` / `update_fact` — the only update trigger is a key collision (`get_fact(key)`), i.e., **last-write-wins on identical keys**. There is no conflict-resolution policy, no timestamp comparison, no confidence arbitration. The LLM prompt asks for `action: "update"` on conflict but the orchestrator ignores `action`.
- **Cross-session continuity**: relies entirely on the memory JSON; the greeting reflects `session_count` and first known pillar (orchestrator.py:274–287).

---

## SECTION 9 — ANALYSIS (mood, stress, habits, wellness, productivity, recommendations)

| Metric | Generator | Deterministic or LLM |
|---|---|---|
| Mood / primary emotion | `GroqLLM.extract_emotion` (EMOTION_SYSTEM) **or** `EmotionEngine.analyze` (keyword lexicons + sentiment + weighted heuristics, emotion_engine.py) | Hybrid: LLM primary, deterministic fallback |
| Stress / anxiety / loneliness / burnout / energy / hope / trust / engagement / frustration / self-esteem / depression-risk | Same two paths — 0–100 scores from keyword counts × weights (emotion_engine.py:24–36) or LLM | Hybrid |
| Risk flag | `RISK_PATTERNS` regex (nlp_utils.py:30) or LLM `risk_flag` | Hybrid |
| Habits (sleep hours, exercise frequency, nutrition) | `extract_facts_from_message` regexes (memory.py:144) | Deterministic |
| Pillar coverage / wellness dimensions | `pillar_coverage` aggregation by key-substring (memory.py:82) | Deterministic |
| Root cause / insight | `GroqLLM.analyze_root_cause` **or** `RootCauseAnalyzer` (per-pillar canned chains, root_cause.py) | Hybrid, LLM primary |
| Recommendations / routines | `GroqLLM.generate_routine` **or** `RoutineGenerator` (canned templates per topic, routine_generator.py) | Hybrid, LLM primary |
| Report trends/observations/goals | `ReportGenerator` (reports.py) — **fully deterministic**; `GroqLLM.generate_report` exists but is unused | Deterministic |

Honest note: the deterministic scores are keyword-count heuristics with arbitrary weights (e.g., `_score_dimension` = `min(100, int(count*25*weight + 10))`); the "metrics" reported to users (mood_avg etc.) come from `ReportGenerator._build_metrics_from_memory` which **hardcodes defaults** (`mood_avg: 65`, `stress_avg: 40`, ...) and only overrides `sleep_avg` — i.e., reports are largely fabricated numbers (Section 10).

---

## SECTION 10 — REPORTS

- **Code**: `wellness_agent/reports.py` (`ReportGenerator`); triggered only via `POST /report/{session_id}?period=daily|weekly` (app.py:102) or CLI `/report`.
- **Generation**: `generate(period)` → `_build_metrics_from_memory()` (defaults + optional sleep override) → `_compute_trends()` (diff vs `_build_prior_metrics()`, which are **hardcoded constants** `{mood_avg: 62, stress_avg: 45, ...}` — there is no real prior period data) → `_generate_observations()` (threshold-if statements) → `_generate_goals()` → `_generate_summary()` (counts up/down directions).
- **Output**: JSON written to `data/reports/{user_id}_{period}.json` (`get_report_path`, config.py:85). `data/reports/` did not exist at audit time — no report has ever been produced.
- **Charts**: none — no chart code, no charting library, no report UI in the frontend at all.
- **Insights**: generated in-chat via the root-cause engine (`_generate_insight`, orchestrator.py:536), presented as text with "not a diagnosis" caveat.
- **LLM path**: `GroqLLM.generate_report` (REPORT_SYSTEM) is dead code; `generate_weekly`/`generate_monthly` wrappers are also unused (only `daily`/`weekly` ever requested).

**Critical correctness issue**: report numbers (`mood_avg=65`, etc.) are hardcoded defaults, and trends are computed against hardcoded "prior" values — the report is not data-derived and will produce direction claims with zero supporting data.

---

## SECTION 11 — API ROUTES

All in `app.py`. Request/response bodies (JSON) below.

| Method | Path | Purpose | Request | Response |
|---|---|---|---|---|
| GET | `/` | Login page | — | `login.html` (HTML) |
| GET | `/chat?user=<name>` | Chat page | query `user` (default "default") | `chat.html` (HTML) |
| POST | `/chat` | **Process one message** | form: `message`, `session_id` (default "default") | `{response, options, state, emotion, risk, llm, pillar, crisis?}` |
| GET | `/summary/{session_id}` | Live state snapshot | path `session_id` | `{user, state, memory, current_pillar, trust_score, last_turns_count, llm_available}` |
| GET | `/memory/{session_id}` | All memory facts | path `session_id` | `{facts: [...]}` |
| GET | `/insight/{session_id}` | Last root-cause insight | path `session_id` | insight dict or `{error}` |
| GET | `/routine/{session_id}` | Last generated routine | path `session_id` | routine dict or `{error}` |
| POST | `/report/{session_id}` | Generate report | path `session_id`, query `period` (default daily) | report dict |
| POST | `/reset/{session_id}` | Reset state machine (memory preserved) | path `session_id` | `{status: "reset"}` |
| GET | `/health` | Health + LLM availability | — | `{status, llm_available}` |

Frontend consumes only `/chat` (initial greeting via empty `message`). Note the `route` field returned by `process_message` is dropped by the API layer.

---

## SECTION 12 — BACKGROUND JOBS

**None.** No schedulers, cron, queues, workers, async tasks, or Celery/APScheduler equivalents. Everything is request-synchronous.

Implications:
- "I'll check in tomorrow" (orchestrator.py:152) is a **lie** — nothing happens tomorrow. No proactive messaging exists despite `follow_up` state and `proactive_test_*` session files in `data/`.
- `weekly_review` state is unreachable because nothing triggers it.
- No retry/backoff for LLM calls (`max_retries=0`), no rate limiting, no caching.

---

## SECTION 13 — AUTHENTICATION

**None.**

- **Login**: `login.html` is a single text field → `GET /chat?user=<name>`. The "name" is never verified or persisted server-side.
- **Sessions**: `app.py` `_sessions: dict[str, Orchestrator]` — in-memory per-process map keyed by the arbitrary user string. **Anyone who knows/guesses a `session_id` can read that user's `/memory`, `/summary`, `/insight`, `/routine`, and `/report` endpoints, and impersonate them in `/chat`.** No cookies, tokens, or auth middleware.
- **User IDs**: free-form strings from query params, form fields, and URL path segments. Also used to build filesystem paths (`get_user_memory_path(user_id)` → `data/memory/{user_id}_memory.json`) — a `session_id` like `../../...` enables **path traversal** for read/write outside `data/`.
- **Permissions**: none — no roles, no scoping, no rate limits.
- The `_sessions` dict is also unbounded (memory leak vector).

---

## SECTION 14 — FILE MAP (30 most important files)

| # | File | Why it exists |
|---|---|---|
| 1 | `wellness_agent/orchestrator.py` | The entire conversation engine: turn pipeline, routing, response generation, repetition guard, persistence. The single most important file. |
| 2 | `wellness_agent/llm_service.py` | All LLM I/O, all 10 prompt templates, JSON parsing, availability flag. |
| 3 | `wellness_agent/memory.py` | Long-term fact store + regex fact extraction + trust/pillar bookkeeping. |
| 4 | `wellness_agent/state_machine.py` | Deterministic conversation flow control. |
| 5 | `wellness_agent/config.py` | Central constants: states, transitions, pillars, memory categories, `PRODUCT_CONTEXT`, data paths. |
| 6 | `wellness_agent/agents.py` | Composition root (`AgentRegistry`), rule-based memory extraction orchestration, reflection templates. |
| 7 | `wellness_agent/emotion_engine.py` | Rule-based emotion scoring fallback + emotion-driven memory writes. |
| 8 | `wellness_agent/nlp_utils.py` | Keyword lexicons, avoidance/risk regexes, sentiment, softmax (unused). |
| 9 | `wellness_agent/question_planner.py` | Template question bank + state option rules. |
| 10 | `wellness_agent/conversation_planner.py` | Pillar targeting heuristics (context, emotion spikes, staleness, coverage). |
| 11 | `wellness_agent/root_cause.py` | Rule-based causal chains + root-cause phrasing. |
| 12 | `wellness_agent/routine_generator.py` | Canned routine templates by topic. |
| 13 | `wellness_agent/reports.py` | Deterministic report generation (trends/observations/goals). |
| 14 | `wellness_agent/synthetic_data.py` | Scripted conversation generator for testing. |
| 15 | `wellness_agent/utils/storage.py` | JSON persistence helpers. |
| 16 | `app.py` | FastAPI app: all routes, session store, page serving. |
| 17 | `main.py` | CLI REPL entry point with debug slash commands. |
| 18 | `templates/chat.html` | The entire frontend (single file: CSS/JS/HTML, chat UI, options, crisis UI). |
| 19 | `templates/login.html` | Name-entry page (fake auth). |
| 20 | `requirements.txt` | Dependency manifest. |
| 21 | `Dockerfile` | Deploy image definition. |
| 22 | `render.yaml` | Render.com service config (free plan). |
| 23 | `.github/workflows/ci.yml` | CI import-smoke test + deploy trigger. |
| 24 | `.env.example` | Documented env vars (some dead). |
| 25 | `.env` | Real `GROQ_API_KEY` (gitignored, local). |
| 26 | `.gitignore` | Excludes data/memory, data/sessions, .env, caches. |
| 27 | `AUDIT_REPORT.md` | Prior audit notes (useful context; several issues already fixed in code). |
| 28 | `FIXES.md` | Stated fix plan from the prior audit (status unverifiable). |
| 29 | `data/memory/default_memory.json` | Real long-term memory sample (schema evidence; shows low-confidence facts persisted). |
| 30 | `data/sessions/default_session.json` | Real session log (evidence of greeting loops and repeated canned text). |

---

## SECTION 15 — ARCHITECTURAL WEAKNESSES (identified, not fixed)

### 15.1 Duplicated logic

1. **Topic keyword lists** duplicated at least 3×: orchestrator.py:115–118 and 139–141 (two near-identical lists), `state_machine._has_topic_signal` (state_machine.py:146–148), plus pillar regex maps in `conversation_planner.py:55–65` and `nlp_utils.py`. Drift risk is real (e.g., "sleep" appears twice in the first list; orchestrator's second list omits "routine").
2. **Option sets** duplicated between `orchestrator._MESSAGE_VARIANTS`/hardcoded arrays and `question_planner.STATE_OPTIONS` (e.g., avoidance options exist in both files with different wording).
3. **Avoidance counting** implemented twice — `Orchestrator.avoidance_count` and `StateMachine.avoidance_count` — never synchronized.
4. **Memory write paths** — LLM extraction, regex extraction, and emotion side-effect writes all funnel into the same fact store with different shapes; category/key conventions overlap (`mood_state` vs `emotion_<name>` vs `current_mood` observed in real data).

### 15.2 Dead code

- `AgentRegistry.get_agent()` (agents.py:20) — never called; orchestrator calls agents directly.
- `GroqLLM.decide_transition()` + `TRANSITION_SYSTEM` — unused.
- `GroqLLM.generate_report()` + `REPORT_SYSTEM` — unused.
- `ConversationStateMachine.mark_pillar_exit()` — unused.
- `MemorySystem.mark_avoided_pillar()` — unused.
- `ReportGenerator.generate_weekly()/generate_monthly()` — unused.
- `nlp_utils.softmax` (imported in emotion_engine, never invoked), `nlp_utils.extract_numeric_value`, `storage.merge_dicts` (imported in memory.py, never invoked).
- `QuestionPlanner._open_slots_used` and `STATE_OPTION_RULES[...]["free_slots"]` — declared, never enforced.
- `Orchestrator.context` (`PRODUCT_CONTEXT` formatted) — never sent anywhere.
- `GROQ_MODEL`, `APP_NAME`, `HOST` env vars — documented, never read.
- State `weekly_review` — unreachable.
- `resolved` field on facts — never written to `true`; `tags` field in `get_facts_by_pillar` — never populated.
- `recommendation_engine` advertised in ROUTER_SYSTEM prompt — doesn't exist.

### 15.3 Tight coupling

- `Orchestrator` is a god-class (661 lines): emotion analysis, routing, response generation, memory writes, persistence, crisis handling, repetition guards all inline.
- Response generation is one if/elif ladder whose branch order encodes product rules (avoidance → tree → question → insight → routine) that cannot be reconfigured.
- `AgentRegistry` is bypassed; the `route` list is computed but only loosely consulted.
- `EmotionEngine` writes to `MemorySystem` as a constructor side-effect dependency; `ReportGenerator` reaches into `memory` facts directly.
- State machine and orchestrator both mutate `avoidance`/exit flags across two objects.

### 15.4 Code smells

- **Magic numbers everywhere**: thresholds (60/65/70), weights (0.25/0.3/0.5/0.75), trust deltas (±2/±3), caps (min 95), turn caps (2/3/4/5) — no constants module.
- **Hardcoded fabricated data**: `reports.py` `_build_metrics_from_memory` returns `mood_avg: 65, stress_avg: 40` etc.; `_build_prior_metrics` returns hardcoded "prior" values; trends are then computed against them.
- **`async def` endpoints with blocking calls**: `app.py` handlers call the fully synchronous orchestrator/LLM inside the event loop (Free-tier render instance → one user blocks all).
- **Full-file JSON rewrite per turn** on both session and memory files; no locking (lost-update races), no atomic write (corruption on crash mid-write).
- **XSS**: `chat.html` renders `data.response` and option text via `div.innerHTML = text` (chat.html:240) — LLM/assistant output injected unsanitized; options are inserted via `textContent` (safe) but the message text is not.
- **Path traversal**: `user_id` flows into file paths (`config.get_user_memory_path`).
- **In-memory `_sessions` dict unbounded**; orchestrators never evicted.
- **Unbounded session JSON growth** (turns appended forever; only 10 are reloaded).
- **`logging` imported inside functions** (orchestrator.py:431, 443, 456) — style smell.
- **Prompt/state config drift**: `STATE_TRANSITIONS` next/fallback/max_turns unused by the state machine.
- Emoji in option strings mixed with text, no accessibility IDs.
- No tests directory, no pytest config; CI only does an import check.

### 15.5 Scalability issues

- Single-process, single-threaded event loop; blocking LLM calls (15s timeout) serialize all users.
- JSON-file storage doesn't scale past toy volume; every turn rewrites the whole file.
- No caching of LLM results; identical messages pay full cost each time.
- `last_turns` capped at 10 but LLM context never grows beyond slices — fine for now, but no path toward longer context.
- Free-tier assumptions baked into design (render.yaml `plan: free`, single service).

---

## SECTION 16 — CURRENT LIMITATIONS (brutally honest)

1. **No real conversational LLM memory.** The LLM sees only tiny JSON snapshots (last 2–5 turns, a counts-summary). It cannot reason over the full conversation or user history; `PRODUCT_CONTEXT` (the one real system prompt) is never sent. Long-term "intelligence" is regexes + hardcoded templates.
2. **No tool calling / function calling.** The LLM cannot invoke anything, fetch anything, or act; "agents" are decorative — the route list barely influences the response generator.
3. **Cannot schedule anything.** No follow-ups, no reminders, no cron — "check in tomorrow" is a hardcoded lie; `weekly_review` is unreachable.
4. **Cannot report truthfully.** Reports are built from hardcoded default metrics and hardcoded prior values; trends/goals are generated against fabricated data.
5. **Cannot handle conversation flow robustly.** The greeting state can loop indefinitely (proven in real session logs); exit-offer handler swallows valid user replies; canned-text repetition loops occur despite safeguards; two unsynchronized avoidance counters.
6. **No state persistence between process restarts** for active state machine/insight/routine (only memory + last 10 turns are reloaded; `current_pillar`, insight, routine, avoidance counters all reset on restart).
7. **No auth, no privacy boundary.** Any user can read/impersonate any session; user_id is a path traversal vector; health-data sensitivity with zero access control.
8. **No UI beyond chat.** No reports/charts in the frontend despite report/insight/routine endpoints. No streaming, no voice, no mobile.
9. **No observability.** No structured logging, no metrics, no tracing, no analytics; loop detection is stderr warnings only.
10. **LLM single point of failure with silent degradation.** If Groq is down (or `max_retries=0` + 15s timeout hit), the whole system silently switches to rule mode — behavior varies between "LLM mode" and "rules mode" even within a session (emotion facts differ between modes, Section 4.5).
11. **Cannot personalize beyond a fact list.** No identity, no preferences, no timezone, no goals store beyond free-text facts; trust score has almost no effect on behavior (only state_machine rapport exit checks it).
12. **No clinical safety validation.** Risk detection is regex/LLM-keyword based with no escalation, no follow-up protocol, no human-in-the-loop, no logging of crisis events.
13. **No testing.** Zero automated tests; the `data/sessions/*_test*.json` files show manual/synthetic testing only.
14. **Not deployable at scale as-is.** Blocking endpoints, JSON store, unbounded session dict, no DB, no auth — fine for a demo on a free Render instance, not beyond.

---

*Audit compiled from full source read of all 21 Python files, 2 templates, Dockerfile, render.yaml, CI workflow, config files, and sample `data/` payloads. All claims verified against code; dead-code claims verified via repository-wide grep.*
