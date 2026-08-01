# AGENTS.md

## Project
AI Agent Final — wellness companion coach (FastAPI, port 8000 local).
Repo: https://github.com/LUFICR/Ai-Agent-Final (branch `main`)
Live: https://ai-agent-final-reet.onrender.com (Render, auto-deploys from `main`)

## Critical convention: the "save" command
When the user types **save** (or "save progress"), you MUST:
1. `git add -A` + `git commit` (concise message matching repo style) + `git push origin main`
2. Pushing to `main` auto-deploys to Render (autoDeploy: yes). Verify nothing is broken before pushing.
3. Do NOT commit `.env` (gitignored), `data/` (gitignored), logs.

Every user change is expected to be pushed this way so the live app
stays in sync. If a push fails, fix and retry — the live site is the source of truth for the user.

## Local server
- Start: `python app.py` (or `C:\Python314\python.exe app.py`) from repo root.
- Health: `http://localhost:8000/health`
- Logs: `logs_app.txt` / `logs_app_err.txt` (gitignored).
- Debug tools: `replay_app.py` (8001), `metrics_app.py` (8002), `diff_app.py` (8003), `outcome_app.py` (8004).

## Key facts
- `/chat` endpoint uses Form fields (`application/x-www-form-urlencoded`), NOT JSON.
- Offline tests: pop `GROQ_API_KEY` from env; rule-based fallback keeps everything working.
- Eval index `data\evaluations\index.json` must stay at exactly 620 entries (cleanup after live runs).
- Safety/crisis detection is rule-based (`RISK_PATTERNS` in `wellness_agent\utils\nlp_utils.py`) — never rely on LLM for safety.
- LLM never decides objectives/interventions/hypotheses/behaviors (deterministic before prompting).
- Test suites: `memory_test.py`, `coaching_test.py`, `learning_test.py`, `phase6_stress100.py` in `C:\Users\Admin\AppData\Local\Temp\opencode\` (offline, no LLM).

## Verify before claiming success
- Run relevant test suite after code changes (all offline, fast).
- For live verification: POST form to `http://localhost:8000/chat` (or the Render URL) and check `risk`/`state`/response.
