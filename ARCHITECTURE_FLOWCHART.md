# AI Architecture Flowchart

```mermaid
flowchart TD
    U[("👤 User")]

    subgraph FE["FRONTEND (Vanilla JS, single-file HTML)"]
        L[login.html<br/>name field → GET /chat?user=<name>]
        C[chat.html<br/>fetch POST /chat<br/>FormData: message + session_id]
        R[Render: message bubble<br/>option buttons · status bar<br/>crisis banner]
    end

    subgraph AUTH["🔐 AUTHENTICATION — NOT IMPLEMENTED"]
        AUTH_N["No login verification<br/>No cookies / tokens / sessions<br/>Any session_id can impersonate a user<br/>session_id → filesystem path (traversal risk)"]
    end

    subgraph API["BACKEND — FastAPI (app.py)"]
        E1["GET / (login page)"]
        E2["GET /chat (chat page)"]
        E3["POST /chat — main turn endpoint<br/>(async def but runs blocking sync code)"]
        E4["GET /summary /memory /insight /routine"]
        E5["POST /report /reset"]
        E6["GET /health (LLM availability)"]
        SS["_sessions: dict[str, Orchestrator]<br/>in-memory, unbounded"]
    end

    subgraph ORCH["CONVERSATION MANAGER — Orchestrator.process_message()"]
        direction TB
        P1["1. _analyze_emotion()<br/>LLM EMOTION_SYSTEM → fallback EmotionEngine (rules)"]
        P2["2. Risk check<br/>risk_flag → CRISIS SHORT-CIRCUIT<br/>(no memory/state/routing) → LLM crisis text or 988 canned"]
        P3["3. Deterministic avoidance counter<br/>(short msg + no topic keyword)"]
        P4["4. Exit-offer handler (_exit_offered one-shot)"]
        P5["5. _extract_memory()<br/>LLM MEMORY_SYSTEM → fallback regex facts<br/>+ emotion side-effect writes"]
        P6["6. Trust score adjust (−3 avoidance / +2 engagement)"]
        P7["7. State machine transition()<br/>deterministic thresholds (NO LLM)"]
        P8["8. _decide_route()<br/>base + state rules + LLM ROUTER_SYSTEM supplement"]
        P9["9. _generate_response() — if/elif dispatch"]
        P10["10. _save_turn() → session JSON"]
        P1 --> P2 --> P3 --> P4 --> P5 --> P6 --> P7 --> P8 --> P9 --> P10
    end

    subgraph PB["🧩 PROMPT BUILDER (llm_service.py)"]
        PB1["Stateless json.dumps slices:<br/>last 2–5 turns · memory snapshot · emotion scores<br/>pillar · state · risk reason"]
        PB2["PRODUCT_CONTEXT system prompt<br/>⚠️ BUILT but NEVER sent to LLM"]
        PB3["Extract JSON: strip ``` fences → {…} regex → {} on failure<br/>malformed = silent rule-fallback"]
    end

    subgraph LLM["☁️ LLM — Groq API (llama-3.3-70b-versatile, hardcoded)"]
        LM1["EMOTION_SYSTEM"]
        LM2["MEMORY_SYSTEM"]
        LM3["ROUTER_SYSTEM"]
        LM4["QUESTION_SYSTEM"]
        LM5["RCA_SYSTEM"]
        LM6["ROUTINE_SYSTEM"]
        LM7["CRISIS_SYSTEM"]
        LM8["REFLECTION_SYSTEM"]
        LM9["TRANSITION_SYSTEM ⚠️ DEAD (never called)"]
        LM10["REPORT_SYSTEM ⚠️ DEAD (never called)"]
    end

    subgraph TOOLS["🔧 TOOL CALLING — NOT IMPLEMENTED"]
        TN["No tools= / function calling anywhere<br/>LLM cannot invoke anything —<br/>'route' list is advisory only<br/>AgentRegistry.get_agent() is dead code<br/>agents are called directly, not via registry"]
    end

    subgraph MEM["MEMORY (per-user JSON files)"]
        M1["data/memory/{user_id}_memory.json<br/>facts[] (category/key/value/confidence/source)<br/>trust_score · pillar_coverage · session_count"]
        M2["data/sessions/{user_id}_session.json<br/>full turn log (unbounded)<br/>last 10 reloaded at boot → short-term"]
        M3["No vector store · no embeddings<br/>no ranking · no summarization · no deletion<br/>last-write-wins on identical key"]
        M4["O(n) linear scans · pillar_coverage<br/>keyed by substring of pillar name"]
    end

    subgraph DB["🗄️ DATABASE — NONE"]
        DBN["No RDBMS / No tables / No indexes<br/>No migrations / No relationships<br/>Flat JSON is the only persistence"]
    end

    subgraph REP["📊 REPORTS"]
        REP1["ReportGenerator (deterministic only)<br/>LLM REPORT_SYSTEM unused"]
        REP2["Metrics HARDCODED: mood_avg=65, stress_avg=40<br/>'prior period' = hardcoded constants<br/>trends computed vs fabricated baseline"]
        REP3["data/reports/{user_id}_{period}.json"]
        REP4["No charts anywhere · no report UI"]
    end

    subgraph SCH["⏰ SCHEDULER — NONE"]
        SCHN["No cron / queues / workers / async jobs<br/>'I'll check in tomorrow' is never scheduled<br/>weekly_review state unreachable<br/>proactive messaging impossible"]
    end

    %% ====== MAIN FLOW ======
    U -->|types / taps option| L
    L -->|GET /chat?user=| C
    C -->|POST /chat| E3
    E3 -.-> AUTH_N
    AUTH_N -.->|no verification| E3
    E3 -->|get_orch(session_id)| SS
    SS -->|Orchestrator instance| P1

    P1 -->|LLM call| LM1
    P1 -.->|fallback| P1F["EmotionEngine.analyze (rules)<br/>nlp_utils lexicons + sentiment"]
    P2 -->|risk detected| P2F["_risk_response: LM7 or 988 canned text"]
    P2F --> P10
    P5 -->|LLM call| LM2
    P5 -.->|fallback| P5F["MemorySystem.extract_facts_from_message()<br/>regex patterns (sleep/mood/work/exercise)"]
    P5 -->|add_fact / update_fact| M1
    P8 -->|LLM call (supplement only)| LM3
    P9 -->|question_planner branch| P9Q["_generate_question<br/>LLM QUESTION_SYSTEM → QuestionPlanner bank<br/>(deep-investigation type cycle + ConversationPlanner pillar pick)"]
    P9 -->|root_cause_engine branch| P9R["_generate_insight<br/>LLM RCA_SYSTEM → RootCauseAnalyzer chains"]
    P9 -->|routine_generator branch| P9U["_generate_routine_suggestion<br/>LLM ROUTINE_SYSTEM → RoutineGenerator templates"]
    P9 -->|reflection state| P9L["LLM REFLECTION_SYSTEM → reflection_response()"]
    P9Q -->|LLM call| LM4
    P9R -->|LLM call| LM5
    P9U -->|LLM call| LM6
    P9L -->|LLM call| LM8
    P9Q -->|reads| M1
    P9R -->|reads facts ≥60 conf| M1
    P9U -->|reads facts| M1
    P10 -->|append + rewrite whole file| M2

    %% API side-routes
    E4 -->|reads| M1
    E5 -->|writes| REP3
    REP1 --> REP3
    E5 -->|reset only state machine,<br/>memory preserved| ORCH

    %% Dead / absent markers
    PB2 -.->|never injected| LLM
    LM9 -.->|unused| PB1
    LM10 -.->|unused| REP1
    TOOLS -.->|not invoked| P9
    DB -.->|replaces nothing| M1
    SCH -.->|absent| P4
    AUTH_N -.->|absent| E3

    R -->|render response/options| U
    E3 -->|JSON {response, options, state, emotion, risk, llm, pillar, crisis}| R
    R -.->|innerHTML injection (XSS risk)| C

    style AUTH fill:#fde8e8,stroke:#dc2626,stroke-dasharray: 5 5
    style DB fill:#fde8e8,stroke:#dc2626,stroke-dasharray: 5 5
    style SCH fill:#fde8e8,stroke:#dc2626,stroke-dasharray: 5 5
    style TOOLS fill:#fde8e8,stroke:#dc2626,stroke-dasharray: 5 5
    style PB2 fill:#fef9c3,stroke:#ca8a04
    style LM9 fill:#fef9c3,stroke:#ca8a04
    style LM10 fill:#fef9c3,stroke:#ca8a04
    style REP2 fill:#fef9c3,stroke:#ca8a04
```
