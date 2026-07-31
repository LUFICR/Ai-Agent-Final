"""Why Engine — recurring behavioral pattern discovery from historical data.

Deterministic and near-zero latency. Analyzes memory facts, emotion history,
conversation turns, and stored reports to find signal pairs that co-deviate
repeatedly over time (e.g. "Sleep ↓ → Stress ↑" repeated 6 times).

Patterns are ONLY emitted when backed by actual stored observations.
Correlations are never invented; a single shared word or one-off day is never
enough to form a pattern.

Every discovered pattern is stored in TWO versions:
  * machine — the compact representation ("Sleep ↓ → Stress ↑", signals, confidence)
  * human   — the coach explanation ("I've noticed that whenever your sleep drops
              for several days, your stress tends to increase soon afterwards.")
Conversation responses prefer the human version.

Pattern shape:
{
  "pattern": "Sleep ↓ → Stress ↑",          # machine label (backward compatible)
  "machine": {"label": ..., "signals": [...], "confidence": 91},   # machine version
  "human": "I've noticed that whenever your sleep drops ...",      # coach version
  "why_matters": "...",
  "evidence": [...],                                              # stored observations
  "confidence": 91,
  "follow_up": "...",                # suggested follow-up question
  "action": "...",                   # recommended coaching action
  "recommendation": "...",           # same as action (backward compatible)
  "observations": [...], "repeats": 6,
  "first_seen": ..., "last_seen": ...,
  "signals": ["sleep", "stress"]
}

Only patterns with confidence >= 70 are stored as insights.
"""

import re
from itertools import combinations
from .utils.storage import load_json, save_json, now_iso, days_since
from .config import get_data_dir, get_user_session_path, get_report_path

MIN_REPEATS = 2           # co-deviations needed for a pair pattern
MIN_SINGLE_REPEATS = 3    # deviations needed for a single-signal pattern
DEVIATION_LEVEL = 65      # signal level at/above which a day "deviates"
MAX_PATTERNS = 10
INSIGHT_MIN_CONFIDENCE = 70

SIGNAL_META = {
    "sleep":      {"display": "Sleep",         "arrow": "↓", "pillars": ("sleep",)},
    "stress":     {"display": "Stress",        "arrow": "↑", "pillars": ("stress",)},
    "anxiety":    {"display": "Anxiety",       "arrow": "↑", "pillars": ("stress",)},
    "mood":       {"display": "Mood",          "arrow": "↓", "pillars": ("mood",)},
    "energy":     {"display": "Energy",        "arrow": "↓", "pillars": ("exercise", "mood")},
    "motivation": {"display": "Motivation",    "arrow": "↓", "pillars": ("motivation",)},
    "exercise":   {"display": "Exercise",      "arrow": "↓", "pillars": ("exercise",)},
    "connection": {"display": "Isolation",     "arrow": "↑", "pillars": ("relationships",)},
    "work":       {"display": "Work pressure", "arrow": "↑", "pillars": ("work",)},
}

_EMOTION_SIGNALS = {
    "sad": ("mood", 80), "depressed": ("mood", 85), "down": ("mood", 75),
    "unhappy": ("mood", 80), "miserable": ("mood", 90), "low": ("mood", 75),
    "happy": ("mood", 10), "good": ("mood", 20), "great": ("mood", 10),
    "calm": ("mood", 15), "okay": ("mood", 30), "fine": ("mood", 30),
    "anxious": ("anxiety", 75), "nervous": ("anxiety", 70), "worried": ("anxiety", 70),
    "overthinking": ("anxiety", 65),
    "stressed": ("stress", 80),
    "lonely": ("connection", 80), "alone": ("connection", 75),
    "tired": ("energy", 65), "exhausted": ("energy", 85), "drained": ("energy", 80),
}

