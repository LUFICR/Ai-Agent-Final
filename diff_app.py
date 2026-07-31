"""Conversation Diff — DEBUG-ONLY viewer. Run: python diff_app.py  (port 8003)

Runs the same user conversation through the OLD AI (recorded v1 sim records,
data/simulations/sim_main_520) and the CURRENT AI (the user script replayed
through the live orchestrator offline), then compares:

  Memory, Questions, Recommendations, Coaching, Empathy,
  Pattern detection, Objectives

and generates per conversation / per batch:
  Winner (OLD vs CURRENT), Regression, Improvement, Confidence
  + exact per-turn response differences (word-level diff, highlighted)

Both runs are scored with the SAME current judge code (deterministic,
no evaluation-store writes). No production code is touched.
"""

import json
import os
import re
import sys
import difflib
import html as html_mod
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

sys.path.insert(0, str(Path(__file__).resolve().parent))

DATA = Path(__file__).resolve().parent / "data"
OLD_BATCH = DATA / "simulations" / "sim_main_520"

app = FastAPI(title="Conversation Diff (debug)", version="0.1.0")

CACHE = {}
_METRICS = ["coaching", "empathy", "curiosity", "memory_usage", "pattern_recognition",
            "recommendation_quality", "objective_completion"]
METRIC_NAMES = {
    "coaching": "Coaching", "empathy": "Empathy", "curiosity": "Questions",
    "memory_usage": "Memory", "pattern_recognition": "Pattern detection",
    "recommendation_quality": "Recommendations", "objective_completion": "Objectives",
}


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _cleanup(user_id):
    try:
        from simulation.simulator import _cleanup_stores
        _cleanup_stores(user_id)
    except Exception:
        pass


def list_old():
    out = []
    if not OLD_BATCH.is_dir():
        return out
    for f in sorted(OLD_BATCH.glob("*.json")):
        if f.name == "manifest.json":
            continue
        rec = _read(f)
        if not rec or not rec.get("turns"):
            continue
        out.append({
            "sim_id": rec.get("sim_id") or f.stem,
            "persona": rec.get("persona_label") or rec.get("persona_id"),
            "seed": rec.get("seed"),
            "turns": len(rec["turns"]),
            "ended": rec.get("ended"),
        })
    return out


def _top3(d):
    """First 3 entries of a list or dict."""
    if isinstance(d, dict):
        return list(d.values())[:3]
    return list(d or [])[:3]


def run_current(messages, uid):
    """Replay a user script through the current orchestrator (offline)."""
    os.environ.pop("GROQ_API_KEY", None)
    _cleanup(uid)
    from wellness_agent.orchestrator import Orchestrator
    orch = Orchestrator(user_id=uid, enable_auto_judge=False)
    turns = []
    for msg in messages:
        res = orch.process_message(msg)
        mem_before = {f.get("key") for f in orch.agents.memory.get_all_facts()}
        mem_after = orch.agents.memory.get_all_facts()
        added = [{"key": f.get("key"), "value": str(f.get("value", ""))[:60]}
                 for f in mem_after if f.get("key") not in mem_before]
        turns.append({
            "n": len(turns) + 1,
            "user_message": msg,
            "assistant_response": res.get("response"),
            "state": (res.get("state") or {}).get("current_state"),
            "route": res.get("route") or [],
            "objective": (res.get("objective") or {}).get("objective"),
            "emotion": (res.get("emotion") or {}).get("primary_emotion"),
            "llm_used": False,
            "options": res.get("options") or [],
            "ranked_interventions": [i.get("title") or i.get("intervention")
                                     for i in (res.get("ranked_interventions") or [])][:3],
            "memory_changes": {"added": added, "added_count": len(added),
                               "facts_total": len(mem_after),
                               "trust_score": orch.agents.memory.get_trust_score()},
            "whys": _top3(orch.agents.why_engine.get_patterns()),
            "hypotheses": _top3(orch.agents.hypothesis_engine.get_hypotheses()),
        })
    _cleanup(uid)
    return turns


def judge_dims(turns):
    from wellness_agent.conversation_judge import ConversationJudge
    judge = ConversationJudge(user_id="diff_judge")
    payload = {"turns": [judge._normalize_turn(t) for t in turns],
               "memory": None, "trust_score": None, "beliefs": None,
               "reasoning_context": None, "ended": "complete"}
    return judge._score_dimensions(judge._signals(payload))


def _questions(resp):
    return [s.strip(" ?!.…") for s in re.findall(r"[^?!.]*\?", str(resp or ""))]


