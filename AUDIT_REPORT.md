AUDIT FINDINGS REPORT — Wellness Companion Agent
================================================

1. STATE MACHINE INTEGRITY
--------------------------
Checked: config STATES (line 32-36), state_machine transition rules (lines 20-143), 
orchestrator process flow (line 80-179), all response branches in _generate_response (lines 250-378).

PASS:
- Every defined state (greeting, free_conversation, guided_discovery, pillar_selection, 
  deep_investigation, insight_generation, routine_planning, reflection, follow_up, 
  avoidance_detection, soft_exploration, rapport_building, weekly_review) has entry/exit logic.
- Risk protocol (line 99-105) hard-bypasses all routing first.

ISSUES FOUND:
- SEVERITY BLOCKS CONVERSATION: Exit-offer handler (lines 126-142) consumes ANY user reply 
  when _exit_offered=True. If user types a wellness topic instead of Yes/No, it still returns 
  "No worries — want to talk about something else..." and does NOT transition state or process 
  the topic. File: orchestrator.py:127-142.
- SEVERITY DEGRADES QUALITY: Default case in _generate_response (line 356-358: else branch) 
  falls back to generic default cycler text. While it has repetition safeguard, it means 
  unexpected routes can silently land in unplanned response rather than erroring loudly.
  File: orchestrator.py:356-358.
- SEVERITY DEGRADES QUALITY: State transition on greeting (line 39-48) allows return to 
  None (stay in greeting) indefinitely if words < 3 and no topic signal — user can loop 
  in greeting without forced advancement.
  File: state_machine.py:39-48.

2. DATA GROUNDING / HALLUCINATION CHECK
------------------------------------------
Checked: memory.add_fact (memory.py:32-48), agent extract_and_store (agents.py:33-65), 
_generate_insight (orchestrator.py:420-446), reflection_response (agents.py:67-73), 
message variants (orchestrator.py:17-54).

PASS:
- Memory facts scoped per user (memory.py:8, user_id path).
- Insight chain pulls from memory.get_facts_by_pillar / emotional_history / habit_trends.

ISSUES FOUND:
- SEVERITY DEGRADES QUALITY: Reflection agent uses hardcoded templates based on stateInfo 
  flags (agents.py:67-73) — not grounded in session memory facts. Could say "solid plan" 
  without referencing actual routine actions.
  File: agents.py:67-73.
- SEVERITY COSMETIC/DEGRADES QUALITY: Base option templates in _generate_response (line 273) 
  hardcode emoji + pillar labels ["😴 Sleep", "💼 Work", etc.] with no link to current pillar 
  selection logic (except conditional highlight).
  File: orchestrator.py:273.
- SEVERITY BLOCKS QUALITY: Option-generation for hierarchical tree (edited) uses static 
  arrays; sub-category selection parses user text but doesn't feed selected_sub back into 
  memory as a pillar fact with full category/key/value structure — only sets self.current_pillar.

3. MEMORY SYSTEM
----------------
Checked: MemorySystem (memory.py:7-210), add_fact/update_fact/get_fact/get_all_facts, 
config MEMORY_CATEGORIES.

PASS:
- Every stored fact has category, key, value, confidence, source, last_updated (memory.py:36-44).
- Per-user isolation via user_id path (memory.py:8-11).
- Session count incremented (memory.py:208-210).

ISSUES FOUND:
- SEVERITY DEGRADES QUALITY: Low-confidence facts are never filtered before being presented 
  to user. Memory.get_facts_by_pillar returns all; insight generation uses them directly 
  without checking confidence threshold. No minimum confidence gate for user-facing statements.
  File: orchestrator.py:420-442, memory.py:73.
- SEVERITY COSMETIC: Memory.extract_facts_from_message uses regex with fixed confidence 
  (80, 75, etc.). These are reasonable but arbitrary; no validation against external source.

4. EMOTION & RISK DETECTION
----------------------------
Checked: process_message (line 95-105), _analyze_emotion (line 183-187), 
config EMOTION_DIMENSIONS (config.py:60-66).

PASS:
- Emotion detection runs first in process_message (line 95).
- Risk check is FIRST before routing (line 99-105) and hard-bypasses to crisis response.
- Risk response includes 988 reference (line 480-486).

ISSUES FOUND:
- SEVERITY BLOCKS SAFETY: If self.llm.extract_emotion returns None (line 184-186 checks 
  llm_result.get("primary_emotion")), it falls back to emotion_engine.analyze. This is safe, 
  but there's no explicit guard if emotion_engine also fails and returns empty dict — 
  risk_flag would never trigger.
  File: orchestrator.py:183-187.
- SEVERITY DEGRADES QUALITY: Emotion scores (depression_risk, anxiety) exist in dimension 
  list (config.py) but the agent never explicitly states them as diagnosis. However, 
  no code comment or guard prevents future developer from exposing these labels directly 
  to user in a response template.
  File: config.py:60-66 (potential, not active violation).

5. OPTIONS SYSTEM
------------------
Checked: All option arrays in _generate_response, question planner generation, 
exit-offer options, tree options.

