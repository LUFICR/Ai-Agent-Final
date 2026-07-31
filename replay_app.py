"""Conversation Replay — DEBUG-ONLY viewer. Run: python replay_app.py  (port 8001)

Replays conversations turn by turn with full internal context:
Turn, User message, Reasoning Context, Behavior traits, Hypotheses, Objective,
Why Engine, Intervention, Prompt, Response, Evaluation, Memory updates.

Sources:
  - sim records   data/simulations/*/  (full per-turn fidelity)
  - live sessions data/sessions/*_session.json
                  (slim store: missing internals are reconstructed from the
                   per-user memory/behaviors/whys/hypotheses stores, best-effort)

No production code is touched. app.py and the wellness_agent package are
never modified or imported for serving; this file only reads data files.
"""

import json
import os
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

DATA = Path(__file__).resolve().parent / "data"
SIM_BATCHES = DATA / "simulations"
SESSIONS = DATA / "sessions"
MEMORY_DIR = DATA / "memory"
BEHAVIORS_DIR = DATA / "behaviors"
WHYS_DIR = DATA / "whys"
HYPOTHESES_DIR = DATA / "hypotheses"

app = FastAPI(title="Conversation Replay (debug)", version="0.1.0")


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _iso(t):
    try:
        return datetime.fromisoformat(str(t))
    except (ValueError, TypeError):
        return None


def _fmt_ts(t):
    d = _iso(t)
    return d.strftime("%Y-%m-%d %H:%M:%S") if d else str(t or "")


# ─── Discovery ────────────────────────────────────────────────────────────

def list_sim_records():
    out = []
    if not SIM_BATCHES.is_dir():
        return out
    for batch_dir in sorted(SIM_BATCHES.iterdir()):
        if not batch_dir.is_dir():
            continue
        for f in sorted(batch_dir.glob("*.json")):
            if f.name == "manifest.json":
                continue
            rec = _read(f)
            if not rec or not rec.get("turns"):
                continue
            out.append({
                "id": f"sim:{batch_dir.name}:{f.name}",
                "source": "sim",
                "batch": batch_dir.name,
                "sim_id": rec.get("sim_id") or f.stem,
                "persona": rec.get("persona_label") or rec.get("persona_id") or "",
                "seed": rec.get("seed"),
                "turns": len(rec["turns"]),
                "ended": rec.get("ended"),
            })
    return out


def list_live_sessions():
    out = []
    if not SESSIONS.is_dir():
        return out
    for f in sorted(SESSIONS.glob("*_session.json")):
        rec = _read(f)
        if not rec or not rec.get("turns"):
            continue
        uid = rec.get("user_id") or f.name.replace("_session.json", "")
        out.append({
            "id": f"live:{uid}",
            "source": "live",
            "user_id": uid,
            "turns": len(rec["turns"]),
            "created": _fmt_ts(rec.get("created")),
        })
    return out


def list_conversations():
    return list_sim_records() + list_live_sessions()


# ─── Sim record replay ────────────────────────────────────────────────────

def _section(name, value, note=None):
    return {"name": name, "value": value, "note": note}


def replay_sim(batch, filename):
    rec = _read(SIM_BATCHES / batch / filename)
    if not rec:
        return None
    turns = []
    for i, t in enumerate(rec.get("turns", [])):
        eo = t.get("engine_outputs") or {}
        rc = t.get("reasoning_context") or {}
        turns.append({
            "n": i + 1,
            "timestamp": _fmt_ts(t.get("timestamp")),
            "sections": [
                _section("Turn", {
                    "turn": i + 1,
                    "state": t.get("state"),
                    "route": t.get("route") or [],
                    "emotion": t.get("emotion"),
                    "day_offset": t.get("day_offset"),
                    "llm_used": t.get("llm_used"),
                    "tags": t.get("tags") or [],
                }),
                _section("User message", t.get("user_message")),
                _section("Reasoning Context", rc,
                         "What the pipeline used to build this response (persisted per turn in sim records)."),
                _section("Behavior traits", eo.get("behaviors")),
                _section("Hypotheses", eo.get("hypotheses")),
                _section("Objective", t.get("objective"),
                         "Objective chosen for this turn."),
                _section("Why Engine", eo.get("whys"),
                         "Why patterns/insights active this turn."),
                _section("Intervention", eo.get("interventions") or rc.get("intervention"),
                         "Ranked interventions offered this turn."),
                _section("Prompt", rc,
                         "Raw LLM request is not persisted; the reasoning context is the deterministic prompt fragment the response was built from."),
                _section("Response", t.get("assistant_response")),
                _section("Evaluation", t.get("evaluation"),
                         "Self-evaluation of the PREVIOUS response (evaluated on this turn)."),
                _section("Memory updates", t.get("memory_changes")),
            ],
        })
    return {
        "id": f"sim:{batch}:{filename}",
        "source": "sim",
        "label": f"{rec.get('persona_label') or rec.get('persona_id')} ({rec.get('sim_id')})",
        "meta": {
            "batch": batch,
            "sim_id": rec.get("sim_id"),
            "persona": rec.get("persona_label") or rec.get("persona_id"),
            "seed": rec.get("seed"),
            "turns": len(turns),
            "actual_turns": rec.get("actual_turns"),
            "ended": rec.get("ended"),
            "tags": rec.get("tags") or [],
            "duration_s": rec.get("duration_s"),
            "memory_final": rec.get("memory_final"),
        },
        "turns": turns,
    }


