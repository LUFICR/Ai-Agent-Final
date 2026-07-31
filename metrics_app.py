"""AI Metrics Dashboard — DEBUG-ONLY viewer. Run: python metrics_app.py  (port 8002)

Tracks 12 AI coach metrics from evaluation + simulation data:
  avg_coaching_score, memory_retrieval_accuracy, hypothesis_accuracy,
  objective_success, avg_conversation_length, return_user_rate,
  generic_response_rate, memory_recall_rate, recommendation_acceptance,
  question_diversity, intervention_success, hallucination_rate

Visualizes trends (per-turn metrics over conversation progress) and allows
filtering by version (v1 / v2 — evaluation commit labels).

Data sources (read-only):
  data/evaluations/index.json    judge dims per conversation (commit_id = version)
  data/simulations/{batch}/      full per-turn records (behavioral metrics)
  batch sim_main_520 -> v1, sim_cmp_100 -> v2

No production code is touched.
"""

import json
import os
import re
from collections import defaultdict
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

DATA = Path(__file__).resolve().parent / "data"
SIM_BATCHES = DATA / "simulations"
EVAL_INDEX = DATA / "evaluations" / "index.json"

BATCH_VERSION = {"sim_main_520": "v1", "sim_cmp_100": "v2"}

app = FastAPI(title="AI Metrics Dashboard (debug)", version="0.1.0")

ACCEPT_RE = re.compile(
    r"\b(yes|yeah|yep|sure|ok(ay)?|sounds (good|great)|i'?ll (try|do)|"
    r"let'?s (do|try)|good idea|absolutely|definitely|i think you'?re (onto|right))\b",
    re.I)
STOP = None  # placeholder for the turn-level metrics that need no stopwords


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _q(text):
    return [s.strip(" ?!.…") for s in re.findall(r"[^?!.]*\?", str(text or ""))]


def _stem(q):
    words = re.findall(r"[a-z]+", q.lower())
    return " ".join(words[:5])


# ─── Evaluation-based metrics (judge dims) ────────────────────────────────

def eval_metrics(version):
    idx = _read(EVAL_INDEX)
    if not idx:
        return {}
    entries = idx.get("entries", [])
    if version != "all":
        entries = [e for e in entries if e.get("commit_id") == version]
    n = len(entries)
    if n == 0:
        return {}
    def mean(key):
        vals = [e.get("dims", {}).get(key) for e in entries if e.get("dims", {}).get(key) is not None]
        return round(sum(vals) / len(vals), 1) if vals else None
    return {
        "count": n,
        "avg_coaching_score": mean("coaching"),
        "memory_retrieval_accuracy": mean("memory_usage"),
        "hypothesis_accuracy": mean("pattern_recognition"),
        "objective_success": mean("objective_completion"),
        "return_user_rate": mean("return"),
        "recommendation_acceptance": mean("recommendation_quality"),
        "hallucination_rate": None if mean("hallucination_risk") is None
                              else round(100 - mean("hallucination_risk"), 1),
    }


# ─── Simulation-based metrics (per-turn behavioral) ───────────────────────

def _records(version):
    for batch, ver in BATCH_VERSION.items():
        if version != "all" and ver != version:
            continue
        d = SIM_BATCHES / batch
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.json")):
            if f.name == "manifest.json":
                continue
            rec = _read(f)
            if rec and rec.get("turns"):
                yield rec


