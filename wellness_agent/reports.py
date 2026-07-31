"""Report Generator — WHY-first, engine-driven reports.

Replaces the old metric-summary reports (hardcoded Mood/Stress numbers with
no explanation). Every report is assembled from real engine state and every
item explains WHY it matters, not just WHAT it says.

Data sources (all deterministic, no LLM calls):
  * Behavior Engine   → behavior changes, confidence trends, difficult habits
  * Hypothesis Engine → leading hypotheses (questions for next week)
  * Why Engine        → recurring patterns, follow-up questions
  * Objective history → most successful interventions
  * Memory beliefs    → difficult habits, confidence trends

The `trends` list is kept as a machine-readable feed of fact-derived metric
values (real data only, never hardcoded) for the Why Engine's pattern
detector; `state_snapshot` enables confidence deltas on the next report.
"""

import re
from datetime import datetime

from .utils.storage import load_json, save_json, now_iso, days_since
from .config import get_report_path

TREND_DELTA = 5

# Word → 0-100 score maps for fact-derived metrics (no hardcoded values)
_WORD_SCORES = {
    "happy": 85, "great": 85, "good": 80, "well": 80, "okay": 60, "fine": 60,
    "calm": 55, "meh": 40, "tired": 40, "sad": 25, "down": 25, "low": 25,
    "depressed": 15, "exhausted": 20, "anxious": 35, "stressed": 30,
    "worried": 35, "neutral": 50,
}
_STRESS_WORD_SCORES = {
    "high": 80, "elevated": 65, "stressful": 70, "hectic": 65,
    "overwhelming": 85, "busy": 55, "medium": 50, "moderate": 50,
    "low": 20, "fine": 25, "good": 20, "calm": 15, "relaxed": 15,
}
_HABIT_LABELS = {
    "poor_sleep_reduced_energy": "Sleep",
    "limited_movement": "Exercise / movement",
    "low_motivation": "Motivation",
    "anxiety_interfering": "Anxiety management",
    "relationships_under_strain": "Relationships",
    "high_recurring_stress": "Stress management",
    "recurring_low_mood": "Mood care",
}
_BELIEF_QUESTIONS = {
    "poor_sleep_reduced_energy": "Is sleep still the biggest drain on your energy, or has it changed?",
    "limited_movement": "Have you managed any movement this week?",
    "low_motivation": "Is motivation still low, or has it shifted at all?",
    "anxiety_interfering": "Is anxiety still interfering with your days?",
    "relationships_under_strain": "How are your relationships feeling right now?",
    "high_recurring_stress": "Has your stress stayed high, or has it come down?",
    "recurring_low_mood": "Has your mood lifted at all this week?",
}
_OBJECTIVE_HINTS = {
    "build_rapport": "Good for warming up new topics.",
    "learn_sleep_habits": "Sleep is a known focus for you.",
    "understand_work_stress": "Work stress keeps resurfacing for you.",
    "explore_emotional_trigger": "Fits your reflective style.",
    "explore_wellness_area": "Useful when an area needs mapping out.",
    "confirm_hypothesis": "Good when a hypothesis needs checking.",
    "close_conversation": "A clean exit helps end sessions well.",
}
_STRUGGLE_AMPLIFIERS = {
    "loses_momentum_after_failure": "made harder because you lose momentum after a slip",
    "perfectionist": "and perfectionism can turn one bad day into a reset",
}


def _num(value):
    m = re.search(r"\d+(?:\.\d+)?", str(value or ""))
    return float(m.group(0)) if m else None


def _word_score(value):
    text = str(value or "").lower()
    best = None
    for word, score in _WORD_SCORES.items():
        if word in text and (best is None or score < best[1]):
            best = (word, score)
    return best


def _stress_score(value):
    text = str(value or "").lower()
    n = _num(value)
    if n is not None:
        return max(0.0, min(100.0, n))
    best = None
    for word, score in _STRESS_WORD_SCORES.items():
        if word in text and (best is None or score < best[1]):
            best = (word, score)
    return best[1] if best else None


