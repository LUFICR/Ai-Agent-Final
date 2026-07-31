# LOCAL_SETUP.md

The complete local setup guide lives in **[README_LOCAL.md](README_LOCAL.md)**.

Quick start:

```powershell
cd C:\test
python -m pip install -r requirements.txt
Copy-Item .env.example .env   # optional: add GROQ_API_KEY
python app.py                 # → http://localhost:8000
```

Debug tools (standalone, read-only): `python replay_app.py` (8001),
`python metrics_app.py` (8002), `python diff_app.py` (8003),
`python outcome_app.py` (8004).

Data lives under `C:\test\data\` (per-user JSON stores — no database).
Works fully without an API key (rule-based fallback, `llm_available: false`).
See README_LOCAL.md for configuration knobs, data layout, and troubleshooting.
