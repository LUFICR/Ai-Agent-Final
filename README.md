# AI Agent Final — Wellness Companion

An empathetic AI coaching companion with memory, learning, and safety-first
crisis detection. Fully local-first: no database needed, runs on your machine
or anywhere with Docker/Python.

## Live demo

- Deployed on Render: *(add your Render URL once deployed — e.g. https://ai-agent-final.onrender.com)*
- Local: see [README_LOCAL.md](README_LOCAL.md)

## What it is

A conversational wellness coach with a full reasoning pipeline:

- **Emotion & risk analysis** — deterministic, rule-based safety layer with
  988 crisis protocol (panic phrasing, suicide ideation, plan/means detection)
- **Memory** — per-user long-term facts with confidence, contradiction
  detection, decay, and confirmation prompts
- **Coaching state machine** — investigation before insight (no premature
  conclusions), intervention/routine generation grounded in explored patterns
- **Learning** — per-user behavioral model that adapts objectives, question
  style, and retrieval weighting across sessions
- **Reports** — daily and weekly summaries

The LLM (Groq, free tier) only converts deterministic reasoning into language.
It never decides objectives, interventions, hypotheses, or behavior traits.
All safety detection is rule-based and never depends on the LLM.

## Quick start

```powershell
pip install -r requirements.txt
Copy-Item .env.example .env   # optional: add GROQ_API_KEY
python app.py                 # → http://localhost:8000
```

Works fully without an API key (rule-based fallback). Four read-only debug
servers on ports 8001–8004 (`replay_app.py`, `metrics_app.py`, `diff_app.py`,
`outcome_app.py`).

## Verification

- [PRODUCTION_READINESS_REPORT.md](PRODUCTION_READINESS_REPORT.md) — scores, verdict, go-live checklist
- [TEST_RESULTS.md](TEST_RESULTS.md) — memory/coaching/learning suites, 100-conversation stress test, live safety verification
- [PERFORMANCE_REPORT.md](PERFORMANCE_REPORT.md) — 5.6 ms/turn offline, ~60 LLM turns/day on Groq free tier
- [ARCHITECTURE_AUDIT.md](ARCHITECTURE_AUDIT.md) / [AUDIT_REPORT.md](AUDIT_REPORT.md)

## Deployment

`Dockerfile` (Python 3.12, uvicorn on `0.0.0.0:8000`) — deployable on
HuggingFace Spaces, Render, Railway, or any container host. Data lives in
local JSON files under `data/`; a `data/` folder is created automatically on
first run.

## Stack

FastAPI · uvicorn · Jinja2 · Groq LLM (optional) · pure Python logic core