# ─── Live session replay (best effort reconstruction) ─────────────────────

def _live_snapshot(uid):
    snap = {
        "memory_facts": _read(MEMORY_DIR / f"{uid}_memory.json"),
        "behaviors": _read(BEHAVIORS_DIR / f"{uid}_behaviors.json"),
        "whys": _read(WHYS_DIR / f"{uid}_whys.json"),
        "hypotheses": _read(HYPOTHESES_DIR / f"{uid}_hypotheses.json"),
    }
    return snap


def _memory_updates_live(snapshot, t0, t1):
    """Best-effort per-turn memory updates: facts touched between turn timestamps."""
    mem = snapshot.get("memory_facts") or {}
    facts = mem.get("facts") or []
    if t0 is None and t1 is None:
        return {"note": "no timestamps in session store", "facts": []}
    updated = []
    for f in facts:
        ts = _iso(f.get("last_updated"))
        if ts is None:
            continue
        if t0 is not None and ts < t0:
            continue
        if t1 is not None and ts > t1:
            continue
        updated.append({k: f.get(k) for k in ("category", "key", "value", "confidence", "last_updated")})
    return {
        "note": "reconstructed from memory store by last_updated (best effort)",
        "facts": updated,
        "facts_total": len(facts),
        "trust_score": mem.get("trust_score"),
    }


def replay_live(uid):
    rec = _read(SESSIONS / f"{uid}_session.json")
    if not rec:
        return None
    snapshot = _live_snapshot(uid)
    raw_turns = rec.get("turns", [])
    times = [_iso(t.get("timestamp")) for t in raw_turns]
    turns = []
    for i, t in enumerate(raw_turns):
        t0 = times[i - 1] if i > 0 else None
        t1 = times[i]
        es = t.get("emotion_summary") or {}
        turns.append({
            "n": i + 1,
            "timestamp": _fmt_ts(t.get("timestamp")),
            "sections": [
                _section("Turn", {
                    "turn": i + 1,
                    "state": t.get("state"),
                    "emotion": es.get("primary"),
                    "risk": es.get("risk"),
                }),
                _section("User message", t.get("user_message")),
                _section("Reasoning Context", None,
                         "Not captured in the live session store (sim records capture it; live sessions persist only a slim turn)."),
                _section("Behavior traits", snapshot.get("behaviors"),
                         "End-of-conversation snapshot from behaviors store (per-turn traits not persisted for live sessions)."),
                _section("Hypotheses", snapshot.get("hypotheses"),
                         "End-of-conversation snapshot from hypotheses store."),
                _section("Objective", t.get("objective"),
                         "Objective chosen for this turn."),
                _section("Why Engine", snapshot.get("whys"),
                         "End-of-conversation snapshot from whys store."),
                _section("Intervention", None,
                         "Not captured in the live session store."),
                _section("Prompt", None,
                         "Not captured for live sessions."),
                _section("Response", t.get("response")),
                _section("Evaluation", None,
                         "Not captured in the live session store."),
                _section("Memory updates", _memory_updates_live(snapshot, t0, t1)),
            ],
        })
    return {
        "id": f"live:{uid}",
        "source": "live",
        "label": f"live session — {uid}",
        "meta": {
            "user_id": uid,
            "turns": len(turns),
            "created": _fmt_ts(rec.get("created")),
            "last_updated": _fmt_ts(rec.get("last_updated")),
        },
        "turns": turns,
    }