_RECOMMENDATIONS = {
    frozenset(("sleep", "stress")): "When your sleep dips, stress climbs with it. Protecting a consistent wind-down when you're stressed may break this loop.",
    frozenset(("sleep", "anxiety")): "Restless sleep and anxious thoughts appear together for you. A short pre-bed reflection ritual may quiet the loop.",
    frozenset(("sleep", "mood")): "Poor sleep and low mood tend to arrive together. An earlier, fixed bedtime could lift both.",
    frozenset(("sleep", "energy")): "Low sleep and low energy pair up regularly for you — nudging bedtime earlier may be the highest-leverage move.",
    frozenset(("sleep", "work")): "Sleep suffers when work pressure rises. Shielding your evening from work could help both.",
    frozenset(("stress", "mood")): "Stress and low mood travel together for you. Naming one small stressor you can control this week might help.",
    frozenset(("stress", "anxiety")): "High stress and anxiety co-occur for you. A daily five-minute reset could reduce the spiral.",
    frozenset(("stress", "work")): "Work pressure and stress rise together. One clear boundary at work may ease both.",
    frozenset(("stress", "energy")): "Stress burns your energy. Scheduling real rest after heavy days could change this pattern.",
    frozenset(("mood", "energy")): "Low mood and low energy co-occur — gentle movement often lifts both.",
    frozenset(("mood", "motivation")): "Low mood and low motivation appear together. Small, done-is-good wins may restart momentum.",
    frozenset(("mood", "connection")): "Isolation and low mood show up together — a small daily connection could help.",
    frozenset(("anxiety", "energy")): "Anxious days leave you drained. Protecting rest after anxious stretches matters.",
    frozenset(("motivation", "energy")): "Low motivation and low energy pair up — starting with the easiest task often helps.",
    frozenset(("exercise", "energy")): "Skipping movement and low energy coincide for you. A short daily walk may lift both.",
    frozenset(("exercise", "mood")): "Exercise dips and low mood appear together — ten minutes of movement can help.",
}
_FALLBACK_RECOMMENDATION = ("This pattern has shown up {n} times in your history. "
                            "Noticing what precedes it next time may help you break the loop.")
_SINGLE_RECOMMENDATIONS = {
    "sleep": "Your sleep dips regularly. A consistent bedtime window may be worth protecting.",
    "stress": "Your stress level rises repeatedly. Regular short resets could reduce the buildup.",
    "anxiety": "Anxiety shows up repeatedly for you. A breathing or journaling ritual may ease it.",
    "mood": "Low mood recurs in your history. Keeping a small mood ritual could help you spot triggers.",
    "energy": "Low energy recurs for you. Movement and sleep timing are the levers to test.",
    "motivation": "Motivation dips recur. Shrinking tasks to their smallest first step can help.",
    "exercise": "Exercise drops recur — starting with a tiny routine you keep matters more than intensity.",
    "connection": "Isolation recurs. A small daily reach-out could break the pattern.",
    "work": "Work pressure recurs. Check how much of it is urgent versus important.",
}

# ─── Human (coach) explanations — deterministic, no LLM ───

_UP_VERBS = {
    "sleep": "rises", "stress": "rises", "anxiety": "rises", "mood": "lifts",
    "energy": "rebounds", "motivation": "returns", "exercise": "picks up",
    "connection": "increases", "work": "climbs",
}
_DOWN_VERBS = {
    "sleep": "drops", "stress": "eases", "anxiety": "fades", "mood": "dips",
    "energy": "drops", "motivation": "dips", "exercise": "drops",
    "connection": "lessens", "work": "eases",
}


def _signal_verb(signal):
    return _UP_VERBS[signal] if SIGNAL_META[signal]["arrow"] == "↑" else _DOWN_VERBS[signal]


def _verb_base(verb):
    return verb[:-1] if verb.endswith("s") else verb


def _pair_human(sa, sb, meta_a, meta_b):
    return (f"I've noticed that whenever your {meta_a['display'].lower()} "
            f"{_signal_verb(sa)} for several days, your {meta_b['display'].lower()} "
            f"tends to {_verb_base(_signal_verb(sb))} soon afterwards.")


def _single_human(sig, meta, repeats):
    return (f"I've noticed that your {meta['display'].lower()} {_signal_verb(sig)} "
            f"noticeably every so often — {repeats} times in your history so far.")