class ReportGenerator:
    def __init__(self, memory_system=None, behavior_engine=None,
                 hypothesis_engine=None, why_engine=None,
                 self_evaluator=None, belief_engine=None):
        self.memory = memory_system
        self.behavior_engine = behavior_engine
        self.hypothesis_engine = hypothesis_engine
        self.why_engine = why_engine
        self.self_evaluator = self_evaluator
        self.belief_engine = belief_engine

    # ─── Public API ───────────────────────────────────────────

    def generate(self, period="daily", metrics=None, prior_period_metrics=None, achievements=None):
        achievements = achievements or []
        prior_snapshot = self._load_previous_snapshot(period)

        if metrics is None:
            metrics = self._derive_metrics_from_facts()

        trends = self._compute_trends(metrics, prior_snapshot.get("metrics") or {})
        sections = self._build_sections(prior_snapshot, achievements)
        summary = self._build_summary(sections, achievements, metrics)

        report = {
            "period": period,
            "generated_at": now_iso(),
            "summary": summary,
            "sections": sections,
            "trends": trends,
            "state_snapshot": self._build_snapshot(metrics),
        }

        if self.memory:
            path = get_report_path(self.memory.user_id, period)
            save_json(path, report)

        return report

    def generate_weekly(self):
        return self.generate("weekly")

    def generate_monthly(self):
        return self.generate("monthly")

    def get_report(self, period="daily"):
        if not self.memory:
            return None
        data = load_json(get_report_path(self.memory.user_id, period))
        return data if data else None

    # ─── Fact-derived metrics (real data only, never hardcoded) ───

    def _derive_metrics_from_facts(self):
        facts = self.memory.get_all_facts() if self.memory else []
        if not facts:
            return {}

        def latest(pred):
            hits = [f for f in facts if pred(f.get("key", ""))]
            if not hits:
                return None
            return sorted(hits, key=lambda f: f.get("last_updated") or "", reverse=True)[0]

        metrics = {}

        f = latest(lambda k: "sleep_hours" in k)
        if f and _num(f.get("value")) is not None:
            metrics["sleep_avg"] = _num(f["value"])

        f = latest(lambda k: "stress_level" in k or "work_stress" in k
                   or "current_stress_level" in k)
        if f and _stress_score(f.get("value")) is not None:
            metrics["stress_avg"] = _stress_score(f["value"])

        f = latest(lambda k: "mood_state" in k or "current_mood" in k)
        if f and _word_score(f.get("value")) is not None:
            metrics["mood_avg"] = _word_score(f["value"])[1]

        f = latest(lambda k: "energy" in k and "sleep" not in k)
        if f and _word_score(f.get("value")) is not None:
            metrics["energy_avg"] = _word_score(f["value"])[1]

        f = latest(lambda k: "motivation" in k)
        if f and _word_score(f.get("value")) is not None:
            metrics["motivation_avg"] = _word_score(f["value"])[1]

        f = latest(lambda k: "exercise" in k)
        if f and _num(f.get("value")) is not None:
            metrics["exercise_days"] = _num(f["value"])

        return {k: round(v, 1) for k, v in metrics.items()}

    def _compute_trends(self, current, prior):
        trends = []
        for metric, curr_val in current.items():
            if curr_val is None:
                continue
            prior_val = prior.get(metric)
            direction = "flat"
            change = None
            if prior_val is not None:
                diff = curr_val - prior_val
                change = f"{'+' if diff > 0 else ''}{diff:.1f}"
                if diff > TREND_DELTA:
                    direction = "up"
                elif diff < -TREND_DELTA:
                    direction = "down"
            trends.append({
                "metric": metric,
                "direction": direction,
                "value": f"{curr_val:g}",
                "change": change or "N/A",
            })
        return trends

    # ─── Sections (WHY-first) ─────────────────────────────────

    def _build_sections(self, prior_snapshot, achievements):
        return {
            "behavior_changes": self._behavior_changes(prior_snapshot),
            "recurring_patterns": self._recurring_patterns(),
            "successful_interventions": self._successful_interventions(),
            "difficult_habits": self._difficult_habits(),
            "confidence_trends": self._confidence_trends(prior_snapshot),
            "questions_for_next_week": self._questions_for_next_week(),
        }

    def _behavior_changes(self, prior_snapshot):
        out = []
        if not self.behavior_engine:
            return out
        prior = prior_snapshot.get("trait_confidence") or {}
        traits = self.behavior_engine.get_traits()

        ranked = []
        for trait, entry in traits.items():
            label = entry.get("label") or trait
            conf = entry.get("confidence", 0)
            evidence = entry.get("evidence") or []
            last_confirmed = entry.get("last_confirmed") or entry.get("last_updated")
            prev_conf = prior.get(trait)
            trend = entry.get("trend", "stable")

            if prev_conf is None:
                if trend == "up":
                    ranked.append({
                        "title": label,
                        "what": f"{label} is emerging ({conf}% confidence).",
                        "why": (f"New trait — {len(evidence)} confirming moments so far, "
                                f"most recently \"{self._snippet(evidence)}\"."),
                        "direction": "new",
                        "confidence": conf,
                        "evidence_count": len(evidence),
                        "_delta": 100,
                    })
                continue

            if conf - prev_conf > TREND_DELTA:
                why = (f"Reinforced this period ({prev_conf}% → {conf}%) — "
                       f"{len(evidence)} supporting moments, last: \"{self._snippet(evidence)}\".")
                direction = "up"
            elif prev_conf - conf > TREND_DELTA:
                if evidence and str(evidence[-1].get("snippet", "")).startswith("counter:"):
                    why = (f"Weakened by mismatched responses this period "
                           f"({prev_conf}% → {conf}%) — \"{self._snippet(evidence)}\".")
                else:
                    days = self._days_since(last_confirmed)
                    why = (f"Faded without recent confirmation ({prev_conf}% → {conf}%) — "
                           f"last confirmed {days} days ago.")
                direction = "down"
            else:
                continue

            status = "active" if conf >= 60 else "uncertain"
            ranked.append({
                "title": label,
                "what": f"{label} shifted {direction} to {conf}% ({status}).",
                "why": why,
                "direction": direction,
                "confidence": conf,
                "evidence_count": len(evidence),
                "_delta": abs(conf - prev_conf),
            })

        return [dict(i, _delta=0) for i in sorted(ranked, key=lambda i: i["_delta"], reverse=True)][:5]

    def _recurring_patterns(self):
        if not self.why_engine:
            return []
        patterns = self.why_engine.get_patterns(min_confidence=60)[:3]
        out = []
        for p in patterns:
            why = p.get("why_matters") or ""
            recency = "still active this week" if self._within_days(p.get("last_seen"), 7) \
                else f"last seen {p.get('last_seen')}"
            out.append({
                "title": p.get("human") or p.get("pattern"),
                "what": p.get("human") or p.get("pattern"),
                "why": f"{why} It repeated {p.get('repeats')}× since {p.get('first_seen')} "
                       f"({recency}) — suggested action: {p.get('action', '')}",
                "confidence": p.get("confidence"),
                "repeats": p.get("repeats"),
                "first_seen": p.get("first_seen"),
                "last_seen": p.get("last_seen"),
                "action": p.get("action"),
            })
        if not out:
            out.append({
                "title": "No recurring patterns yet",
                "what": "No recurring pattern has crossed the confidence threshold yet.",
                "why": ("Patterns only form when the same signal deviation recurs on "
                        "separate days — keep tracking and the why behind them will sharpen."),
                "confidence": 0,
            })
        return out

    def _successful_interventions(self):
        if not self.self_evaluator:
            return []
        track = self.self_evaluator.get_track() or {}
        attempts_total = sum(e.get("attempts", 0) for e in track.values())

        ranked = []
        for objective, entry in track.items():
            attempts = entry.get("attempts", 0)
            successes = entry.get("successes", 0)
            if attempts < 1 or successes < 1:
                continue
            rate = successes / attempts
            if rate < 0.5:
                continue
            display = objective.replace("_", " ").title()
            hint = _OBJECTIVE_HINTS.get(objective, "")
            last_val = entry.get("last")
            if last_val is True:
                last = "the most recent attempt"
            elif last_val is False:
                last = "the last attempt (not completed)"
            else:
                last = str(last_val).split("T")[0] or "the last attempt"
            ranked.append({
                "title": display,
                "what": f"{display} — completed {successes} of {attempts} attempts.",
                "why": (f"{round(rate * 100)}% success rate with average confidence "
                        f"{entry.get('avg_confidence', 0)}%; last attempt {last}. {hint}"),
                "successes": successes,
                "attempts": attempts,
                "success_rate": f"{round(rate * 100)}%",
            })

        ranked.sort(key=lambda i: (i["successes"], i["success_rate"]), reverse=True)
        out = ranked[:3]
        if not out:
            out.append({
                "title": "No completed objectives yet",
                "what": f"No objective has been completed successfully yet ({attempts_total} attempts tracked).",
                "why": ("Success rates need completed objectives — confidence builds "
                        "as more attempts are evaluated."),
                "successes": 0,
                "attempts": attempts_total,
                "success_rate": "0%",
            })
        return out

    def _difficult_habits(self):
        out = []
        if not self.belief_engine:
            return out
        beliefs = self.belief_engine.get_beliefs(min_confidence=40)
        amplifiers = self.behavior_engine.active_traits() if self.behavior_engine else []

        for b in beliefs:
            rule_id = b.get("id", "")
            label = _HABIT_LABELS.get(rule_id)
            if not label:
                continue
            supporting = b.get("supporting_facts") or []
            contradicting = b.get("contradicting_facts") or []
            why = f"Grounded in {len(supporting)} observations"
            if supporting:
                f0 = supporting[0]
                why += f" (e.g. {f0.get('key')}: {f0.get('value')})"
            if contradicting:
                why += f"; though {len(contradicting)} observations push the other way"
            extra = [amp for amp, text in _STRUGGLE_AMPLIFIERS.items() if amp in amplifiers]
            if extra:
                why += f" — {_STRUGGLE_AMPLIFIERS[extra[0]]}"
            why += "."
            out.append({
                "title": label,
                "what": b.get("belief"),
                "why": why,
                "confidence": b.get("confidence"),
                "belief_id": rule_id,
                "evidence_count": b.get("evidence_count"),
            })

        if self.memory:
            facts = self.memory.get_all_facts()
            for fact in facts:
                key = fact.get("key", "")
                if "sleep_hours" in key and _num(fact.get("value")) is not None \
                        and _num(fact["value"]) < 6:
                    if not any(i.get("title") == "Sleep" for i in out):
                        out.append({
                            "title": "Sleep",
                            "what": f"Sleep has been short ({fact['value']}).",
                            "why": (f"Observed on {fact.get('created_at', '')[:10]} — "
                                    f"short sleep correlates with lower energy and mood."),
                            "confidence": fact.get("confidence", 50),
                            "belief_id": None,
                            "evidence_count": 1,
                        })
                elif "exercise" in key and _num(fact.get("value")) is not None \
                        and _num(fact["value"]) <= 1:
                    if not any(i.get("title") == "Exercise / movement" for i in out):
                        out.append({
                            "title": "Exercise / movement",
                            "what": f"Movement has been minimal ({fact['value']}).",
                            "why": (f"Observed on {fact.get('created_at', '')[:10]} — "
                                    f"low movement tends to keep energy and mood down."),
                            "confidence": fact.get("confidence", 50),
                            "belief_id": None,
                            "evidence_count": 1,
                        })

        return sorted(out, key=lambda i: i.get("confidence", 0), reverse=True)[:4]

    def _confidence_trends(self, prior_snapshot):
        out = []
        if not self.behavior_engine:
            return out

        prior_traits = prior_snapshot.get("trait_confidence") or {}
        traits = self.behavior_engine.get_traits()
        for trait, entry in traits.items():
            conf = entry.get("confidence", 0)
            prev = prior_traits.get(trait)
            if prev is None:
                continue
            if abs(conf - prev) <= TREND_DELTA:
                continue
            evidence = entry.get("evidence") or []
            if conf > prev:
                why = (f"Supported by new evidence — {len(evidence)} observations now "
                       f"(was {len(evidence) - 1} at last report).")
            elif evidence and str(evidence[-1].get("snippet", "")).startswith("counter:"):
                why = f"Contradicted this period — \"{self._snippet(evidence)}\""
            else:
                why = f"Decayed without recent confirmation (last confirmed {self._days_since(entry.get('last_confirmed'))} days ago)."
            out.append({
                "title": f"Trait: {entry.get('label') or trait}",
                "what": f"{prev}% → {conf}%",
                "why": why,
                "direction": "up" if conf > prev else "down",
                "from": prev,
                "to": conf,
            })

        if self.belief_engine:
            prior_beliefs = prior_snapshot.get("belief_confidence") or {}
            for b in self.belief_engine.get_beliefs():
                rule_id = b.get("id", "")
                prev = prior_beliefs.get(rule_id)
                if prev is None:
                    continue
                conf = b.get("confidence", 0)
                if abs(conf - prev) <= TREND_DELTA:
                    continue
                supporting = len(b.get("supporting_facts") or [])
                why = (f"Supporting evidence changed — {supporting} observations now "
                       f"support it; belief {'strengthened' if conf > prev else 'weakened'} "
                       f"from {prev}% to {conf}%.")
                out.append({
                    "title": f"Belief: {b.get('belief', '')[:60]}",
                    "what": f"{prev}% → {conf}%",
                    "why": why,
                    "direction": "up" if conf > prev else "down",
                    "from": prev,
                    "to": conf,
                })

        if self.why_engine:
            prior_patterns = prior_snapshot.get("pattern_confidence") or {}
            for p in self.why_engine.get_patterns(min_confidence=60)[:3]:
                key = "|".join(sorted(p.get("signals") or []))
                prev = prior_patterns.get(key)
                if prev is None:
                    continue
                conf = p.get("confidence", 0)
                if abs(conf - prev) <= TREND_DELTA:
                    continue
                out.append({
                    "title": f"Pattern: {(p.get('human') or p.get('pattern', ''))[:60]}",
                    "what": f"{prev}% → {conf}%",
                    "why": (f"Repeated {p.get('repeats')}× since {p.get('first_seen')} — "
                            f"confidence {'rose' if conf > prev else 'fell'} as evidence accumulated."),
                    "direction": "up" if conf > prev else "down",
                    "from": prev,
                    "to": conf,
                })

        if self.memory:
            trust = self.memory.get_trust_score()
            prev_trust = prior_snapshot.get("trust_score")
            if prev_trust is not None and abs(trust - prev_trust) > 1:
                out.append({
                    "title": "Trust score",
                    "what": f"{prev_trust} → {trust}",
                    "why": ("Trust adjusts with engagement during conversations — "
                            "it rises on engaged turns and drops on avoidance."),
                    "direction": "up" if trust > prev_trust else "down",
                    "from": prev_trust,
                    "to": trust,
                })

        return sorted(out, key=lambda i: abs((i.get("to") or 0) - (i.get("from") or 0)),
                      reverse=True)[:6]

    def _questions_for_next_week(self):
        out = []

        if self.why_engine:
            p = self.why_engine.get_top(min_confidence=60)
            if p and p.get("follow_up"):
                out.append({
                    "title": "Follow-up on recurring pattern",
                    "what": p["follow_up"],
                    "why": (f"The strongest recurring pattern ({p.get('confidence')}%) "
                            f"deserves a direct check."),
                })

        if self.hypothesis_engine:
            h = self.hypothesis_engine.get_leading(min_confidence=50)
            if h:
                out.append({
                    "title": "Check the leading hypothesis",
                    "what": f"Has this changed? \"{str(h.get('hypothesis', ''))[:100]}\"",
                    "why": f"Leading hypothesis at {h.get('confidence')}% confidence.",
                })

        if self.memory:
            pending = self.memory.get_pending_confirmation()
            if pending and pending.get("question"):
                out.append({
                    "title": "Finish an open confirmation",
                    "what": pending["question"],
                    "why": "An earlier claim is still awaiting confirmation.",
                })

        if self.belief_engine:
            for b in self.belief_engine.get_beliefs(min_confidence=30):
                question = _BELIEF_QUESTIONS.get(b.get("id", ""))
                conf = b.get("confidence", 0)
                if question and 30 <= conf <= 65:
                    out.append({
                        "title": "Settle an unsettled belief",
                        "what": question,
                        "why": (f"Belief \"{b.get('belief', '')[:70]}\" sits at {conf}% — "
                                f"not fully settled yet."),
                    })
                if len(out) >= 4:
                    break

        if not out:
            out.append({
                "title": "First step: keep tracking",
                "what": "What would you most like to focus on next week?",
                "why": ("Not enough patterns or hypotheses yet to auto-generate "
                        "questions — more data makes the questions sharper."),
            })
        return out[:4]

    # ─── Summary (narrative) ──────────────────────────────────

    def _build_summary(self, sections, achievements, metrics):
        parts = []

        patterns = sections.get("recurring_patterns") or []
        if patterns and patterns[0].get("confidence"):
            p = patterns[0]
            parts.append(f"The strongest recurring pattern this period: "
                         f"{p['what'][:80]} ({p.get('confidence')}% confidence).")

        trends = sections.get("confidence_trends") or []
        if trends:
            t = trends[0]
            parts.append(f"Confidence moved {t['direction']} on \"{t['title']}\" "
                         f"({t.get('from')}% → {t.get('to')}%).")

        interventions = sections.get("successful_interventions") or []
        if interventions and interventions[0].get("successes", 0) > 0:
            i = interventions[0]
            parts.append(f"Most reliable approach so far: {i['title']} "
                         f"(completed {i['successes']} of {i['attempts']} attempts).")

        habits = sections.get("difficult_habits") or []
        if habits:
            names = ", ".join(h["title"] for h in habits[:3])
            parts.append(f"Hardest areas right now: {names}.")

        if achievements:
            parts.insert(0, f"You reported progress on: {'; '.join(str(a) for a in achievements[:2])}.")

        if not parts:
            n_facts = len(metrics)
            n_traits = len(self.behavior_engine.get_traits()) if self.behavior_engine else 0
            n_patterns = len(self.why_engine.get_patterns()) if self.why_engine else 0
            parts.append(
                f"Not enough evidence for a full picture yet ({n_facts} fact-derived metrics, "
                f"{n_traits} traits, {n_patterns} patterns). "
                f"Keep tracking — the why behind your trends sharpens as data builds.")

        return " ".join(parts[:4])

    # ─── Snapshot (for next report's confidence trends) ───────

    def _build_snapshot(self, metrics):
        snapshot = {
            "generated_at": now_iso(),
            "metrics": metrics,
        }
        if self.memory:
            snapshot["trust_score"] = self.memory.get_trust_score()
        if self.behavior_engine:
            snapshot["trait_confidence"] = {
                t: e.get("confidence", 0) for t, e in self.behavior_engine.get_traits().items()}
        if self.belief_engine:
            snapshot["belief_confidence"] = {
                b.get("id"): b.get("confidence", 0) for b in self.belief_engine.get_beliefs()}
        if self.why_engine:
            snapshot["pattern_confidence"] = {
                "|".join(sorted(p.get("signals") or [])): p.get("confidence", 0)
                for p in self.why_engine.get_patterns()}
        return snapshot

    def _load_previous_snapshot(self, period):
        if not self.memory:
            return {}
        prev = load_json(get_report_path(self.memory.user_id, period))
        return (prev or {}).get("state_snapshot") or {}

    # ─── Helpers ──────────────────────────────────────────────

    @staticmethod
    def _snippet(evidence):
        for e in reversed(evidence or []):
            snippet = str(e.get("snippet", "")).replace("counter: ", "")
            if snippet:
                return snippet[:80]
        return ""

    @staticmethod
    def _within_days(iso, max_days):
        if not iso:
            return False
        try:
            return days_since(str(iso)[:10]) <= max_days
        except Exception:
            return False

    @staticmethod
    def _days_since(iso):
        if not iso:
            return 0
        try:
            last = datetime.fromisoformat(str(iso))
        except (TypeError, ValueError):
            return 0
        return max(0, (datetime.now() - last).days)