def _word_diff(old, new):
    """Word-level HTML diff with <del>/<ins> markers."""
    sm = difflib.SequenceMatcher(None, old.split(), new.split())
    out = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        a = " ".join(old.split()[i1:i2])
        b = " ".join(new.split()[j1:j2])
        if tag == "equal":
            out.append(html_mod.escape(a))
        elif tag == "delete":
            out.append(f'<del>{html_mod.escape(a)}</del>')
        elif tag == "insert":
            out.append(f'<ins>{html_mod.escape(b)}</ins>')
        elif tag == "replace":
            if a:
                out.append(f'<del>{html_mod.escape(a)}</del>')
            if b:
                out.append(f'<ins>{html_mod.escape(b)}</ins>')
    return " ".join(out)


def _normalize_old_turn(t):
    return {
        "n": t.get("n"),
        "user_message": t.get("user_message"),
        "assistant_response": t.get("assistant_response"),
        "state": t.get("state"),
        "objective": t.get("objective"),
        "route": t.get("route") or [],
        "emotion": t.get("emotion"),
        "llm_used": bool(t.get("llm_used")),
        "options": t.get("assistant_options") or [],
        "interventions": [(i.get("title") or i.get("intervention"))
                          for i in ((t.get("engine_outputs") or {}).get("interventions") or [])][:3],
        "memory_changes": t.get("memory_changes") or {},
        "whys": (t.get("engine_outputs") or {}).get("whys") or [],
        "hypotheses": (t.get("engine_outputs") or {}).get("hypotheses") or [],
    }


def diff_conversation(sim_id):
    if sim_id in CACHE:
        return CACHE[sim_id]
    old_rec = None
    for f in OLD_BATCH.glob("*.json"):
        rec = _read(f)
        if rec and rec.get("sim_id") == sim_id:
            old_rec = rec
            break
    if old_rec is None:
        return None

    old_turns = [_normalize_old_turn(t) for t in old_rec.get("turns", [])]
    messages = [t["user_message"] for t in old_turns]
    new_turns = run_current(messages, f"diff_{sim_id}")

    old_dims = judge_dims(old_turns)
    new_dims = judge_dims(new_turns)

    # per-turn compare
    pairs = []
    for i, o in enumerate(old_turns):
        nw = new_turns[i] if i < len(new_turns) else {}
        old_q = _questions(o["assistant_response"])
        new_q = _questions(nw.get("assistant_response"))
        o_added = [f.get("key") for f in (o.get("memory_changes") or {}).get("added", [])]
        n_added = [f.get("key") for f in (nw.get("memory_changes") or {}).get("added", [])]
        pairs.append({
            "n": i + 1,
            "user_message": o["user_message"],
            "old": {
                "response": o["assistant_response"],
                "response_diff": _word_diff(o["assistant_response"] or "", nw.get("assistant_response") or ""),
                "state": o["state"], "objective": o["objective"],
                "questions": old_q, "interventions": o["interventions"],
                "whys": [w.get("why") or w.get("pattern") or w for w in o["whys"]][:3],
                "hypotheses": [(h.get("hypothesis"), h.get("confidence")) for h in o["hypotheses"]][:3],
                "memory_added": o_added,
                "memory_total": (o.get("memory_changes") or {}).get("facts_total"),
                "trust": (o.get("memory_changes") or {}).get("trust_score"),
            },
            "current": {
                "response": nw.get("assistant_response"),
                "state": nw.get("state"), "objective": nw.get("objective"),
                "questions": new_q, "interventions": nw.get("ranked_interventions") or [],
                "whys": [w.get("why") or w.get("pattern") or w for w in (nw.get("whys") or [])][:3],
                "hypotheses": [(h.get("hypothesis"), h.get("confidence")) for h in (nw.get("hypotheses") or [])][:3],
                "memory_added": n_added,
                "memory_total": (nw.get("memory_changes") or {}).get("facts_total"),
                "trust": (nw.get("memory_changes") or {}).get("trust_score"),
            },
        })

    # winner / regression / improvement / confidence
    deltas = {}
    for m in _METRICS:
        o, n = old_dims.get(m), new_dims.get(m)
        deltas[m] = round((n or 0) - (o or 0), 1) if o is not None else None
    total = sum(abs(d) for d in deltas.values() if d is not None)
    signed = sum(d for d in deltas.values() if d is not None)
    winner = "CURRENT" if signed > 0.5 else ("OLD" if signed < -0.5 else "TIE")
    agree = sum(abs(d) for m, d in deltas.items() if d is not None and
                ((d > 0) == (signed > 0)))
    confidence = round(100 * agree / total, 1) if total else 50.0
    regressions = {METRIC_NAMES[m]: d for m, d in deltas.items()
                   if d is not None and d < -0.5}
    improvements = {METRIC_NAMES[m]: d for m, d in deltas.items()
                    if d is not None and d > 0.5}

    result = {
        "sim_id": sim_id,
        "persona": old_rec.get("persona_label") or old_rec.get("persona_id"),
        "seed": old_rec.get("seed"),
        "turns": len(pairs),
        "old_ended": old_rec.get("ended"),
        "dims": {"old": old_dims, "current": new_dims},
        "deltas": deltas,
        "winner": winner,
        "confidence": confidence,
        "regressions": regressions,
        "improvements": improvements,
        "pairs": pairs,
    }
    CACHE[sim_id] = result
    return result