_WHY_MATTERS = {
    frozenset(("sleep", "stress")): "Sleep and stress feed each other — when sleep drops, your ability to regulate stress weakens, and rising stress then makes good sleep harder.",
    frozenset(("sleep", "anxiety")): "Sleep is when anxious thoughts usually settle; when sleep is poor, worries have more room to grow and the loop tightens.",
    frozenset(("sleep", "mood")): "Poor sleep and low mood share the same underlying systems — fixing sleep timing often lifts mood too.",
    frozenset(("sleep", "energy")): "Sleep is the main way your body restores energy; when it suffers, everything else runs on empty.",
    frozenset(("sleep", "work")): "Work pressure can crowd out the wind-down time your sleep depends on — the two fight for the same hours.",
    frozenset(("stress", "mood")): "Sustained stress drains mood — catching stress early can stop it pulling your mood down with it.",
    frozenset(("stress", "anxiety")): "Stress and anxiety amplify each other in a cycle; interrupting one weakens the other.",
    frozenset(("stress", "work")): "When work pressure rises, stress follows — the boundary between the two is one of the most controllable levers.",
    frozenset(("stress", "energy")): "Stress burns energy faster than almost anything else; recovery has to be scheduled deliberately.",
    frozenset(("mood", "energy")): "Mood and energy move as one for you — lifting either one typically lifts the other.",
    frozenset(("mood", "motivation")): "Low mood makes every task feel bigger, which drags motivation down with it.",
    frozenset(("mood", "connection")): "Isolation feeds low mood and low mood feeds isolation — a small connection breaks the loop.",
    frozenset(("anxiety", "energy")): "Anxious days are mentally exhausting; the energy cost is real and needs rest to recover.",
    frozenset(("motivation", "energy")): "Low energy makes starting hard, and not starting drains motivation further.",
    frozenset(("exercise", "energy")): "Movement is one of the most reliable ways to restore energy — skipping it compounds.",
    frozenset(("exercise", "mood")): "Exercise lifts mood through several pathways; missing it lets mood dip.",
}
_WHY_FALLBACK = ("When {a} and {b} move together for you, they tend to reinforce each other — "
                 "so a change on either side often carries the other.")
_SINGLE_WHY = {
    "sleep": "Sleep is the foundation everything else builds on — repeated dips are worth treating seriously.",
    "stress": "Sustained stress wears down every other system; catching it early is the highest-leverage habit.",
    "anxiety": "Anxiety loops build on themselves — noticing early signs gives you a chance to interrupt them.",
    "mood": "Repeated low mood is an early-warning signal worth tracking closely.",
    "energy": "Energy drives action; when it drops repeatedly, motivation and mood tend to follow.",
    "motivation": "Motivation follows action, not the other way around — dips can be reversed with tiny steps.",
    "exercise": "Movement is the most reliable mood and energy lever; repeated dips matter.",
    "connection": "Isolation compounds quietly — each episode makes the next easier.",
    "work": "Work pressure accumulates; repeated spikes are a burnout risk worth watching.",
}
_WHY_FALLBACK_SINGLE = ("Repeated {x} swings are an early-warning signal — catching them early "
                        "gives you a chance to act before they build.")

_FOLLOW_UPS = {
    frozenset(("sleep", "stress")): "What usually happens in the days right before your sleep drops — can you name the trigger?",
    frozenset(("sleep", "anxiety")): "When your sleep suffers, is there a specific worry that keeps running through your head at night?",
    frozenset(("sleep", "mood")): "Do you notice the sleep dip coming first, or the low mood — which one starts the cycle?",
    frozenset(("sleep", "energy")): "On the nights before low-energy days, what time are you actually getting to bed?",
    frozenset(("sleep", "work")): "Is work creeping into your evenings on the nights your sleep drops?",
    frozenset(("stress", "mood")): "What tends to be stressing you in the days before your mood dips?",
    frozenset(("stress", "anxiety")): "When stress climbs, what are the first thoughts that show up with it?",
    frozenset(("stress", "work")): "Which part of work usually drives the spike — workload, deadlines, or people?",
    frozenset(("stress", "energy")): "How long does it usually take you to recover after a heavy stretch?",
    frozenset(("mood", "energy")): "Which usually dips first for you — mood or energy?",
    frozenset(("mood", "motivation")): "What makes even the smallest task feel heavy on your lowest days?",
    frozenset(("mood", "connection")): "How long do you usually go without meaningful contact before your mood drops?",
    frozenset(("anxiety", "energy")): "What exhausts you more — the anxious thinking itself, or the things it makes you worry about?",
    frozenset(("motivation", "energy")): "When energy is low, what is the very first small step you skip?",
    frozenset(("exercise", "energy")): "What gets in the way on the days you skip moving?",
    frozenset(("exercise", "mood")): "How do you feel physically on the days you skip movement?",
}
_FOLLOW_UP_FALLBACK = "What tends to be going on around those days — is there a common thread you've noticed?"
_SINGLE_FOLLOW_UPS = {
    "sleep": "What do you notice in the hours before your sleep starts to slip?",
    "stress": "What is usually the first sign that your stress is climbing?",
    "anxiety": "When does the anxious feeling usually start — morning or night?",
    "mood": "What are the first signs that a low day is coming?",
    "energy": "What time of day do you run out of steam?",
    "motivation": "What is the smallest task that feels impossible on a low-motivation day?",
    "exercise": "What typically stops you from moving on those days?",
    "connection": "What stops you from reaching out when you feel isolated?",
    "work": "What is the first sign that work pressure is building?",
}