def load_conversation(cid):
    parts = unquote(cid).split(":", 1)
    if len(parts) != 2:
        return None
    kind, rest = parts
    if kind == "sim":
        bf = rest.split(":", 1)
        if len(bf) != 2:
            return None
        return replay_sim(bf[0], bf[1])
    if kind == "live":
        return replay_live(rest)
    return None


# ─── API ──────────────────────────────────────────────────────────────────

@app.get("/api/conversations")
def conversations():
    return {"conversations": list_conversations()}


@app.get("/api/conversation/{cid:path}")
def conversation(cid: str):
    data = load_conversation(cid)
    if data is None:
        return JSONResponse({"error": "conversation not found"}, status_code=404)
    return data


@app.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse(INDEX_HTML)


INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Conversation Replay — debug</title>
<style>
  :root { --bg:#0f1420; --panel:#171e2e; --line:#2a3450; --fg:#d7dce8; --dim:#8b93a7;
          --acc:#5aa2ff; --chip:#22304f; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--fg); font:14px/1.5 "Segoe UI",system-ui,sans-serif; }
  #layout { display:flex; height:100vh; }
  #side { width:300px; min-width:300px; border-right:1px solid var(--line); overflow:auto; padding:10px; }
  #main { flex:1; overflow:auto; padding:18px 24px; }
  h1 { font-size:16px; margin:6px 8px 12px; color:var(--acc); }
  .grp { color:var(--dim); font-size:11px; text-transform:uppercase; letter-spacing:.08em; margin:14px 8px 6px; }
  .conv { display:block; width:100%; text-align:left; background:var(--panel); border:1px solid var(--line);
          color:var(--fg); border-radius:6px; padding:8px 10px; margin:4px 0; cursor:pointer; font-size:12.5px; }
  .conv:hover { border-color:var(--acc); }
  .conv.active { border-color:var(--acc); background:#1c2a44; }
  .conv small { display:block; color:var(--dim); }
  #header { display:flex; align-items:center; gap:12px; border-bottom:1px solid var(--line); padding-bottom:10px; flex-wrap:wrap; }
  #label { font-size:17px; font-weight:600; }
  #meta { color:var(--dim); font-size:12px; }
  #controls { display:flex; align-items:center; gap:6px; margin:12px 0; }
  button { background:var(--panel); border:1px solid var(--line); color:var(--fg); border-radius:6px;
           padding:6px 12px; cursor:pointer; font-size:13px; }
  button:hover:not(:disabled) { border-color:var(--acc); }
  button:disabled { opacity:.35; cursor:default; }
  #pos { font-variant-numeric:tabular-nums; }
  #turnhead { display:flex; gap:8px; align-items:center; flex-wrap:wrap; margin:14px 0 10px; }
  .chip { background:var(--chip); border-radius:10px; padding:2px 9px; font-size:12px; }
  .sec { background:var(--panel); border:1px solid var(--line); border-radius:8px; margin:10px 0; overflow:hidden; }
  .sec h3 { margin:0; padding:8px 14px; font-size:13px; color:var(--acc); background:#1a2236; cursor:pointer;
            display:flex; justify-content:space-between; }
  .sec .body { padding:10px 14px; }
  .sec .note { color:var(--dim); font-size:12px; font-style:italic; margin-bottom:6px; }
  pre { margin:0; white-space:pre-wrap; word-break:break-word; font:12.5px/1.5 Consolas,monospace; }
  .empty { color:var(--dim); font-style:italic; }
  .user { color:#ffd479; font-weight:600; }
  .resp { color:#a8e6a1; }
  .kv { font:12.5px/1.5 Consolas,monospace; }
</style>
</head>
<body>
<div id="layout">
  <div id="side"><h1>Conversation Replay</h1><div id="list"><div class="empty">loading…</div></div></div>
  <div id="main">
    <div id="header">
      <div id="label">select a conversation</div>
      <div id="meta"></div>
    </div>
    <div id="controls">
      <button id="first" title="first turn">|<</button>
      <button id="prev" title="previous turn (←)"><</button>
      <span id="pos">– / –</span>
      <button id="next" title="next turn (→)">></button>
      <button id="last" title="last turn">>|</button>
      <input id="jump" type="number" min="1" style="width:64px;background:var(--panel);border:1px solid var(--line);color:var(--fg);border-radius:6px;padding:5px 8px" title="jump to turn">
    </div>
    <div id="turnhead"></div>
    <div id="sections"></div>
  </div>
</div>
<script>
let LIST = [], CUR = null, IDX = 0;

async function api(p){ const r = await fetch(p); if(!r.ok) throw new Error(p + " " + r.status); return r.json(); }

function el(tag, cls, text){ const e = document.createElement(tag); if(cls) e.className = cls; if(text !== undefined) e.textContent = text; return e; }

function renderList(){
  const box = document.getElementById("list"); box.innerHTML = "";
  const grps = {"sim": "Simulation records", "live": "Live sessions"};
  for (const src of ["sim", "live"]) {
    const items = LIST.filter(c => c.source === src);
    if (!items.length) continue;
    box.appendChild(el("div", "grp", grps[src]));
    for (const c of items) {
      const b = el("button", "conv");
      const label = c.source === "sim" ? (c.persona || c.sim_id) : c.user_id;
      b.appendChild(el("span", null, label + " · " + c.turns + " turns"));
      b.appendChild(el("small", null, c.source === "sim" ? (c.batch + " · seed " + (c.seed ?? "?")) : ("created " + c.created)));
      b.onclick = () => openConv(c.id);
      if (CUR && c.id === CUR.id) b.classList.add("active");
      box.appendChild(b);
    }
  }
}

async function openConv(id){
  CUR = await api("/api/conversation/" + encodeURIComponent(id));
  IDX = 0;
  document.getElementById("label").textContent = CUR.label;
  document.getElementById("meta").textContent = JSON.stringify(CUR.meta, null, 0);
  renderList(); showTurn();
}

function showTurn(){
  if (!CUR) return;
  const t = CUR.turns[IDX];
  document.getElementById("pos").textContent = (IDX+1) + " / " + CUR.turns.length;
  document.getElementById("jump").value = IDX + 1;
  const head = document.getElementById("turnhead"); head.innerHTML = "";
  head.appendChild(el("span", "chip", "Turn " + t.n));
  head.appendChild(el("span", "chip", t.timestamp));
  const box = document.getElementById("sections"); box.innerHTML = "";
  for (const s of t.sections) {
    const sec = el("div", "sec");
    const h = el("h3", null, s.name); h.appendChild(el("span", "kv", "▾")); h.onclick = () => toggle(sec); sec.appendChild(h);
    const body = el("div", "body");
    if (s.note) body.appendChild(el("div", "note", s.note));
    if (s.value === null || s.value === undefined || (Array.isArray(s.value) && s.value.length === 0)
        || (typeof s.value === "object" && Object.keys(s.value).length === 0)) {
      body.appendChild(el("div", "empty", "— not available —"));
    } else if (typeof s.value === "string") {
      const p = el("pre", null, s.value);
      if (s.name === "User message") p.classList.add("user");
      if (s.name === "Response") p.classList.add("resp");
      body.appendChild(p);
    } else {
      body.appendChild(el("pre", null, JSON.stringify(s.value, null, 2)));
    }
    sec.appendChild(body); box.appendChild(sec);
  }
  document.getElementById("first").disabled = IDX === 0;
  document.getElementById("prev").disabled = IDX === 0;
  document.getElementById("next").disabled = IDX >= CUR.turns.length - 1;
  document.getElementById("last").disabled = IDX >= CUR.turns.length - 1;
}

function toggle(sec){ sec.querySelector(".body").style.display = sec.querySelector(".body").style.display === "none" ? "" : "none"; }

document.getElementById("prev").onclick = () => { if (IDX > 0) { IDX--; showTurn(); } };
document.getElementById("next").onclick = () => { if (CUR && IDX < CUR.turns.length - 1) { IDX++; showTurn(); } };
document.getElementById("first").onclick = () => { IDX = 0; showTurn(); };
document.getElementById("last").onclick = () => { IDX = CUR.turns.length - 1; showTurn(); };
document.getElementById("jump").onchange = e => {
  const v = parseInt(e.target.value, 10);
  if (v >= 1 && v <= CUR.turns.length) { IDX = v - 1; showTurn(); }
};
document.addEventListener("keydown", e => {
  if (e.target.tagName === "INPUT") return;
  if (e.key === "ArrowRight") document.getElementById("next").click();
  if (e.key === "ArrowLeft") document.getElementById("prev").click();
});

api("/api/conversations").then(d => { LIST = d.conversations; renderList(); }).catch(console.error);
</script>
</body>
</html>
"""


if __name__ == "__main__":
    import uvicorn

    print("Conversation Replay (debug) — http://127.0.0.1:8001")
    uvicorn.run(app, host="127.0.0.1", port=8001, log_level="warning")