def sim_metrics(version):
    lengths, n_records = [], 0
    gen_turns, dup_turns, recall_turns = [], [], []
    q_total, q_stems = [], []
    offer_turns, offer_accept, offer_success = 0, 0, 0
    turn_agg = {k: defaultdict(int) for k in ("n", "generic", "recall", "diversity_num", "diversity_den",
                                              "accept_offer", "accept_yes", "interv_offer", "interv_ok")}

    for rec in _records(version):
        n_records += 1
        turns = rec.get("turns", [])
        lengths.append(rec.get("actual_turns") or len(turns))
        seen = set()
        known_facts = []
        for i, t in enumerate(turns):
            tn = i + 1
            user = t.get("user_message") or ""
            resp = t.get("assistant_response") or ""
            agg = {k: v for k, v in turn_agg.items()}  # per-version accumulators

            # generic: verbatim repeat within conversation
            key = resp.strip().lower()
            dup = key in seen and key
            if key:
                seen.add(key)
            if dup:
                dup_turns.append(tn)
                turn_agg["generic"][tn] += 1
            turn_agg["n"][tn] += 1

            # memory recall: assistant text mentions a previously stored fact value
            added = (t.get("memory_changes") or {}).get("added") or []
            recalled = False
            for fv in known_facts:
                if fv and len(fv) >= 3 and fv.lower() in resp.lower():
                    recalled = True
                    break
            if recalled:
                recall_turns.append(tn)
                turn_agg["recall"][tn] += 1
            for f in added:
                v = str(f.get("value", "") or "")
                if len(v) >= 3:
                    known_facts.append(v)

            # question diversity
            qs = _q(resp)
            if qs:
                q_total.append(len(qs))
                q_stems.extend(_stem(q) for q in qs)
                turn_agg["diversity_den"][tn] += len(qs)
                turn_agg["diversity_num"][tn] += len({_stem(q) for q in qs})

            # recommendation acceptance + intervention success
            has_offer = bool(t.get("assistant_options")) or bool(
                (t.get("engine_outputs") or {}).get("interventions"))
            if has_offer:
                offer_turns += 1
                turn_agg["accept_offer"][tn] += 1
                nxt = turns[i + 1] if i + 1 < len(turns) else None
                if nxt and ACCEPT_RE.search(nxt.get("user_message") or ""):
                    offer_accept += 1
                    turn_agg["accept_yes"][tn] += 1
                if nxt and ((nxt.get("evaluation") or {}).get("completed")):
                    offer_success += 1
                    turn_agg["interv_ok"][tn] += 1
                turn_agg["interv_offer"][tn] += 1

    if n_records == 0:
        return {}
    gen = len(dup_turns)
    turns_total = sum(turn_agg["n"].values())

    def turn_rate(key_num, key_den):
        return [round(turn_agg[key_num][k] / turn_agg[key_den][k], 3) if turn_agg[key_den][k] else None
                for k in sorted(turn_agg["n"].keys())]

    hyp_conf = []
    for rec in _records(version):
        for t in rec.get("turns", []):
            for h in (t.get("engine_outputs") or {}).get("hypotheses") or []:
                if isinstance(h, dict) and h.get("confidence"):
                    hyp_conf.append(h["confidence"])
    q_div = (len(set(q_stems)) / max(1, len(q_stems))) if q_stems else 0

    return {
        "count": n_records,
        "avg_conversation_length": round(sum(lengths) / n_records, 1),
        "generic_response_rate": round(gen / max(1, turns_total) * 100, 1),
        "memory_recall_rate": round(len(recall_turns) / max(1, turns_total) * 100, 1),
        "question_diversity": round(q_div * 100, 1),
        "recommendation_acceptance": round(offer_accept / max(1, offer_turns) * 100, 1),
        "intervention_success": round(offer_success / max(1, offer_turns) * 100, 1),
        "hypothesis_confidence": round(sum(hyp_conf) / max(1, len(hyp_conf)), 1),
        "trends": {
            "turns": sorted(turn_agg["n"].keys()),
            "generic_response_rate": turn_rate("generic", "n"),
            "memory_recall_rate": turn_rate("recall", "n"),
            "question_diversity": turn_rate("diversity_num", "diversity_den"),
            "recommendation_acceptance": turn_rate("accept_yes", "accept_offer"),
            "intervention_success": turn_rate("interv_ok", "interv_offer"),
        },
    }


