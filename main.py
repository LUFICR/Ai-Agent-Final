#!/usr/bin/env python3
"""Wellness Companion — CLI mode. Use `python app.py` for web UI."""
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wellness_agent.orchestrator import Orchestrator
from wellness_agent.synthetic_data import SyntheticDataGenerator


def print_header():
    llm_status = "🧠 LLM" if Orchestrator().llm.is_available() else "⚙️ Rules"
    print(f"\n{'='*60}")
    print(f"  Wellness Companion — {llm_status}")
    print(f"{'='*60}")
    print(f"  /quit  /help  /summary  /memory  /state  /report")
    print(f"  /insight  /routine  /synthetic  /reset")
    print(f"{'='*60}\n")


def main():
    print_header()
    orch = Orchestrator("default")

    greeting = orch.process_message("")
    print(f"🌿 {greeting['response']}\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nTake care.")
            break

        if not user_input:
            continue
        cmd = user_input.lower()

        if cmd in ("quit", "exit", "/quit"):
            print(f"\n🌿 Take care. I'll be here when you need me.\n")
            break
        if cmd in ("/help", "/h"):
            print("Commands: /quit  /summary  /memory  /state  /report [d|w]  /insight  /routine  /synthetic  /reset\n")
            continue
        if cmd in ("/summary", "/sum"):
            s = orch.get_summary()
            print(f"  State: {s['state']['current_state']} | Turns: {s['state']['total_turns']}")
            print(f"  Pillar: {s['current_pillar']} | Trust: {s['trust_score']}/100")
            print(f"  Facts: {s['memory']['facts_count']} | LLM: {s['llm_available']}\n")
            continue
        if cmd in ("/memory", "/mem"):
            facts = orch.agents.memory.get_all_facts()
            if not facts:
                print("  No facts stored.\n")
            else:
                for f in facts:
                    print(f"  [{f['category']}] {f['key']}: {f['value']} ({f['confidence']}%)")
                print()
            continue
        if cmd in ("/state", "/st"):
            si = orch.state_machine.get_state_info()
            print(json.dumps(si, indent=2, default=str))
            print()
            continue
        if cmd.startswith("/report"):
            parts = cmd.split()
            period = "daily" if len(parts) < 2 or parts[1] in ("d", "day") else "weekly"
            r = orch.agents.report_generator.generate(period)
            titles = {
                "behavior_changes": "Behavior Changes",
                "recurring_patterns": "Recurring Patterns",
                "successful_interventions": "Most Successful Interventions",
                "difficult_habits": "Most Difficult Habits",
                "confidence_trends": "Confidence Trends",
                "questions_for_next_week": "Questions for Next Week",
            }
            print(f"\n--- {period.title()} Report ---")
            print(f"  {r['summary']}\n")
            for key, label in titles.items():
                items = r['sections'].get(key, [])
                if not items:
                    continue
                print(f"  {label}:")
                for item in items:
                    print(f"  • {item.get('what', '')}")
                    why = item.get('why', '')
                    if why:
                        print(f"    Why: {why}")
                print()
            print()
            continue
        if cmd in ("/insight", "/i"):
            if orch.current_insight:
                i = orch.current_insight
                print(f"  Root cause: {i['likely_root_cause']} ({i['probability']}%)")
                for o in i.get('chain', []):
                    print(f"    - {o['observation']} ({o['confidence']}%)")
                print(f"  Caveat: {i.get('caveat', '')}\n")
            else:
                print("  No insight yet.\n")
            continue
        if cmd in ("/routine", "/r"):
            if orch.current_routine:
                for a in orch.current_routine.get('actions', []):
                    print(f"  [{a['time_of_day']}] {a['action']} — {a['why']}")
                print()
            else:
                print("  No routine yet.\n")
            continue
        if cmd in ("/synthetic", "/synth"):
            gen = SyntheticDataGenerator()
            convos = gen.generate_batch(5)
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "synthetic_data.json")
            gen.export_json(path)
            print(f"  Generated {len(convos)} conversations → {path}\n")
            continue
        if cmd in ("/reset"):
            orch.reset_state()
            print("  Reset.\n")
            continue

        result = orch.process_message(user_input)
        response = result.get("response", "")
        prefix = "⚠️ " if result.get("risk_detected") else "🌿 "
        print(f"\n{prefix}{response}\n")

        if result.get("risk_detected"):
            print("  ─" * 15)
            print("  CRISIS SUPPORT: 988 Suicide & Crisis Lifeline (US)")
            print("  ─" * 15 + "\n")


if __name__ == "__main__":
    main()
