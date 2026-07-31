"""User Outcome Tracking — DEBUG-ONLY viewer. Run: python outcome_app.py (port 8004)

Measures USER IMPROVEMENT over time (not conversation quality):

  Stress trend, Mood trend, Routine adherence, Goal completion,
  Conversation frequency, Self awareness, Reflection quality,
  Behavior changes, Confidence, Hope, Motivation

Generates:
  30-day progress, 90-day progress, intervention effectiveness,
  highest-ROI coaching methods (learned across users ->
  data/outcomes/learned_methods.json)

Sources (read-only):
  data/simulations/sim_main_520 (v1) + sim_cmp_100 (v2): multi-day user
  journeys with per-turn persona state (stress/mood/anxiety/engagement),
  tags (missed_routine, open_up, goal_change, positive_shift), objectives,
  evaluations and memory changes.
  data/sessions: live users (best-effort, fewer signals).

Windows: sim journeys are day-offset based (span <= ~21 days). "30-day" =
first 10 days vs last 10 days (or first/last half on shorter journeys),
"90-day" = first third vs last third (full span). Actual spans are labeled.

No production code is touched.
"""

import json
import re
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

DATA = Path(__file__).resolve().parent / "data"
OUTCOMES_DIR = DATA / "outcomes"
OUTCOMES_DIR.mkdir(exist_ok=True)

app = FastAPI(title="User Outcome Tracking (debug)", version="0.1.0")

OUTCOME_KEYS = ["stress", "mood", "routine_adherence", "goal_completion",
                "conversation_frequency", "self_awareness", "reflection_quality",
                "behavior_changes", "confidence", "hope", "motivation"]

OUTCOME_LABELS = {
    "stress": "Stress trend", "mood": "Mood trend",
    "routine_adherence": "Routine adherence", "goal_completion": "Goal completion",
    "conversation_frequency": "Conversation frequency",
    "self_awareness": "Self awareness", "reflection_quality": "Reflection quality",
    "behavior_changes": "Behavior changes", "confidence": "Confidence",
    "hope": "Hope", "motivation": "Motivation",
}

HOPE_UP = {"hopeful", "grateful", "positive", "optimistic", "excited", "content",
           "calm", "relieved", "happy", "joy"}
HOPE_DOWN = {"hopeless", "depressed", "sad", "despairing", "miserable"}
MOT_UP = {"motivated", "energetic", "determined", "excited", "happy", "confident"}
MOT_DOWN = {"exhausted", "tired", "hopeless", "lethargic", "unmotivated", "drained"}
CONF_UP = {"calm", "confident", "hopeful", "content", "relieved", "motivated"}
CONF_DOWN = {"anxious", "stressed", "overwhelmed", "worried", "nervous", "scared", "afraid"}
STRESS_UP = {"anxious", "stressed", "overwhelmed", "worried", "nervous", "scared", "angry"}
STRESS_DOWN = {"calm", "relaxed", "peaceful", "content", "relieved"}

REFLECT_STATES = {"reflection", "insight_generation", "weekly_review", "follow_up"}
PROGRESS_STATES = {"guided_discovery", "deep_investigation", "insight_generation",
                   "routine_planning", "reflection", "follow_up", "weekly_review"}


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _clamp(v, lo=0.0, hi=100.0):
    return max(lo, min(hi, v))


def _emotion_scores(emotion):
    e = str(emotion or "neutral").lower()
    def score(up, down):
        s = 50.0
        if e in up:
            s += 18
        if e in down:
            s -= 18
        return _clamp(s)
    return {"hope": score(HOPE_UP, HOPE_DOWN),
            "motivation": score(MOT_UP, MOT_DOWN),
            "confidence": score(CONF_UP, CONF_DOWN),
            "stress": 100 - score(STRESS_UP, STRESS_DOWN)}


# ─── Sim user outcome timeline ────────────────────────────────────────────