PASS:
- Most option sets include escape-style choices (e.g., "Something else", "Let me explain").
- Buttons exist for every displayed message.

ISSUES FOUND:
- SEVERITY DEGRADES QUALITY: The hierarchical quick-path (edited in previous interaction) 
  does not include an explicit free-text fallback option label — user must type freely, 
  which is acceptable, but there's no visible "Something else" button for the category/sub 
  selection screens.
  File: orchestrator.py (edited tree logic).
- SEVERITY DEGRADES QUALITY: Option values (e.g., "Productivity", "Mental wellness", sub-categories) 
  are parsed by string matching in msg_lower but are not stored as structured response metadata. 
  If user mistypes a close variant ("anxiaty"), it falls through to the top-level prompt 
  instead of matching sub-category — no fuzzy matching or forgiveness logic.
- SEVERITY COSMETIC: Option buttons use emoji labels mixed with text; no accessibility 
  alt-text or structured ID mapping for analytics/state tracking.

6. AVOIDANCE & LOOP PROTECTION
-------------------------------
Checked: avoidance_count logic (line 68, 109-119, 121-124, 281-284, 286-288), 
_repeat_count / repetition safeguard (line 337-353, 360-376), exit logic.

PASS:
- Hard-coded avoidance counter (not LLM) at line 109-119.
- Defined thresholds: count==2 → state change to rapport_building; count>=3 + not consumed 
  → exit offer (line 281-284).
- Repetition safeguard detects same state + same text (line 337-353) and logs warning.

ISSUES FOUND:
- SEVERITY BLOCKS QUALITY: Repetition safeguard (line 360-376) uses warnings.warn, NOT 
  a critical exception or forced pipeline interruption. The bot can still send the repeated 
  message; it only tries a variant from the cycler. If cycle exhausts, it falls back to default. 
  No hard stop. Recommended: raise RuntimeError or at minimum log CRITICAL and force 
  state transition.
  File: orchestrator.py:360-376.
- SEVERITY DEGRADES QUALITY: Avoidance count resets to 0 when `len(words) < 3` is false, 
  but selection of a sub-category like "Anxiety / Worry" (3 words including "/") could still 
  be interpreted as deflecting if the code path reaches the original logic. The edit made 
  resets it for selected_sub, but the base logic remains fragile.
  File: orchestrator.py:109-119.
- SEVERITY DEGRADES QUALITY: No verification that a user reply that selects a button 
  actually consumes that selection — the exit handler (line 127-142) can swallow any reply 
  when _exit_offered=True, including an explicit sub-category choice.

7. SAFEGUARD FOR SILENT FAILURES
---------------------------------
Checked: warnings.warn usage (line 340-343, 360-376), exception handling in process_message, 
response generation default cases.

PASS:
- Repetition warning is emitted (line 340-343, 362-364).
- No bare except clauses found in main pipeline.

ISSUES FOUND:
- SEVERITY BLOCKS QUALITY / MISSING: The safeguard requested — if bot sends message identical 
  (or near-identical) to previous message with no state change, log CRITICAL / throw — is 
  PARTIALLY implemented as warnings.warn + variant substitution, but NOT as an error or 
  forced state break. The bot can still emit a near-duplicate silently if variant selection 
  produces a close match (e.g., same tone, different words).
  File: orchestrator.py:360-376. Fix: add explicit similarity check and raise if similarity 
  exceeds threshold without state change.
- SEVERITY COSMETIC: No centralized audit/logging endpoint for session-level loop detection; 
  only per-turn warning. A loop spanning 10 turns produces 10 warnings with no aggregated alert.

SUMMARY BY SEVERITY
-------------------
BLOCKS CONVERSATION (2):
- Exit-offer swallows non-Yes/No replies (orchestrator.py:127-142).
- Silent-failure safeguard missing critical interruption (orchestrator.py:360-376).

DEGRADES QUALITY (7):
- Greeting can loop indefinitely (state_machine.py:39-48).
- Reflection agent hardcoded (agents.py:67-73).
- Default case falls back silently (orchestrator.py:356-358).
- Low-confidence facts presented without filtering (memory.py + orchestrator.py:420-442).
- Quick-path has no fuzzy matching / structured option backing.
- Option parsing fragile against typos.
- Avoidance/exits can swallow valid selections.

COSMETIC / POTENTIAL (4):
- Hardcoded emoji pillars (line 273).
- Emotion label exposure unguarded (config.py:60-66).
- Memory regex confidence arbitrary.
- No aggregated loop audit endpoint.

RECOMMENDATIONS (prioritized)
-----------------------------
1. Fix exit-offer handler to detect wellness keywords before defaulting to chat/exit.
2. Strengthen repetition safeguard to throw/interrupt rather than warn-only.
3. Add confidence threshold gate (< 60) before using memory facts in user-facing text.
4. Make greeting state transition mandatory after N turns (prevent infinite loop).
5. Add structured option IDs and fuzzy matching for category/sub selections.
6. Filter memory facts by recency + confidence in insight generation.
7. Add centralized session loop detector (aggregate > 2 repeats = alert).