def per_persona(version):
    idx = _read(EVAL_INDEX)
    if not idx:
        return []
    rows = {}
    for e in idx.get("entries", []):
        if version != "all" and e.get("commit_id") != version:
            continue
        p = e.get("persona") or e.get("persona_label") or "?"
        d = e.get("dims", {})
        r = rows.setdefault(p, {"n": 0, "coaching": 0, "memory": 0, "return": 0,
                                "objective": 0, "hallucination_risk": 0})
        r["n"] += 1
        for k, key in (("coaching", "coaching"), ("memory", "memory_usage"),
                       ("return", "return"), ("objective", "objective_completion"),
                       ("hallucination_risk", "hallucination_risk")):
            v = d.get(key)
            if v is not None:
                r[k] += v
    out = []
    for p, r in rows.items():
        out.append({
            "persona": p, "n": r["n"],
            "coaching": round(r["coaching"] / r["n"], 1),
            "memory": round(r["memory"] / r["n"], 1),
            "return": round(r["return"] / r["n"], 1),
            "objective": round(r["objective"] / r["n"], 1),
            "hallucination_rate": round(100 - r["hallucination_risk"] / r["n"], 1),
        })
    return out


METRIC_LABELS = {
    "avg_coaching_score": "Avg coaching score",
    "memory_retrieval_accuracy": "Memory retrieval accuracy",
    "hypothesis_accuracy": "Hypothesis accuracy",
    "objective_success": "Objective success",
    "avg_conversation_length": "Avg conversation length",
    "return_user_rate": "Return user rate",
    "generic_response_rate": "Generic response rate",
    "memory_recall_rate": "Memory recall rate",
    "recommendation_acceptance": "Recommendation acceptance",
    "question_diversity": "Question diversity",
    "intervention_success": "Intervention success",
    "hallucination_rate": "Hallucination rate",
}

ORDER = list(METRIC_LABELS.keys())


def compute(version):
    ev = eval_metrics(version)
    sim = sim_metrics(version)
    merged = {}
    for k in ORDER:
        v = ev.get(k)
        if v is None:
            v = sim.get(k)
        merged[k] = v
    merged.update({"evaluations": ev.get("count", 0),
                   "simulations": sim.get("count", 0),
                   "hypothesis_confidence": sim.get("hypothesis_confidence"),
                   "trends": sim.get("trends")})
    merged["per_persona"] = per_persona(version)
    return merged


# ─── API ──────────────────────────────────────────────────────────────────

@app.get("/api/metrics")
def metrics():
    return {
        "versions": ["all", "v1", "v2"],
        "labels": METRIC_LABELS,
        "order": ORDER,
        "data": {v: compute(v) for v in ("all", "v1", "v2")},
    }


@app.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse(INDEX_HTML)


INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>AI Metrics Dashboard — debug</title>
<style>
  :root { --bg:#0f1420; --panel:#171e2e; --line:#2a3450; --fg:#d7dce8; --dim:#8b93a7;
          --acc:#5aa2ff; --good:#7cd97f; --bad:#ff7d7d; --v1:#5aa2ff; --v2:#c58aff; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--fg); font:14px/1.5 "Segoe UI",system-ui,sans-serif; }
  #wrap { max-width:1200px; margin:0 auto; padding:20px 24px 60px; }
  #head { display:flex; align-items:center; gap:16px; flex-wrap:wrap; border-bottom:1px solid var(--line); padding-bottom:14px; }
  h1 { font-size:18px; margin:0; color:var(--acc); }
  #filt { margin-left:auto; }
  select { background:var(--panel); border:1px solid var(--line); color:var(--fg); border-radius:6px; padding:6px 10px; font-size:13px; }
  .sub { color:var(--dim); font-size:12px; margin:8px 0 0; }
  #cards { display:grid; grid-template-columns:repeat(auto-fill,minmax(220px,1fr)); gap:12px; margin:18px 0; }
  .card { background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:14px 16px; }
  .card .name { color:var(--dim); font-size:12px; }
  .card .val { font-size:26px; font-weight:700; margin-top:4px; }
  .card .delta { font-size:12px; margin-top:2px; }
  .up { color:var(--good); } .down { color:var(--bad); } .flat { color:var(--dim); }
  h2 { font-size:15px; margin:26px 0 8px; color:var(--fg); }
  #bars { display:flex; flex-direction:column; gap:8px; }
  .barrow { display:grid; grid-template-columns:230px 1fr 1fr 90px; gap:8px; align-items:center; }
  .barrow .lbl { font-size:12.5px; text-align:right; }
  .track { background:#10162a; border-radius:4px; height:16px; position:relative; overflow:hidden; }
  .fill { height:100%; border-radius:4px; }
  .barrow .delta { font-size:12px; font-variant-numeric:tabular-nums; }
  #trendbox { background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:14px; }
  #trendsel { margin-bottom:10px; }
  svg { width:100%; height:280px; background:#10162a; border-radius:8px; }
  table { width:100%; border-collapse:collapse; background:var(--panel); border:1px solid var(--line); border-radius:10px; overflow:hidden; }
  th, td { padding:8px 12px; text-align:right; border-bottom:1px solid var(--line); font-size:13px; }
  th { background:#1a2236; color:var(--dim); font-weight:600; }
  th:first-child, td:first-child { text-align:left; }
  tr:last-child td { border-bottom:none; }
  .legend { display:flex; gap:16px; color:var(--dim); font-size:12px; margin-top:6px; }
  .sw { display:inline-block; width:10px; height:10px; border-radius:2px; margin-right:4px; }
</style>
</head>
<body>
<div id="wrap">
  <div id="head">
    <h1>AI Metrics Dashboard</h1>
    <div id="filt">
      <label for="ver" style="color:var(--dim);font-size:12px">Version&nbsp;</label>
      <select id="ver"></select>
    </div>
  </div>
  <p class="sub" id="meta"></p>
  <div id="cards"></div>
  <h2>Metrics by version</h2>
  <div id="bars"></div>
  <h2>Trends by turn of conversation</h2>
  <div id="trendbox">
    <select id="trendsel"></select>
    <div class="legend"><span><span class="sw" style="background:var(--v1)"></span>v1</span>
      <span><span class="sw" style="background:var(--v2)"></span>v2</span>
      <span>▼ = delta vs all</span></div>
    <div id="chart"></div>
  </div>
  <h2>Per-persona breakdown</h2>
  <div id="persona"></div>
</div>
<script>
let M = null, VER = "all", TREND = "generic_response_rate";
const fmt = v => v === null || v === undefined ? "—" : (Number.isInteger(v) ? v : v.toFixed(1));
const pct = v => v === null || v === undefined ? "—" : v.toFixed(1) + "%";

async function load(){
  M = await (await fetch("/api/metrics")).json();
  const sel = document.getElementById("ver");
  for (const v of M.versions) {
    const o = document.createElement("option"); o.value = v;
    o.textContent = v === "all" ? "All versions" : v.toUpperCase();
    sel.appendChild(o);
  }
  const ts = document.getElementById("trendsel");
  for (const k of ["generic_response_rate","memory_recall_rate","question_diversity",
                   "recommendation_acceptance","intervention_success"]) {
    const o = document.createElement("option"); o.value = k;
    o.textContent = M.labels[k]; ts.appendChild(o);
  }
  render();
}

function delta(v, all){
  if (v === null || all === null || all === undefined) return "";
  if (all === 0) return "";
  const d = ((v - all) / all) * 100;
  return (d >= 0 ? "▲ +" : "▼ ") + Math.abs(d).toFixed(0) + "%";
}

function render(){
  const d = M.data[VER];
  const meta = `evaluations: ${d.evaluations} · simulations: ${d.simulations} · ` +
               `per-trend window: turns 1–${(d.trends.turns || []).length || "?"}`;
  document.getElementById("meta").textContent = meta;
  const cards = document.getElementById("cards"); cards.innerHTML = "";
  const all = M.data["all"];
  for (const k of M.order) {
    const v = d[k];
    const isPct = !["avg_conversation_length"].includes(k);
    const card = document.createElement("div"); card.className = "card";
    card.innerHTML = `<div class="name">${M.labels[k]}</div>
      <div class="val">${isPct ? pct(v) : fmt(v)}</div>
      <div class="delta ${delta(v, all[k]).startsWith("▼") ? "down" : delta(v, all[k]).startsWith("▲") ? "up" : "flat"}">${delta(v, all[k]) || "vs all versions"}</div>`;
    cards.appendChild(card);
  }
  const bars = document.getElementById("bars"); bars.innerHTML = "";
  for (const k of M.order) {
    const v1 = M.data["v1"][k], v2 = M.data["v2"][k], cur = d[k];
    const max = Math.max(1, ...[v1, v2].filter(x => x !== null));
    const isPct = !["avg_conversation_length"].includes(k);
    const w1 = ((v1 ?? 0) / max) * 100, w2 = ((v2 ?? 0) / max) * 100;
    const row = document.createElement("div"); row.className = "barrow";
    row.innerHTML = `
      <div class="lbl">${M.labels[k]}</div>
      <div class="track"><div class="fill" style="width:${w1}%;background:var(--v1)" title="v1: ${fmt(v1)}"></div></div>
      <div class="track"><div class="fill" style="width:${w2}%;background:var(--v2)" title="v2: ${fmt(v2)}"></div></div>
      <div class="delta">${v1 !== null && v2 !== null ? delta(v2, v1) : ""}</div>`;
    bars.appendChild(row);
  }
  renderTrend();
  renderPersona();
}

function renderTrend(){
  const d = M.data[VER];
  const series = {v1: M.data["v1"].trends[TREND], v2: M.data["v2"].trends[TREND],
                  cur: d.trends[TREND]};
  const turns = d.trends.turns || [];
  const svg = document.getElementById("chart");
  const W = 1160, H = 280, P = {l: 46, r: 14, t: 14, b: 30};
  const xs = [...(M.data.v1.trends.turns || []), ...(M.data.v2.trends.turns || []), ...turns];
  const xmax = Math.max(1, ...xs);
  const vals = [series.v1, series.v2, series.cur].flat().filter(v => v !== null);
  const ymax = Math.max(1, ...(vals.length ? vals : [1]));
  const x = i => P.l + (i / xmax) * (W - P.l - P.r);
  const y = v => H - P.b - (v / ymax) * (H - P.t - P.b);
  let out = `<svg viewBox="0 0 ${W} ${H}">`;
  for (let i = 0; i <= 5; i++) {
    const gy = P.t + (i / 5) * (H - P.t - P.b);
    out += `<line x1="${P.l}" y1="${gy}" x2="${W - P.r}" y2="${gy}" stroke="#232e4a" stroke-width="1"/>`;
    out += `<text x="${P.l - 8}" y="${gy + 4}" fill="#8b93a7" font-size="11" text-anchor="end">${(ymax * (1 - i / 5)).toFixed(2)}</text>`;
  }
  const line = (data, color, dash) => {
    const pts = turns.map((_, i) => `${x(i)},${y(data[i] ?? 0)}`).join(" ");
    return `<polyline points="${pts}" fill="none" stroke="${color}" stroke-width="2" ${dash}/>`;
  };
  if (VER === "all") {
    out += line(series.v1, "var(--v1)", "");
    out += line(series.v2, "var(--v2)", "");
  } else {
    out += line(series.cur, "var(--acc)", "");
  }
  for (let i = 1; i <= Math.min(25, xmax); i += Math.max(1, Math.round(xmax / 10))) {
    out += `<text x="${x(i)}" y="${H - 10}" fill="#8b93a7" font-size="11" text-anchor="middle">${i}</text>`;
  }
  out += "</svg>";
  svg.innerHTML = out;
}

function renderPersona(){
  const d = M.data[VER];
  const t = document.getElementById("persona");
  if (!d.per_persona.length) { t.innerHTML = '<div class="empty" style="color:var(--dim)">no data</div>'; return; }
  let html = "<table><tr><th>persona</th><th>n</th><th>coaching</th><th>memory</th><th>objective</th><th>return</th><th>hallucination rate</th></tr>";
  for (const r of d.per_persona.sort((a, b) => b.coaching - a.coaching))
    html += `<tr><td>${r.persona}</td><td>${r.n}</td><td>${fmt(r.coaching)}</td><td>${fmt(r.memory)}</td>
             <td>${fmt(r.objective)}</td><td>${fmt(r.return)}</td><td>${pct(r.hallucination_rate)}</td></tr>`;
  t.innerHTML = html + "</table>";
}

document.getElementById("ver").onchange = e => { VER = e.target.value; render(); };
document.getElementById("trendsel").onchange = e => { TREND = e.target.value; renderTrend(); };
load();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    import uvicorn

    print("AI Metrics Dashboard (debug) — http://127.0.0.1:8002")
    uvicorn.run(app, host="127.0.0.1", port=8002, log_level="warning")