def _sim_user(rec):
    turns = rec.get("turns", [])
    uid = rec.get("sim_id") or "?"
    version = "v2" if "sim_cmp_100" in (rec.get("_batch") or "") else "v1"
    if not turns:
        return None

    by_day = defaultdict(lambda: {
        "turns": 0, "ps_stress": [], "ps_mood": [], "ps_engage": [],
        "missed_routine": 0, "open_up": 0, "goal_change": 0, "positive_shift": 0,
        "risk": 0, "completed": 0, "objective_set": 0, "reflect": 0,
        "emotion_scores": [], "habits_added": 0, "facts_added": 0,
        "trait_changes": 0})
    max_day_turns = 1
    prev_ps = None
    for t in turns:
        d = t.get("day_offset", 0)
        row = by_day[d]
        row["turns"] += 1
        max_day_turns = max(max_day_turns, row["turns"])
        ps = t.get("persona_state") or {}
        emo = ps.get("emotion") or {}
        if emo:
            row["ps_stress"].append((emo.get("stress", 50) + emo.get("anxiety", 50)) / 2)
            row["ps_mood"].append(emo.get("mood", 50))
            row["ps_engage"].append(emo.get("engagement", 50))
            if prev_ps is not None and any(abs(emo.get(k, 50) - prev_ps.get(k, 50)) > 10
                                           for k in ("stress", "mood", "anxiety", "energy",
                                                     "loneliness", "engagement")):
                row["trait_changes"] += 1
            prev_ps = emo
        es = _emotion_scores(t.get("emotion"))
        row["emotion_scores"].append(es)
        if t.get("risk_detected") or (t.get("route") or []) == ["risk_protocol"]:
            row["risk"] += 1
        tags = t.get("tags") or []
        if "missed_routine" in tags:
            row["missed_routine"] += 1
        if "open_up" in tags:
            row["open_up"] += 1
        if "goal_change" in tags:
            row["goal_change"] += 1
        if "positive_shift" in tags:
            row["positive_shift"] += 1
        if t.get("state") in REFLECT_STATES:
            row["reflect"] += 1
        ev = t.get("evaluation") or {}
        if ev.get("objective"):
            row["objective_set"] += 1
        if ev.get("completed"):
            row["completed"] += 1
        mc = t.get("memory_changes") or {}
        added = mc.get("added") or []
        row["facts_added"] += len(added)
        for f in added:
            if str(f.get("key", "")).startswith(("sleep", "exercise", "nutrition", "bedtime")):
                row["habits_added"] += 1

    days = sorted(by_day)
    timeline = []
    for d in days:
        r = by_day[d]
        n = max(1, r["turns"])
        ps_stress = sum(r["ps_stress"]) / len(r["ps_stress"]) if r["ps_stress"] else 50
        ps_mood = sum(r["ps_mood"]) / len(r["ps_mood"]) if r["ps_mood"] else 50
        engage = sum(r["ps_engage"]) / len(r["ps_engage"]) if r["ps_engage"] else 50
        es_avg = {k: sum(e[k] for e in r["emotion_scores"]) / len(r["emotion_scores"])
                  if r["emotion_scores"] else 50 for k in ("hope", "motivation", "confidence")}
        routine = _clamp(100 - r["missed_routine"] * 25)
        goal = (r["completed"] / r["objective_set"] * 100) if r["objective_set"] else 50
        freq = r["turns"] / max_day_turns * 100
        aware = _clamp(40 + r["open_up"] * 15 + min(30, r["facts_added"] * 4))
        reflect = _clamp(r["reflect"] / n * 300)
        changes = _clamp(r["trait_changes"] / n * 200)
        timeline.append({
            "day": d, "turns": r["turns"],
            "stress": _clamp(100 - ps_stress), "mood": ps_mood,
            "routine_adherence": routine, "goal_completion": goal,
            "conversation_frequency": freq, "self_awareness": aware,
            "reflection_quality": reflect, "behavior_changes": changes,
            "confidence": _clamp(es_avg["confidence"] * 0.6 + engage * 0.4),
            "hope": es_avg["hope"], "motivation": es_avg["motivation"],
        })
    return uid, version, timeline, rec


