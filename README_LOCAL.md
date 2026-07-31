# Wellness Companion — Local Setup

Run the full AI coach stack on your own machine (localhost). Everything is
self-contained in this folder — no external database required.

## 1. Requirements

- Python 3.10+ (developed on 3.14 / Windows)
- Internet access **only if you want LLM-powered responses**
  (see "Working without an API key" below)

## 2. Install

```powershell
cd C:\test
python -m pip install -r requirements.txt
```

Dependencies: `groq`, `fastapi`, `uvicorn`, `jinja2`, `python-multipart`, `python-dotenv`.

## 3. Configure (optional)

Copy `.env.example` to `.env` and add a Groq API key (free tier:
https://console.groq.com/keys — ~100k tokens/day):

```powershell
Copy-Item .env.example .env
notepad .env
```

```env
GROQ_API_KEY=gsk_your_api_key_here
```

Without a key the app still works: every LLM call falls back to deterministic
rule-based responses (quality is lower; no crash, no hang).

## 4. Run

```powershell
python app.py
```

Open http://localhost:8000 in your browser.

| URL | What it is |
|-----|-----------|
| http://localhost:8000 | Login / user picker (any name works) |
| http://localhost:8000/chat | Chat interface |
| http://localhost:8001 | Conversation replay & debugging tool |
| http://localhost:8002 | Live metrics dashboard |
| http://localhost:8003 | Commit-vs-commit comparison |
| http://localhost:8004 | User outcome tracking |
| http://localhost:8000/health | Health check (status + LLM availability) |

The four debug tools (8001–8004) are standalone, read-only servers. Start
them only if you need them:

```powershell
python replay_app.py     # 8001
python metrics_app.py    # 8002
python diff_app.py       # 8003
python outcome_app.py    # 8004
```

Alternatively use the CLI for quick sanity checks:

```powershell
python main.py
```

## 5. Data layout

Everything lives under `C:\test\data\` (created on first run):

| Path | Contents |
|------|----------|
| `data\memory\<user>_memory.json` | Per-user long-term memory facts |
| `data\sessions\<user>_session.json` | Conversation turns |
| `data\behaviors\`, `data\beliefs\`, `data\hypotheses\`, `data\whys\` | Per-user reasoning models |
| `data\evaluations\index.json` | Conversation judge evaluations (620 sim entries) |
| `data\learning\<user>_learning.json` | Per-user learning model (confidence, hypotheses, interventions) |
| `data\reports\` | Generated daily/weekly reports |
| `data\outcomes\` | User outcome tracking |
| `data\stress_reports\` | Stress-test results (if you run them) |

There is no admin user list or password — the login page accepts any user
name and each name gets an isolated memory profile.

## 6. Configuration knobs

| Env var | Default | Meaning |
|---------|---------|---------|
| `GROQ_API_KEY` | (none) | Groq key; absent = rule-based fallback |
| `GROQ_MODEL` | `llama-3.3-70b-versatile` | LLM model name |
| `HOST` | `127.0.0.1` | Bind address |
| `PORT` | `8000` | Web port |
| `DEBUG` | `true` | Print per-turn internal reasoning to the terminal |

## 7. Working without an API key

- All deterministic subsystems are fully functional: emotion analysis, risk
  detection, memory, state machine, objectives, hypotheses, insights,
  interventions, routines, reports.
- `[LLM] Groq not configured — using rule-based fallback` is printed in the
  server terminal; this is expected and harmless.
- The health check reports `llm_available: false`.

## 8. Tests

```powershell
python C:\Users\Admin\AppData\Local\Temp\opencode\memory_test.py
python C:\Users\Admin\AppData\Local\Temp\opencode\coaching_test.py
python C:\Users\Admin\AppData\Local\Temp\opencode\learning_test.py
```

Stress harness (100 adversarial conversations, no LLM needed):

```powershell
python C:\Users\Admin\AppData\Local\Temp\opencode\phase6_stress100.py
```

## 9. Troubleshooting

- **Port in use**: change `PORT` in `.env` and restart.
- **Blank responses / no LLM**: check `.env` exists and key is valid; check
  the server terminal for `[LLM]` messages.
- **Rate limit (HTTP 429)**: Groq free tier is ~100k tokens/day. The app
  degrades gracefully to rule-based responses until the limit resets.
- **Data reset**: delete `C:\test\data\` to start completely fresh.
