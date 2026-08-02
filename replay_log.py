"""Conversation log replay — DEBUG-ONLY CLI. Reads data/conversation_logs/.

Usage:
    python replay_log.py list                          list JSON logs
    python replay_log.py summary <name>                per-turn stats
    python replay_log.py show <name>                   full transcript
    python replay_log.py play <name> [start_turn]      step-by-step (Enter to advance, q to quit)

`name` accepts an exact filename, a partial match, or "latest"
(most recent conversation file). JSON logs are the source of truth;
the daily Markdown transcripts are rendered views of the same records.
"""

import json
import sys
from pathlib import Path

LOGS_DIR = Path(__file__).resolve().parent / "data" / "conversation_logs"


def _fail(msg):
    print(msg)
    sys.exit(1)


def list_logs():
    if not LOGS_DIR.is_dir():
        print("(no conversation logs yet)")
        return []
    return sorted(LOGS_DIR.glob("conversation_*.json"))


def resolve(name):
    if name == "latest":
        files = list_logs()
        if not files:
            _fail("no conversation logs found")
        return files[-1]
    exact = LOGS_DIR / name
    if exact.exists():
        return exact
    files = [f for f in list_logs() if name in f.name]
    if len(files) == 1:
        return files[0]
    if len(files) > 1:
        _fail("ambiguous match %r — candidates:\n  %s"
              % (name, "\n  ".join(f.name for f in files)))
    _fail("no log matches %r (try 'python replay_log.py list')" % name)


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ─── commands ──────────────────────────────────────────────────────────

def cmd_list():
    files = list_logs()
    if not files:
        print("(no conversation logs yet)")
        return
    print("%-40s %-14s %-8s %-8s %s" % ("file", "conversation", "turns", "kb", "started"))
    for f in files:
        try:
            doc = load(f)
        except (OSError, json.JSONDecodeError):
            print("%-40s (unreadable)" % f.name)
            continue
        meta = doc.get("metadata", {})
        print("%-40s %-14s %-8s %-8s %s" % (
            f.name, meta.get("conversation_id", "?"),
            meta.get("total_turns", "?"),
            round(f.stat().st_size / 1024, 1),
            (meta.get("started_at") or "")[:19],
        ))


def cmd_summary(name):
    doc = load(resolve(name))
    meta = doc.get("metadata", {})
    turns = doc.get("turns", [])
    print("conversation : %s" % meta.get("conversation_id"))
    print("started      : %s" % meta.get("started_at"))
    print("ended        : %s" % meta.get("ended_at"))
    print("turns        : %s" % meta.get("total_turns"))
    print("versions     : runtime=%s planner=%s intent_resolver=%s"
          % (meta.get("runtime_version"), meta.get("planner_version"),
             meta.get("intent_resolver_version")))
    print("git_commit   : %s" % meta.get("git_commit"))
    print()
    for t in turns:
        print("T%02d  %-22s action=%-22s mode=%s  risk=%s  %.0fms" % (
            t["turn_number"],
            (t.get("user_message") or "")[:22].replace("\n", " "),
            t.get("planner_action"),
            t.get("planner_mode"),
            t.get("risk_detected"),
            t.get("response_time_ms") or 0,
        ))


def cmd_show(name):
    doc = load(resolve(name))
    meta = doc.get("metadata", {})
    print("# Conversation %s (%s)" % (meta.get("conversation_id"),
                                      meta.get("started_at")))
    for t in doc.get("turns", []):
        _print_turn(t)
        print("-" * 40)


def cmd_play(name, start=1):
    doc = load(resolve(name))
    turns = doc.get("turns", [])
    if not turns:
        print("(no turns)")
        return
    start = max(1, int(start))
    for t in turns[start - 1:]:
        _print_turn(t)
        if t is not turns[-1]:
            key = input("\n[Enter] next turn, q quit > ").strip().lower()
            if key == "q":
                print("(replay stopped)")
                return
    print("\n(end of conversation)")


def _print_turn(t):
    print("Turn %s  [%s]" % (t.get("turn_number"), (t.get("timestamp") or "")[:19]))
    print("  user     : %s" % (t.get("user_message") or "(empty)"))
    intent = t.get("intent") or {}
    print("  intent   : primary=%s confidence=%s secondary=%s"
          % (intent.get("primary"), intent.get("confidence"),
             intent.get("secondary")))
    print("  branch   : %s | state: %s"
          % (t.get("active_branch") or "-",
             (t.get("state") or {}).get("current_state") if isinstance(
                 t.get("state"), dict) else t.get("state")))
    print("  planner  : action=%s mode=%s (before=%s) conf=%s"
          % (t.get("planner_action"), t.get("planner_mode"),
             (t.get("planner") or {}).get("mode_before"),
             (t.get("planner") or {}).get("confidence")))
    print("  reason   : %s" % (t.get("planner_reason") or "-"))
    buttons = t.get("buttons_shown")
    if buttons:
        print("  buttons  : %s | clicked: %s"
              % (", ".join(str(b) for b in buttons),
                 t.get("button_clicked") or "-"))
    print("  runtime  : %s | engines: %s"
          % (t.get("runtime_state"), ", ".join(t.get("engine_execution_order") or [])))
    print("  memory   : %s facts (trust %s) | slots %s -> %s"
          % ((t.get("memory_used") or {}).get("facts_total", 0),
             (t.get("memory_used") or {}).get("trust_score"),
             (t.get("slots_before") or {}).get("keys") or
             ("{" + ", ".join(t.get("slots_before") or {}) + "}" if t.get("slots_before") else "{}"),
             (t.get("slots_after") or {}).get("keys") or
             ("{" + ", ".join(t.get("slots_after") or {}) + "}" if t.get("slots_after") else "{}")))
    if t.get("risk_detected"):
        print("  RISK     : detected")
    print("  assistant: %s" % (t.get("ai_response") or "(empty)"))


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)
    cmd = sys.argv[1]
    if cmd == "list":
        cmd_list()
    elif cmd == "summary":
        if len(sys.argv) < 3:
            _fail("usage: python replay_log.py summary <name>")
        cmd_summary(sys.argv[2])
    elif cmd == "show":
        if len(sys.argv) < 3:
            _fail("usage: python replay_log.py show <name>")
        cmd_show(sys.argv[2])
    elif cmd == "play":
        if len(sys.argv) < 3:
            _fail("usage: python replay_log.py play <name> [start_turn]")
        cmd_play(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else 1)
    else:
        _fail("unknown command %r — see usage above" % cmd)


if __name__ == "__main__":
    main()