def batch_diff(limit=20):
    convs = list_old()
    if limit and limit > 0:
        convs = convs[:limit]
    rows = []
    win = {"OLD": 0, "CURRENT": 0, "TIE": 0}
    agg = {m: [] for m in _METRICS}
    for c in convs:
        d = diff_conversation(c["sim_id"])
        if not d:
            continue
        rows.append({"sim_id": d["sim_id"], "persona": d["persona"],
                     "seed": d["seed"], "winner": d["winner"],
                     "confidence": d["confidence"],
                     "deltas": d["deltas"], "regressions": d["regressions"],
                     "improvements": d["improvements"]})
        win[d["winner"]] += 1
        for m in _METRICS:
            if d["deltas"][m] is not None:
                agg[m].append(d["deltas"][m])
    return {
        "limit": len(rows),
        "winners": win,
        "avg_deltas": {m: round(sum(v) / len(v), 1) if v else None for m, v in agg.items()},
        "rows": rows,
    }


# ─── API ──────────────────────────────────────────────────────────────────

@app.get("/api/conversations")
def conversations():
    return {"conversations": list_old()}


@app.get("/api/diff/{sim_id}")
def diff(sim_id: str):
    d = diff_conversation(sim_id)
    if d is None:
        return JSONResponse({"error": "conversation not found"}, status_code=404)
    return d


@app.get("/api/batch")
def batch(limit: int = 20):
    return batch_diff(limit)


@app.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse(INDEX_HTML)


INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Conversation Diff — debug</title>
<style>
  :root { --bg:#0f1420; --panel:#171e2e; --line:#2a3450; --fg:#d7dce8; --dim:#8b93a7;
          --acc:#5aa2ff; --good:#7cd97f; --bad:#ff7d7d; --old:#c58aff; --cur:#5aa2ff; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--fg); font:14px/1.5 "Segoe UI",system-ui,sans-serif; }
  #layout { display:flex; height:100vh; }
  #side { width:280px; min-width:280px; border-right:1px solid var(--line); overflow:auto; padding:10px; }
  #main { flex:1; overflow:auto; padding:18px 24px; }
  h1 { font-size:15px; margin:6px 8px 12px; color:var(--acc); }
  .conv { display:block; width:100%; text-align:left; background:var(--panel); border:1px solid var(--line);
          color:var(--fg); border-radius:6px; padding:7px 10px; margin:3px 0; cursor:pointer; font-size:12.5px; }
  .conv:hover, .conv.active { border-color:var(--acc); }
  .conv small { display:block; color:var(--dim); }
  #batchbtn { width:100%; margin:8px 0; }
  #head { display:flex; align-items:center; gap:14px; flex-wrap:wrap; border-bottom:1px solid var(--line); padding-bottom:12px; }
  #label { font-size:17px; font-weight:600; }
  #banner { padding:10px 14px; border-radius:8px; font-weight:700; font-size:15px; }
  .w-CURRENT { background:#12301f; color:var(--good); border:1px solid var(--good); }
  .w-OLD { background:#3a1515; color:var(--bad); border:1px solid var(--bad); }
  .w-TIE { background:#2a2a2a; color:var(--dim); border:1px solid var(--dim); }
  table { border-collapse:collapse; width:100%; background:var(--panel); border:1px solid var(--line); border-radius:8px; overflow:hidden; margin:12px 0; }
  th, td { padding:7px 12px; text-align:right; border-bottom:1px solid var(--line); font-size:13px; }
  th { background:#1a2236; color:var(--dim); }
  th:first-child, td:first-child { text-align:left; }
  .up { color:var(--good); } .dn { color:var(--bad); }
  #ctrl { display:flex; gap:6px; align-items:center; margin:14px 0; }
  button { background:var(--panel); border:1px solid var(--line); color:var(--fg); border-radius:6px; padding:6px 12px; cursor:pointer; }
  button:hover:not(:disabled) { border-color:var(--acc); }
  button:disabled { opacity:.35; }
  .turn { background:var(--panel); border:1px solid var(--line); border-radius:8px; margin:12px 0; padding:12px 14px; }
  .user { color:#ffd479; font-weight:600; margin-bottom:8px; }
  .resp { white-space:pre-wrap; font-size:13px; }
  del { background:#5a1d1d; color:#ffb3b3; text-decoration:line-through; border-radius:3px; padding:0 2px; }
  ins { background:#1d4d2a; color:#b3ffc0; text-decoration:none; border-radius:3px; padding:0 2px; }
  .cmp { display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-top:8px; }
  .cmp .box { background:#10162a; border-radius:6px; padding:8px 10px; font-size:12.5px; }
  .cmp .box h4 { margin:0 0 4px; font-size:11px; color:var(--dim); text-transform:uppercase; letter-spacing:.06em; }
  .tag { display:inline-block; background:#22304f; border-radius:10px; padding:1px 8px; font-size:11.5px; margin:1px 2px; }
  .missing { color:var(--dim); font-style:italic; }
  h2 { font-size:15px; margin:20px 0 6px; }
  #agg table td { font-size:12.5px; }
</style>
</head>
<body>
<div id="layout">
  <div id="side">
    <h1>Conversation Diff</h1>
    <button id="batchbtn">Run batch diff (first 20)</button>
    <div id="list"><div class="missing">loading…</div></div>
  </div>
  <div id="main">
    <div id="head"><div id="label">select a v1 conversation</div><div id="banner" hidden></div></div>
    <div id="detail"></div>
  </div>
</div>
<script>
let CONVS = [], CUR = null;

async function api(p){ const r = await fetch(p); if(!r.ok) throw new Error(r.status); return r.json(); }
const esc = s => (s === null || s === undefined) ? "—" : String(s).replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
const fmt = v => v === null || v === undefined ? "—" : (Number.isInteger(v) ? v : v.toFixed(1));

function list(){
  const box = document.getElementById("list"); box.innerHTML = "";
  for (const c of CONVS) {
    const b = document.createElement("button"); b.className = "conv";
    b.innerHTML = esc(c.persona) + " · " + esc(c.sim_id) + "<small>" + c.turns + " turns · seed " + c.seed + "</small>";
    b.onclick = () => openDiff(c.sim_id);
    box.appendChild(b);
  }
}

async function openDiff(id){
  CUR = await api("/api/diff/" + encodeURIComponent(id));
  const banner = document.getElementById("banner");
  banner.hidden = false;
  banner.className = "w-" + CUR.winner;
  banner.textContent = "Winner: " + CUR.winner + "  ·  confidence " + CUR.confidence + "%";
  document.getElementById("label").textContent = CUR.persona + " (" + CUR.sim_id + ") — " + CUR.turns + " turns";
  render();
}

function render(){
  const d = document.getElementById("detail"); d.innerHTML = "";
  const h = document.createElement("div");
  h.innerHTML = `
    <h2>Metrics — OLD vs CURRENT</h2>
    <table><tr><th>metric</th><th>OLD</th><th>CURRENT</th><th>delta</th><th>winner</th></tr>
    ${Object.entries(CUR.deltas).map(([m, dv]) => `
      <tr><td>${esc(m)}</td><td>${fmt(CUR.dims.old[m])}</td><td>${fmt(CUR.dims.current[m])}</td>
      <td class="${dv > 0.5 ? 'up' : dv < -0.5 ? 'dn' : ''}">${dv > 0 ? "+" : ""}${fmt(dv)}</td>
      <td>${dv > 0.5 ? "CURRENT" : dv < -0.5 ? "OLD" : "tie"}</td></tr>`).join("")}
    </table>
    <h2>Regressions</h2><div>${Object.keys(CUR.regressions).length ? Object.entries(CUR.regressions).map(([k, v]) => `<span class="tag">${esc(k)} ${v}</span>`).join(" ") : "<span class='missing'>none</span>"}</div>
    <h2>Improvements</h2><div>${Object.keys(CUR.improvements).length ? Object.entries(CUR.improvements).map(([k, v]) => `<span class="tag">${esc(k)} +${v}</span>`).join(" ") : "<span class='missing'>none</span>"}</div>`;
  d.appendChild(h);
  let i = 0;
  const turnBox = document.createElement("div"); turnBox.id = "turnbox"; d.appendChild(turnBox);
  const ctrl = document.createElement("div"); ctrl.id = "ctrl"; d.insertBefore(ctrl, turnBox);
  const show = () => {
    const p = CUR.pairs[i], o = p.old, c = p.current;
    ctrl.innerHTML = `<button id="prev" ${i === 0 ? "disabled" : ""}>←</button><span id="pos">turn ${i + 1} / ${CUR.pairs.length}</span><button id="next" ${i >= CUR.pairs.length - 1 ? "disabled" : ""}>→</button>`;
    document.getElementById("prev").onclick = () => { i--; show(); };
    document.getElementById("next").onclick = () => { i++; show(); };
    turnBox.innerHTML = `
      <div class="turn">
        <div class="user">T${p.n} · ${esc(p.user_message)}</div>
        <div class="cmp">
          <div class="box"><h4>OLD response</h4><div class="resp">${o.response_diff || esc(o.response)}</div></div>
          <div class="box"><h4>CURRENT response</h4><div class="resp">${esc(c.response)}</div></div>
        </div>
        <div class="cmp">
          <div class="box"><h4>OLD · state/objective/memory</h4>
            state: <span class="tag">${esc(o.state)}</span> obj: <span class="tag">${esc(o.objective)}</span><br>
            questions: ${(o.questions || []).map(q => `<span class="tag">${esc(q)}</span>`).join(" ") || "<span class='missing'>none</span>"}<br>
            recommendations: ${(o.interventions || []).map(x => `<span class="tag">${esc(x)}</span>`).join(" ") || "<span class='missing'>none</span>"}<br>
            memory added: ${(o.memory_added || []).map(x => `<span class="tag">${esc(x)}</span>`).join(" ") || "<span class='missing'>none</span>"} · total ${fmt(o.memory_total)} · trust ${fmt(o.trust)}<br>
            patterns: ${(o.hypotheses || []).map(h => `<span class="tag">${esc(h[0])} (${h[1]})</span>`).join(" ") || "<span class='missing'>none</span>"}</div>
          <div class="box"><h4>CURRENT · state/objective/memory</h4>
            state: <span class="tag">${esc(c.state)}</span> obj: <span class="tag">${esc(c.objective)}</span><br>
            questions: ${(c.questions || []).map(q => `<span class="tag">${esc(q)}</span>`).join(" ") || "<span class='missing'>none</span>"}<br>
            recommendations: ${(c.interventions || []).map(x => `<span class="tag">${esc(x)}</span>`).join(" ") || "<span class='missing'>none</span>"}<br>
            memory added: ${(c.memory_added || []).map(x => `<span class="tag">${esc(x)}</span>`).join(" ") || "<span class='missing'>none</span>"} · total ${fmt(c.memory_total)} · trust ${fmt(c.trust)}<br>
            patterns: ${(c.hypotheses || []).map(h => `<span class="tag">${esc(h[0])} (${h[1]})</span>`).join(" ") || "<span class='missing'>none</span>"}</div>
        </div>
      </div>`;
  };
  show();
}

document.getElementById("batchbtn").onclick = async () => {
  const agg = await api("/api/batch?limit=20");
  const d = document.getElementById("detail");
  d.innerHTML = `<h2>Batch diff — first ${agg.limit} conversations</h2>
    <div id="banner" class="w-TIE" style="margin:10px 0">winners → OLD ${agg.winners.OLD} · CURRENT ${agg.winners.CURRENT} · TIE ${agg.winners.TIE}</div>
    <table><tr><th>metric</th><th>avg delta</th></tr>
    ${Object.entries(agg.avg_deltas).map(([m, v]) => `<tr><td>${esc(m)}</td><td class="${v > 0.5 ? 'up' : v < -0.5 ? 'dn' : ''}">${v > 0 ? "+" : ""}${fmt(v)}</td></tr>`).join("")}</table>
    <h2>Per conversation</h2>
    <table><tr><th>conversation</th><th>winner</th><th>confidence</th><th>deltas</th></tr>
    ${agg.rows.map(r => `<tr><td>${esc(r.sim_id)}</td><td class="${r.winner === 'CURRENT' ? 'up' : r.winner === 'OLD' ? 'dn' : ''}">${r.winner}</td>
      <td>${r.confidence}%</td><td style="font-size:11.5px">${Object.entries(r.deltas).filter(([, v]) => Math.abs(v) > 0.5).map(([k, v]) => `${esc(k)} ${v > 0 ? "+" : ""}${v}`).join(" · ") || "—"}</td></tr>`).join("")}</table>`;
};

api("/api/conversations").then(d => { CONVS = d.conversations; list(); }).catch(console.error);
</script>
</body>
</html>
"""


if __name__ == "__main__":
    import uvicorn

    print("Conversation Diff (debug) — http://127.0.0.1:8003")
    uvicorn.run(app, host="127.0.0.1", port=8003, log_level="warning")
