"""Dynamic Conversation Quick Replies — integration tests.

The planner attaches four conversation-ENTRY quick replies
(Work / Relationships / Mental health / Physical health) to open prompts
(greeting, soft exploration, no active topic). They start a topic; they are
NOT diagnostic category buttons.

Verified behaviors:
1. Greeting -> conversation-entry buttons shown
2. Open prompt (no active topic) -> buttons shown
3. Free text -> buttons ignored, conversation continues naturally
4. Click "Work" -> Work topic begins
5. Click "Mental health" -> Mental Health topic begins
6. Active topic -> buttons hidden

Offline: GROQ_API_KEY is popped so rule-based fallbacks are exercised and
every assertion is deterministic.
"""

import glob
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.pop("GROQ_API_KEY", None)

from wellness_agent.conversation_planner import (  # noqa: E402
    _QUICK_REPLY_ENTRY_BUTTONS,
    _QUICK_REPLY_TYPE_CONVERSATION_ENTRY,
)
from wellness_agent.orchestrator import Orchestrator  # noqa: E402

FAILURES = []


def check(name, fn):
    try:
        fn()
        print("  ok - %s" % name)
    except Exception as exc:  # noqa: BLE001
        FAILURES.append((name, exc))
        print("  FAIL - %s: %s: %s" % (name, type(exc).__name__, exc))


DATA_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
UIDS = []


def fresh_orch(prefix):
    uid = "%s_qr_%d_%d" % (prefix, len(UIDS), int(time.time() * 1000))
    UIDS.append(uid)
    return Orchestrator(user_id=uid, enable_learning=False, enable_auto_judge=False)


def cleanup():
    for uid in UIDS:
        for sub in ("sessions", "memory", "beliefs", "learning"):
            for f in glob.glob(os.path.join(DATA_ROOT, sub, "%s*.json" % uid)):
                try:
                    os.remove(f)
                except OSError:
                    pass


def entry_buttons():
    return list(_QUICK_REPLY_ENTRY_BUTTONS)


# ─── 1. Greeting -> buttons shown ─────────────────────────────────────

def test_greeting_shows_entry_buttons():
    for msg in ("hi", "hello", "hey", "good morning"):
        o = fresh_orch("g")
        r = o.process_message(msg)
        pd = r.get("planner_decision") or {}
        assert r.get("options") == entry_buttons(), \
            "greeting %r must show entry buttons: %r" % (msg, r.get("options"))
        assert r.get("show_quick_replies") is True, r.get("planner_decision")
        assert r.get("quick_replies") == entry_buttons()
        assert r.get("quick_reply_type") == _QUICK_REPLY_TYPE_CONVERSATION_ENTRY
        assert pd.get("showQuickReplies") is True, pd
        assert pd.get("quickReplies") == entry_buttons(), pd
        assert pd.get("quickReplyType") == _QUICK_REPLY_TYPE_CONVERSATION_ENTRY, pd
        assert r["response"].strip().endswith("?")


# ─── 2. Open prompt (no active topic) -> buttons shown ────────────────

def test_open_prompt_shows_entry_buttons():
    o = fresh_orch("open")
    o.process_message("hello")
    o.state_machine.set_state("soft_exploration")
    r = o.process_message("hmm")
    pd = r.get("planner_decision") or {}
    assert r.get("options") == entry_buttons(), \
        "open prompt must show entry buttons: %r" % r.get("options")
    assert r.get("show_quick_replies") is True
    assert pd.get("quickReplyType") == _QUICK_REPLY_TYPE_CONVERSATION_ENTRY, pd


# ─── 3. Free text -> buttons ignored ──────────────────────────────────

def test_free_text_ignores_buttons():
    o = fresh_orch("ft")
    o.process_message("hello")  # buttons shown
    r = o.process_message("I'm stressed because of work")
    assert r.get("options") is None, "rich free text must ignore buttons"
    assert r.get("show_quick_replies") is False
    assert r.get("quick_replies") == []
    assert (r.get("planner_decision") or {}).get("showQuickReplies") is False
    # ...and a topic-signal reply (even short) starts the topic, no buttons
    o2 = fresh_orch("ft2")
    o2.process_message("hello")
    r2 = o2.process_message("sleep")
    assert r2.get("options") is None, "topic signal must not show buttons"
    assert r2.get("show_quick_replies") is False


# ─── 4. Click "Work" -> Work topic begins ─────────────────────────────

def test_click_work_starts_work_topic():
    o = fresh_orch("work")
    o.process_message("hello")
    r = o.process_message("💼 Work")
    assert o.current_pillar == "work", "clicking Work must start the work topic"
    assert r.get("options") is None, "buttons disappear once topic starts"
    assert r.get("show_quick_replies") is False
    assert r.get("quick_replies") == []
    # a follow-up topic message stays button-free (topic established)
    r2 = o.process_message("It's my manager piling on work")
    assert r2.get("options") is None
    assert r2.get("show_quick_replies") is False


# ─── 5. Click "Mental health" -> Mental Health topic begins ───────────

def test_click_mental_health_starts_mental_health_topic():
    o = fresh_orch("mh")
    o.process_message("hello")
    r = o.process_message("🧠 Mental health")
    assert o.current_pillar == "mood", \
        "clicking Mental health must start the mental health (mood) topic"
    assert r.get("options") is None
    assert r.get("show_quick_replies") is False


# ─── 6. Active topic -> buttons hidden ────────────────────────────────

def test_active_topic_hides_buttons():
    o = fresh_orch("hidden")
    o.process_message("hello")  # entry buttons shown once
    o.process_message("💼 Work")  # topic starts
    assert o.current_pillar == "work"
    r1 = o.process_message("I'm stressed about deadlines")
    assert r1.get("show_quick_replies") is False
    assert r1.get("options") is None
    r2 = o.process_message("hmm")
    assert r2.get("show_quick_replies") is False, r2.get("planner_decision")
    assert r2.get("quick_replies") == [], \
        "no entry buttons while investigating a topic"
    r3 = o.process_message("I don't know")
    assert r3.get("show_quick_replies") is False, \
        "uncertainty during a topic uses the recovery tree, not entry buttons"
    assert r3.get("quick_replies") == []


def main():
    print("DYNAMIC CONVERSATION QUICK REPLIES suite")
    check("1. greeting -> entry buttons shown", test_greeting_shows_entry_buttons)
    check("2. open prompt -> entry buttons shown", test_open_prompt_shows_entry_buttons)
    check("3. free text -> buttons ignored", test_free_text_ignores_buttons)
    check("4. click Work -> work topic begins", test_click_work_starts_work_topic)
    check("5. click Mental health -> mental health topic begins",
          test_click_mental_health_starts_mental_health_topic)
    check("6. active topic -> buttons hidden", test_active_topic_hides_buttons)

    cleanup()
    if FAILURES:
        print("\nFAILURES: %d" % len(FAILURES))
        for name, exc in FAILURES:
            print("  - %s: %s: %s" % (name, type(exc).__name__, exc))
        raise SystemExit(1)
    print("\nALL PASS")


if __name__ == "__main__":
    main()