_BAD_SLEEP = ("bad", "poor", "terrible", "awful", "horrible")
_GOOD_SLEEP = ("great", "good", "amazing", "excellent", "well", "fine")
_GOOD_RELATIONSHIP = ("good", "great", "fine", "strong", "better")
_BAD_RELATIONSHIP = ("bad", "strain", "tense", "arguing", "distant", "struggl")


def _to_float(text):
    m = re.search(r"\d+(?:\.\d+)?", str(text or ""))
    return float(m.group(0)) if m else None


def _sleep_level(hours):
    if hours is None:
        return None
    if hours >= 7.5:
        return 0
    if hours <= 4:
        return 100
    return round((7.5 - hours) / 3.5 * 100)


class WhyEngine:
    def __init__(self, memory):
        self.memory = memory
        self.user_id = memory.user_id
        self.path = get_data_dir("whys") / f"{self.user_id}_whys.json"
        self.store = self._load()

    def _load(self):
        data = load_json(self.path)
        if not data:
            data = {"user_id": self.user_id, "updated_at": None,
                    "total_observations": 0, "patterns": []}
        return data

    def _save(self):
        save_json(self.path, self.store)

    # ─── Public API ───────────────────────────────────────────

    def update(self):
        facts = self.memory.get_all_facts()
        turns = self._load_session_turns()
        report = self._load_report()
        observations = self._build_observations(facts, turns, report)
        patterns = self._detect_patterns(observations)
        patterns = [p for p in patterns if p["confidence"] >= INSIGHT_MIN_CONFIDENCE]
        self.store["patterns"] = patterns
        self.store["updated_at"] = now_iso()
        self.store["total_observations"] = len(observations)
        self._save()
        return patterns

    def get_patterns(self, min_confidence=0):
        patterns = [dict(p) for p in self.store.get("patterns", [])
                    if p.get("confidence", 0) >= min_confidence]
        return sorted(patterns, key=lambda p: p["confidence"], reverse=True)

    def get_top(self, min_confidence=50):
        patterns = self.get_patterns(min_confidence)
        return patterns[0] if patterns else None

    def get_relevant(self, pillar, min_confidence=70):
        for p in self.get_patterns(min_confidence):
            signals = p.get("signals", [])
            if any(pillar in SIGNAL_META[s].get("pillars", ()) for s in signals):
                return p
        return None

    def get_signal_deviations(self, signal, min_level=DEVIATION_LEVEL, max_age_days=30):
        days = []
        for fact in self.memory.get_all_facts():
            cls = self._classify(fact.get("key", ""), fact.get("value", ""))
            if not cls or cls[0] != signal or cls[1] is None or cls[1] < min_level:
                continue
            day = (fact.get("created_at") or fact.get("last_updated") or "")[:10]
            if day:
                try:
                    if days_since(day) <= max_age_days:
                        days.append(day)
                except Exception:
                    continue
        return sorted(set(days))

    # ─── Data sources ─────────────────────────────────────────

    def _load_session_turns(self):
        data = load_json(get_user_session_path(self.user_id))
        turns = data.get("turns", []) if data else []
        return turns[-300:]

    def _load_report(self):
        data = load_json(get_report_path(self.user_id, "daily"))
        return data if data else None

    # ─── Signal extraction ────────────────────────────────────

    def _classify(self, key, value):
        key_l = (key or "").lower()
        value_l = str(value or "").lower()
        if "sleep_hours" in key_l:
            h = _to_float(value_l)
            level = _sleep_level(h)
            return ("sleep", level, f"{h}h") if level is not None else None
        if "sleep_quality" in key_l:
            if any(w in value_l for w in _BAD_SLEEP):
                return ("sleep", 80, value_l)
            if any(w in value_l for w in _GOOD_SLEEP):
                return ("sleep", 15, value_l)
            return None
        if "work_stress" in key_l:
            if any(w in value_l for w in ("high", "elevated")) or any(
                    w in value_l for w in ("stressful", "hectic", "overwhelming", "busy")):
                return ("work", 80, value_l)
            if any(w in value_l for w in ("low", "fine", "good")):
                return ("work", 20, value_l)
            return ("work", 60, value_l)
        if "stress_level" in key_l:
            m = _to_float(value_l)
            if "elevated" in value_l:
                return ("stress", 70, value_l)
            if "high" in value_l:
                return ("stress", min(100, int(m) if m else 80), value_l)
            if "low" in value_l:
                return ("stress", max(10, int(m) if m else 20), value_l)
            return ("stress", int(m) if m else 60, value_l)
        if "motivation" in key_l:
            if any(w in value_l for w in ("low", "none", "zero", "no drive", "0")):
                return ("motivation", 75, value_l)
            if any(w in value_l for w in ("high", "good", "better", "improving")):
                return ("motivation", 20, value_l)
            if value_l == "mentioned":
                return ("motivation", 50, value_l)
            return None
        if "exercise" in key_l:
            m = _to_float(value_l)
            if m is None:
                return None
            n = int(m)
            return ("exercise", 70 if n == 0 else (45 if n < 3 else 10), f"{n}x/week")
        if "relationship" in key_l:
            if any(w in value_l for w in _BAD_RELATIONSHIP):
                return ("connection", 70, value_l)
            if any(w in value_l for w in _GOOD_RELATIONSHIP):
                return ("connection", 15, value_l)
            return None
        if key_l == "mood_state":
            mapped = _EMOTION_SIGNALS.get(value_l)
            return (mapped[0], mapped[1], value_l) if mapped else None
        if key_l.startswith("emotion_"):
            mapped = _EMOTION_SIGNALS.get(key_l.split("_", 1)[1])
            return (mapped[0], mapped[1], value_l) if mapped else None
        return None

    def _build_observations(self, facts, turns, report):
        obs = {}
        seen_facts = set()

        def add(signal, level, day, detail, evidence):
            if signal is None or level is None or not day:
                return
            entry = obs.setdefault((signal, day), {"level": 0, "facts": [], "detail": {}})
            if level > entry["level"]:
                entry["level"] = level
                entry["detail"][signal] = detail
            key = (evidence.get("key"), evidence.get("at"))
            if key not in seen_facts:
                seen_facts.add(key)
                entry["facts"].append(evidence)

        for fact in facts:
            cls = self._classify(fact.get("key", ""), fact.get("value", ""))
            if not cls:
                continue
            signal, level, detail = cls
            day = (fact.get("created_at") or fact.get("last_updated") or "")[:10]
            add(signal, level, day, detail, {
                "key": fact.get("key"), "value": fact.get("value"),
                "confidence": fact.get("confidence", 60), "at": day, "source": "memory"})

        for turn in turns:
            day = (turn.get("timestamp") or "")[:10]
            if not day:
                continue
            emo = ((turn.get("emotion_summary") or {}).get("primary") or "").lower()
            mapped = _EMOTION_SIGNALS.get(emo)
            if mapped:
                add(mapped[0], mapped[1], day, emo, {
                    "key": "conversation", "value": emo,
                    "confidence": 70, "at": day, "source": "session"})

        if report:
            day = (report.get("generated_at") or "")[:10]
            for t in report.get("trends", []):
                metric = t.get("metric", "")
                val = _to_float(t.get("value", ""))
                signal = {"stress_avg": "stress", "sleep_avg": "sleep",
                          "mood_avg": "mood", "energy_avg": "energy",
                          "motivation_avg": "motivation",
                          "exercise_days": "exercise"}.get(metric)
                if signal is None or val is None:
                    continue
                if metric == "sleep_avg":
                    level = _sleep_level(val)
                elif metric == "exercise_days":
                    level = 70 if val <= 0 else 10
                elif metric == "stress_avg":
                    level = val
                else:
                    level = 100 - val
                add(signal, level, day, f"{metric}:{val}", {
                    "key": metric, "value": f"{val:.0f}",
                    "confidence": 60, "at": day, "source": "report"})

        return obs

    # ─── Pattern detection ────────────────────────────────────

    def _detect_patterns(self, obs):
        by_signal = {}
        for (signal, day), entry in obs.items():
            by_signal.setdefault(signal, {})[day] = entry

        patterns = []
        for sa, sb in combinations(sorted(by_signal), 2):
            days_a = {d for d, e in by_signal[sa].items() if e["level"] >= DEVIATION_LEVEL}
            days_b = {d for d, e in by_signal[sb].items() if e["level"] >= DEVIATION_LEVEL}
            common = sorted(days_a & days_b)
            if len(common) >= MIN_REPEATS:
                patterns.append(self._make_pair_pattern(sa, sb, common, by_signal))

        for sig in by_signal:
            days = sorted(d for d, e in by_signal[sig].items() if e["level"] >= DEVIATION_LEVEL)
            if len(days) >= MIN_SINGLE_REPEATS:
                patterns.append(self._make_single_pattern(sig, days, by_signal))

        patterns.sort(key=lambda p: p["confidence"], reverse=True)
        return patterns[:MAX_PATTERNS]

    def _make_pair_pattern(self, sa, sb, days, by_signal):
        meta_a, meta_b = SIGNAL_META[sa], SIGNAL_META[sb]
        observations, evidence = [], []
        for d in days:
            entry = {"date": d}
            for sig in (sa, sb):
                e = by_signal[sig][d]
                entry[sig] = e["detail"].get(sig, "")
                for f in e["facts"]:
                    if f not in evidence:
                        evidence.append(f)
            observations.append(entry)
        confidence = self._confidence(len(days), evidence, days[-1])
        label = f"{meta_a['display']} {meta_a['arrow']} → {meta_b['display']} {meta_b['arrow']}"
        key = frozenset((sa, sb))
        action = _RECOMMENDATIONS.get(key, _FALLBACK_RECOMMENDATION.format(n=len(days)))
        return {
            "pattern": label,
            "machine": {"label": label, "signals": [sa, sb], "confidence": confidence},
            "human": _pair_human(sa, sb, meta_a, meta_b),
            "why_matters": _WHY_MATTERS.get(
                key, _WHY_FALLBACK.format(a=meta_a["display"].lower(), b=meta_b["display"].lower())),
            "follow_up": _FOLLOW_UPS.get(key, _FOLLOW_UP_FALLBACK),
            "action": action,
            "recommendation": action,
            "confidence": confidence,
            "observations": observations,
            "evidence": evidence[:20],
            "repeats": len(days),
            "first_seen": days[0],
            "last_seen": days[-1],
            "signals": [sa, sb],
        }

    def _make_single_pattern(self, sig, days, by_signal):
        meta = SIGNAL_META[sig]
        observations, evidence = [], []
        for d in days:
            entry = by_signal[sig][d]
            observations.append({"date": d, sig: entry["detail"].get(sig, "")})
            for f in entry["facts"]:
                if f not in evidence:
                    evidence.append(f)
        confidence = self._confidence(len(days), evidence, days[-1])
        label = f"{meta['display']} {meta['arrow']} recurring"
        action = _SINGLE_RECOMMENDATIONS.get(sig)
        return {
            "pattern": label,
            "machine": {"label": label, "signals": [sig], "confidence": confidence},
            "human": _single_human(sig, meta, len(days)),
            "why_matters": _SINGLE_WHY.get(
                sig, _WHY_FALLBACK_SINGLE.format(x=meta["display"].lower())),
            "follow_up": _SINGLE_FOLLOW_UPS.get(sig, _FOLLOW_UP_FALLBACK),
            "action": action,
            "recommendation": action,
            "confidence": confidence,
            "observations": observations,
            "evidence": evidence[:20],
            "repeats": len(days),
            "first_seen": days[0],
            "last_seen": days[-1],
            "signals": [sig],
        }

    def _confidence(self, repeats, evidence, last_seen):
        conf = 45 + repeats * 7
        if evidence:
            avg = sum(f.get("confidence", 60) for f in evidence) / len(evidence)
            conf += min(6, (avg - 50) / 5)
        try:
            if days_since(last_seen) <= 7:
                conf += 3
        except Exception:
            pass
        return min(97, round(conf))
