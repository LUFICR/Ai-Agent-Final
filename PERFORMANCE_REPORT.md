# Performance Report — Wellness Companion

**Date:** 2026-08-01
**Method:** deterministic offline runs (GROQ_API_KEY removed in-process) plus
live-server measurements on the restarted stack.

---

## 1. Turn Latency (offline, rule-based fallback)

Measured across 8 scenario categories × 1 run each through the REAL
orchestrator pipeline (emotion → risk → memory → state → route → reasoning →
response → save):

| Metric | Value |
|--------|-------|
| Mean per-turn latency | **5.6 ms** |
| Median per-turn latency | **5.8 ms** |
| Max per-turn latency | **6.9 ms** |

No LLM calls are made in this mode — this is the floor. The entire stack is
fully functional without an API key.

## 2. LLM Call Profile (live path)

Instrumented the real `GroqLLM` call sites during a 6-turn conversation:

| Turn | LLM calls | Approx. prompt chars |
|------|-----------|----------------------|
| 1 (greeting/exploration) | 2 | ~444 |
| 2 (deep investigation) | 3 | ~707 |
| 3 | 3 | ~928 |
| 4 | 3 | ~1,153 |
| 5 | 3 | ~1,427 |
| 6 (insight) | 2 | ~1,648 |

- Calls: `extract_emotion`, `extract_memory`, `generate_question` (during
  questioning states). `route_turn` only when state-based routing is
  supplemented.
- **2–3 LLM calls per turn**, prompt sizes grow as memory context accumulates.

## 3. Token Budget (the binding constraint)

Observed live on 2026-08-01: Groq free tier `llama-3.3-70b-versatile` hit the
**100,000 tokens/day limit** (99.2k used). Each request is ~1.3–1.9k tokens.

| Budget | Estimate |
|--------|----------|
| Tokens per LLM-enabled turn | ~1,500 (3 calls × ~500) |
| Turns per day on free tier | **~60** |
| Graceful degradation | verified: HTTP 429 → rule-based fallback, no error surfaced to user |

**Recommendation:** for real deployment, upgrade to a paid Groq tier or add a
secondary model provider. The fallback is safe, but coaching quality drops
without the LLM.

## 4. Memory & Scale

- Memory facts per conversation run: max 5 facts stored in stress runs;
  per-user store bounded (evidence history capped at 8, confidence capped 95).
- Session store in `app.py` is bounded at **MAX_SESSIONS = 50** (oldest
  evicted) — a duplicate `get_orch` that shadowed this bound was removed
  during the review.
- Commit-id detection is cached per process (one `git` subprocess, not one
  per session).

## 5. Process Memory

Measured via Windows working-set sampling during 8 full scenario runs:
no material growth detected (delta below measurement resolution). Data
persists to JSON files under `data/`, not in RAM.

## 6. Optimization Notes

| Area | Finding |
|------|---------|
| Offline latency | Excellent (5.6ms); no work needed |
| LLM prompt size | Grows with context; consider trimming `last_turns` window (currently 10) if budget matters |
| Token consumption | 2–3 calls/turn is reasonable; `route_turn` and `decide_transition` LLM supplements are optional by design |
| Cold start | `Orchestrator()` loads all per-user JSON stores; negligible for 50-session bound |
| File I/O | Per-turn session write is synchronous; acceptable at 5.6ms floor |