def _window_delta(timeline, mode):
    """mode: '30d' -> first 10 vs last 10 days (or halves); '90d' -> full span."""
    n = len(timeline)
    if n < 4:
        return None
    if mode == "30d":
        k = min(10, n // 3)
        k = max(2, k)
        a, b = timeline[:k], timeline[-k:]
    else:
        k = max(2, n // 3)
        a, b = timeline[:k], timeline[-k:]
    def mean(rows, key):
        return sum(r[key] for r in rows) / len(rows)
    return {key: round(mean(b, key) - mean(a, key), 1) for key in OUTCOME_KEYS}


def _overall(day):
    return round(sum(day[k] for k in OUTCOME_KEYS) / len(OUTCOME_KEYS), 1)


def user_outcome(uid):
    """uid: sim:{sim_id} | live:{user_id}"""
    if uid.startswith("sim:"):
        sim_id = uid.split(":", 1)[1]
        for batch, version in (("sim_main_520", "v1"), ("sim_cmp_100", "v2")):
            f = DATA / "simulations" / batch / f"{sim_id}.json"
            rec = _read(f)
            if rec is None and sim_id:
                for p in (DATA / "simulations" / batch).glob("*.json"):
                    r = _read(p)
                    if r and r.get("sim_id") == sim_id:
                        rec, f = r, p
                        break
            if rec and rec.get("turns"):
                break
        else:
            return None
        uid_, version, timeline, rec = _sim_user(rec)
        if timeline is None:
            return None
        meta = {
            "user_id": sim_id, "kind": "sim", "version": version,
            "persona": rec.get("persona_label") or rec.get("persona_id"),
            "seed": rec.get("seed"),
            "span_days": max((t["day"] for t in timeline), default=0) + 1,
            "turns": len(rec.get("turns", [])),
            "window": "days" if len(timeline) >= 7 else "buckets",
        }
    else:
        user_id = uid.split(":", 1)[1]
        rec = _read(DATA / "sessions" / f"{user_id}_session.json")
        if not rec or not rec.get("turns"):
            return None
        timeline = _live_user(user_id, rec)
        if not timeline:
            return None
        meta = {"user_id": user_id, "kind": "live", "version": "live",
                "persona": "live user", "seed": None,
                "span_days": len(timeline), "turns": len(rec.get("turns", [])),
                "window": "days"}

    start = _overall(timeline[0])
    end = _overall(timeline[-1])
    p30 = _window_delta(timeline, "30d")
    p90 = _window_delta(timeline, "90d")

    eff = _effectiveness(timeline, rec if meta["kind"] == "sim" else None)
    return {
        "meta": meta,
        "timeline": timeline,
        "overall_start": start, "overall_end": end,
        "overall_delta": round(end - start, 1),
        "progress_30d": p30, "progress_90d": p90,
        "progress_30d_overall": round(sum(p30.values()) / len(p30), 1) if p30 else None,
        "progress_90d_overall": round(sum(p90.values()) / len(p90), 1) if p90 else None,
        "effectiveness": eff,
        "roi": rank_roi([eff]),
    }


def _live_user(user_id, rec):
    """Best-effort timeline from a live session file (one row per active day)."""
    by_day = defaultdict(lambda: {"turns": 0, "scores": [], "risk": 0, "reflect": 0})
    for t in rec.get("turns", []):
        ts = t.get("timestamp") or ""
        try:
            d = datetime.fromisoformat(ts[:10]).date()
        except ValueError:
            continue
        row = by_day[d]
        row["turns"] += 1
        es = t.get("emotion_summary") or {}
        row["scores"].append(_emotion_scores(es.get("primary")))
        if es.get("risk"):
            row["risk"] += 1
        if (t.get("state") or "").startswith(("reflection", "insight")):
            row["reflect"] += 1
    if not by_day:
        return None
    days = sorted(by_day)
    max_n = max(r["turns"] for r in by_day.values())
    out = []
    for d in days:
        r = by_day[d]
        n = max(1, len(r["scores"]))
        agg = {k: sum(s[k] for s in r["scores"]) / n for k in ("hope", "motivation", "confidence", "stress")}
        out.append({
            "day": d.isoformat(), "turns": r["turns"],
            "stress": agg["stress"], "mood": 50.0,
            "routine_adherence": 50.0, "goal_completion": 50.0,
            "conversation_frequency": r["turns"] / max_n * 100,
            "self_awareness": 50.0, "reflection_quality": _clamp(r["reflect"] / n * 300),
            "behavior_changes": 50.0, "confidence": agg["confidence"],
            "hope": agg["hope"], "motivation": agg["motivation"],
        })
    return out


# ─── Intervention effectiveness + ROI learning ────────────────────────────

def _effectiveness(timeline, rec):
    """For each coaching method used by this user, outcome delta ~3 days after use."""
    if not rec:
        return []
    by_day = {t["day"]: t for t in timeline}
    uses = defaultdict(lambda: {"type": "", "before": [], "after": [], "uses": 0})
    _NOISE_OPTIONS = {"something else", "let me explain", "i'll try", "okay", "ok"}
    for t in rec.get("turns", []):
        d = t.get("day_offset", 0)
        obj = t.get("objective")
        state = t.get("state")
        inter = ((t.get("engine_outputs") or {}).get("interventions") or [])
        inter_titles = [(i.get("title") or i.get("intervention") or "") for i in inter]
        options = [(o or "") for o in (t.get("assistant_options") or [])]
        if state == "routine_planning":
            inter_titles += [o for o in options
                             if o.lower() not in _NOISE_OPTIONS and len(o.split()) <= 4]
        methods = [("objective", obj)] + [("state", state)] + \
                  [("intervention", x) for x in inter_titles if x]
        for mtype, mname in methods:
            if not mname:
                continue
            key = f"{mtype}:{mname}"
            uses[key]["type"] = mtype
            uses[key]["uses"] += 1
            before = by_day.get(d - 2) or by_day.get(d - 1) or timeline[0]
            after = by_day.get(d + 2) or by_day.get(d + 1) or timeline[-1]
            uses[key]["before"].append(_overall(before))
            uses[key]["after"].append(_overall(after))
    rows = []
    for key, u in uses.items():
        if not u["after"]:
            continue
        before = sum(u["before"]) / len(u["before"])
        after = sum(u["after"]) / len(u["after"])
        rows.append({
            "method": key.split(":", 1)[1], "type": u["type"],
            "before": round(before, 1), "after": round(after, 1),
            "improvement": round(after - before, 1), "uses": u["uses"],
        })
    return rows


def rank_roi(eff_lists):
    """ROI per method across users: mean improvement x exposure share."""
    agg = defaultdict(lambda: {"improvements": [], "users": set()})
    for eff in eff_lists:
        for r in eff:
            key = f"{r['type']}:{r['method']}"
            agg[key]["improvements"].append(r["improvement"])
    rows = []
    for key, a in agg.items():
        mean_imp = sum(a["improvements"]) / len(a["improvements"])
        rows.append({
            "method": key.split(":", 1)[1], "type": key.split(":", 1)[0],
            "roi": round(mean_imp, 1),
            "mean_improvement": round(mean_imp, 1), "samples": len(a["improvements"]),
        })
    rows.sort(key=lambda r: -r["roi"])
    return rows


def aggregate(version="all", limit=None):
    users = list_users(version)
    if limit and limit > 0:
        users = users[:limit]
    p30s, p90s = [], []
    eff_lists = []
    per_metric = {k: [] for k in OUTCOME_KEYS}
    for u in users:
        d = user_outcome(u["id"])
        if not d:
            continue
        if d["progress_30d"]:
            p30s.append(d["progress_30d_overall"])
            for k in OUTCOME_KEYS:
                per_metric[k].append(d["progress_30d"][k])
        if d["progress_90d"]:
            p90s.append(d["progress_90d_overall"])
        if d["effectiveness"]:
            eff_lists.append(d["effectiveness"])
    roi = rank_roi(eff_lists)
    n30 = len(p30s)
    return {
        "users": len(users),
        "avg_progress_30d": round(sum(p30s) / n30, 1) if n30 else None,
        "avg_progress_90d": round(sum(p90s) / max(1, len(p90s)), 1) if p90s else None,
        "metric_30d": {OUTCOME_LABELS[k]: round(sum(v) / len(v), 1) if v else None
                       for k, v in per_metric.items()},
        "roi_top": roi[:8],
        "roi_bottom": list(reversed(roi[-4:])) if len(roi) >= 4 else [],
    }


def save_learned(version="all", limit=80):
    agg = aggregate(version, limit)
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "version": version, "users_analyzed": agg["users"],
        "avg_progress_30d": agg["avg_progress_30d"],
        "avg_progress_90d": agg["avg_progress_90d"],
        "best_methods": agg["roi_top"],
        "avoid_methods": agg["roi_bottom"],
    }
    f = OUTCOMES_DIR / "learned_methods.json"
    with open(f, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
    return payload


def list_users(version="all"):
    out = []
    for batch, ver in (("sim_main_520", "v1"), ("sim_cmp_100", "v2")):
        if version not in ("all", ver):
            continue
        d = DATA / "simulations" / batch
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.json")):
            if f.name == "manifest.json":
                continue
            rec = _read(f)
            if not rec or not rec.get("turns"):
                continue
            days = {t.get("day_offset", 0) for t in rec.get("turns", [])}
            out.append({
                "id": f"sim:{rec.get('sim_id')}", "kind": "sim", "version": ver,
                "persona": rec.get("persona_label") or rec.get("persona_id"),
                "turns": len(rec["turns"]), "span_days": (max(days) + 1) if days else 0,
            })
    if version in ("all", "live"):
        for f in sorted((DATA / "sessions").glob("*_session.json")):
            rec = _read(f)
            if not rec or not rec.get("turns"):
                continue
            uid = rec.get("user_id") or f.name.replace("_session.json", "")
            out.append({"id": f"live:{uid}", "kind": "live", "version": "live",
                        "persona": "live user", "turns": len(rec["turns"]),
                        "span_days": 0})
    return out


# ─── API ──────────────────────────────────────────────────────────────────

@app.get("/api/users")
def users(version: str = "all"):
    return {"users": list_users(version)}


@app.get("/api/user/{uid:path}")
def user(uid: str):
    d = user_outcome(uid)
    if d is None:
        return JSONResponse({"error": "user not found"}, status_code=404)
    return d


@app.get("/api/aggregate")
def agg(version: str = "all", limit: int = 0):
    return aggregate(version, limit)


@app.get("/api/learn")
def learn(version: str = "all", limit: int = 80):
    return save_learned(version, limit)


@app.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse(INDEX_HTML)


INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>User Outcome Tracking — debug</title>
<style>
  :root { --bg:#0f1420; --panel:#171e2e; --line:#2a3450; --fg:#d7dce8; --dim:#8b93a7;
          --acc:#5aa2ff; --good:#7cd97f; --bad:#ff7d7d; --v1:#5aa2ff; --v2:#c58aff; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--fg); font:14px/1.5 "Segoe UI",system-ui,sans-serif; }
  #layout { display:flex; height:100vh; }
  #side { width:290px; min-width:290px; border-right:1px solid var(--line); overflow:auto; padding:10px; }
  #main { flex:1; overflow:auto; padding:18px 24px; }
  h1 { font-size:15px; margin:6px 8px 12px; color:var(--acc); }
  #filt { width:100%; margin-bottom:6px; }
  select { width:100%; background:var(--panel); border:1px solid var(--line); color:var(--fg); border-radius:6px; padding:5px 8px; font-size:12.5px; }
  .usr { display:block; width:100%; text-align:left; background:var(--panel); border:1px solid var(--line);
         color:var(--fg); border-radius:6px; padding:7px 10px; margin:3px 0; cursor:pointer; font-size:12.5px; }
  .usr:hover, .usr.active { border-color:var(--acc); }
  .usr small { display:block; color:var(--dim); }
  #head { display:flex; align-items:center; gap:14px; flex-wrap:wrap; border-bottom:1px solid var(--line); padding-bottom:12px; }
  #label { font-size:17px; font-weight:600; }
  #cards { display:grid; grid-template-columns:repeat(auto-fill,minmax(170px,1fr)); gap:10px; margin:16px 0; }
  .card { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:10px 12px; }
  .card .name { color:var(--dim); font-size:11.5px; }
  .card .val { font-size:22px; font-weight:700; }
  .up { color:var(--good); } .dn { color:var(--bad); }
  h2 { font-size:15px; margin:22px 0 6px; }
  svg { width:100%; height:240px; background:#10162a; border-radius:8px; }
  table { border-collapse:collapse; width:100%; background:var(--panel); border:1px solid var(--line); border-radius:8px; overflow:hidden; margin:10px 0; }
  th, td { padding:6px 10px; text-align:right; border-bottom:1px solid var(--line); font-size:12.5px; }
  th { background:#1a2236; color:var(--dim); }
  th:first-child, td:first-child { text-align:left; }
  .note { color:var(--dim); font-size:12px; font-style:italic; }
  #learnbtn { margin:8px 0; padding:7px 14px; }
  button { background:var(--panel); border:1px solid var(--line); color:var(--fg); border-radius:6px; padding:6px 12px; cursor:pointer; }
  button:hover { border-color:var(--acc); }
</style>
</head>
<body>
<div id="layout">
  <div id="side">
    <h1>User Outcome Tracking</h1>
    <select id="ver"><option value="all">All versions</option><option value="v1">v1</option><option value="v2">v2</option><option value="live">Live users</option></select>
    <div id="list"><div class="note">loading…</div></div>
  </div>
  <div id="main">
    <div id="head"><div id="label">select a user</div><div id="progress" class="note"></div></div>
    <button id="learnbtn">Refresh learned ROI model (data/outcomes/learned_methods.json)</button>
    <div id="agg"></div>
    <div id="detail"></div>
  </div>
</div>
<script>
let U = [], CUR = null, VER = "all";
const KEYS = ["stress","mood","routine_adherence","goal_completion","conversation_frequency","self_awareness","reflection_quality","behavior_changes","confidence","hope","motivation"];
const LABELS = {stress:"Stress trend",mood:"Mood trend",routine_adherence:"Routine adherence",goal_completion:"Goal completion",conversation_frequency:"Conversation frequency",self_awareness:"Self awareness",reflection_quality:"Reflection quality",behavior_changes:"Behavior changes",confidence:"Confidence",hope:"Hope",motivation:"Motivation"};
async function api(p){ const r = await fetch(p); if(!r.ok) throw new Error(r.status); return r.json(); }
const esc = s => String(s ?? "—").replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
const fmt = v => v === null || v === undefined ? "—" : (Number.isInteger(v) ? v : v.toFixed(1));
const cls = v => v > 0.5 ? "up" : v < -0.5 ? "dn" : "";

async function list(){
  U = (await api("/api/users?version=" + VER)).users;
  const box = document.getElementById("list"); box.innerHTML = "";
  for (const u of U) {
    const b = document.createElement("button"); b.className = "usr";
    b.innerHTML = esc(u.persona) + " · " + esc(u.id.replace("sim:","").replace("live:","")) +
      "<small>" + u.version + " · " + u.turns + " turns · " + u.span_days + " days</small>";
    b.onclick = () => open(u.id);
    if (CUR && u.id === CUR) b.classList.add("active");
    box.appendChild(b);
  }
}

async function open(id){
  CUR = id;
  const d = await api("/api/user/" + encodeURIComponent(id));
  document.getElementById("label").textContent = d.meta.persona + " (" + d.meta.user_id + ")";
  document.getElementById("progress").textContent =
    "span: " + d.meta.span_days + " days · window: " + d.meta.window +
    " · 30d progress: " + fmt(d.progress_30d_overall) + " · 90d progress: " + fmt(d.progress_90d_overall);
  list();
  render(d);
}

function render(d){
  const main = document.getElementById("detail"); main.innerHTML = "";
  const cards = document.createElement("div"); cards.id = "cards";
  const t0 = d.timeline[0], t1 = d.timeline[d.timeline.length - 1];
  for (const k of ["overall"].concat(KEYS)) {
    const v0 = k === "overall" ? d.overall_start : t0[k];
    const v1 = k === "overall" ? d.overall_end : t1[k];
    const dv = v1 - v0;
    cards.innerHTML += `<div class="card"><div class="name">${k === "overall" ? "Overall outcome" : LABELS[k]}</div>
      <div class="val">${fmt(v1)}</div><div class="${cls(dv)}">${dv > 0 ? "+" : ""}${fmt(dv)} vs start (${fmt(v0)})</div></div>`;
  }
  main.appendChild(cards);
  main.innerHTML += `<h2>Overall outcome trend</h2><div id="chart"></div>`;
  chart(d.timeline, "overall");
  main.innerHTML += `<h2>Trend per outcome</h2><select id="met"><option>overall</option>${KEYS.map(k => `<option>${k}</option>`).join("")}</select><div id="chart2"></div>`;
  document.getElementById("met").onchange = e => chart(d.timeline, e.target.value, "chart2");
  chart(d.timeline, "mood", "chart2");
  const mk = (label, p, o) => p ? `<h2>${label} (per metric)</h2><table><tr><th>metric</th><th>delta</th></tr>${KEYS.map(k => `<tr><td>${LABELS[k]}</td><td class="${cls(p[k])}">${p[k] > 0 ? "+" : ""}${fmt(p[k])}</td></tr>`).join("")}</table>` : `<div class="note">${label}: insufficient timeline</div>`;
  main.innerHTML += mk("30-day progress", d.progress_30d, d.progress_30d_overall);
  main.innerHTML += mk("90-day progress", d.progress_90d, d.progress_90d_overall);
  if (d.effectiveness && d.effectiveness.length) {
    main.innerHTML += `<h2>Intervention effectiveness</h2>
      <table><tr><th>method</th><th>type</th><th>before</th><th>after</th><th>improvement</th><th>uses</th></tr>
      ${d.effectiveness.sort((a,b)=>b.improvement-a.improvement).map(r => `<tr><td>${esc(r.method)}</td><td>${r.type}</td><td>${fmt(r.before)}</td><td>${fmt(r.after)}</td><td class="${cls(r.improvement)}">${r.improvement > 0 ? "+" : ""}${fmt(r.improvement)}</td><td>${r.uses}</td></tr>`).join("")}</table>`;
  }
  if (d.roi && d.roi.length) {
    main.innerHTML += `<h2>Highest ROI coaching methods (this user)</h2>
      <table><tr><th>method</th><th>type</th><th>ROI</th><th>samples</th></tr>
      ${d.roi.slice(0,6).map(r => `<tr><td>${esc(r.method)}</td><td>${r.type}</td><td>${fmt(r.roi)}</td><td>${r.samples}</td></tr>`).join("")}</table>`;
  }
}

function chart(tl, key, id = "chart"){
  const box = document.getElementById(id);
  const W = 1160, H = 240, P = {l:46, r:14, t:14, b:30};
  const vals = tl.map(t => key === "overall" ? (Object.keys(KEYS).reduce((s,k)=>s+t[KEYS[k]],0)/KEYS.length) : t[key]);
  const ymax = Math.max(100, ...vals.map(v => Math.ceil(v + 5)));
  const x = i => P.l + (i / Math.max(1, tl.length - 1)) * (W - P.l - P.r);
  const y = v => H - P.b - (v / ymax) * (H - P.t - P.b);
  let out = `<svg viewBox="0 0 ${W} ${H}">`;
  for (let i = 0; i <= 4; i++) {
    const gy = P.t + i / 4 * (H - P.t - P.b);
    out += `<line x1="${P.l}" y1="${gy}" x2="${W-P.r}" y2="${gy}" stroke="#232e4a"/><text x="${P.l-8}" y="${gy+4}" fill="#8b93a7" font-size="11" text-anchor="end">${Math.round(ymax*(1-i/4))}</text>`;
  }
  const pts = vals.map((v,i)=>`${x(i)},${y(v)}`).join(" ");
  out += `<polyline points="${pts}" fill="none" stroke="var(--acc)" stroke-width="2.5"/>`;
  for (let i = 0; i < tl.length; i++)
    out += `<circle cx="${x(i)}" cy="${y(vals[i])}" r="2.5" fill="#10162a" stroke="var(--acc)"/>`;
  for (let i = 0; i < tl.length; i += Math.max(1, Math.round(tl.length / 10)))
    out += `<text x="${x(i)}" y="${H-10}" fill="#8b93a7" font-size="11" text-anchor="middle">${tl[i].day}</text>`;
  box.innerHTML = out + "</svg>";
}

async function showAgg(){
  const a = await api("/api/aggregate?version=" + VER);
  document.getElementById("agg").innerHTML = `
    <div class="note">Across ${a.users} users · avg 30d progress: <b class="${cls(a.avg_progress_30d)}">${fmt(a.avg_progress_30d)}</b> · avg 90d progress: <b class="${cls(a.avg_progress_90d)}">${fmt(a.avg_progress_90d)}</b></div>
    <h2>Learned: highest ROI coaching methods</h2>
    <table><tr><th>method</th><th>type</th><th>ROI (avg improvement)</th><th>samples</th></tr>
    ${a.roi_top.map(r => `<tr><td>${esc(r.method)}</td><td>${r.type}</td><td class="${cls(r.roi)}">${r.roi > 0 ? "+" : ""}${fmt(r.roi)}</td><td>${r.samples}</td></tr>`).join("")}</table>`;
}

document.getElementById("ver").onchange = e => { VER = e.target.value; CUR = null; list(); showAgg(); };
document.getElementById("learnbtn").onclick = async () => {
  const r = await api("/api/learn?version=" + VER);
  alert("learned model saved: " + r.users_analyzed + " users · best: " + (r.best_methods[0] ? r.best_methods[0].method + " (" + r.best_methods[0].roi + ")" : "n/a"));
};
list(); showAgg();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    import uvicorn

    print("User Outcome Tracking (debug) — http://127.0.0.1:8004")
    uvicorn.run(app, host="127.0.0.1", port=8004, log_level="warning")
