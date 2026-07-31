"""Scenario runner: drive the real orchestrator offline through adversarial users.

Each scenario runs through a fresh Orchestrator instance (matching the sim
engine's offline pattern: GROQ_API_KEY popped in-process, deterministic
fallback responses). Per-turn records capture everything the scorer needs:

  - assistant response + route + state + objective
  - risk/crisis flags from emotion extraction
  - memory facts added (vs truth facts)
  - self-evaluation + judge evaluation at the end
"""

import os
import time
from datetime import datetime

from stress.scenarios import ScenarioRuntime, SCENARIOS

USER_PREFIX = "stress_user_"


def _cleanup_stores(user_id):
    try:
        from simulation.simulator import _cleanup_stores as sim_cleanup
        sim_cleanup(user_id)
    except Exception:
        pass


def run_scenario(scenario_id, seed=1, offline=True, target_turns=None,
                 keep_stores=False, evaluate=True):
    """Run one adversarial scenario. Returns a result dict.

    offline=True pops GROQ_API_KEY so the real pipeline uses deterministic
    fallbacks (llm_used=False). The orchestrator is fully exercised.
    """
    spec = SCENARIOS[scenario_id]
    user_id = f"{USER_PREFIX}{scenario_id}_{seed}"
    target_turns = target_turns or spec.get("turns", 8)

    if offline:
        os.environ.pop("GROQ_API_KEY", None)

    _cleanup_stores(user_id)

    from wellness_agent.orchestrator import Orchestrator
    orch = Orchestrator(user_id=user_id, enable_auto_judge=False)
    rt = ScenarioRuntime(scenario_id, seed)
    turns = []
    started = time.time()

    try:
        while rt.turn < target_turns:
            assistant_text = turns[-1]["assistant_response"] if turns else ""
            turn_info = turns[-1] if turns else None
            message = rt.next_message(assistant_text, turn_info)

            memory_before = {f.get("key") for f in orch.agents.memory.get_all_facts()}
            res = orch.process_message(message)
            memory_after = orch.agents.memory.get_all_facts()
            added = [{"key": f.get("key"), "value": str(f.get("value"))[:60],
                      "confidence": f.get("confidence")}
                     for f in memory_after if f.get("key") not in memory_before]

            emotion = res.get("emotion") or {}
            turn = {
                "n": len(turns) + 1,
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "user_message": message,
                "assistant_response": res.get("response"),
                "route": res.get("route"),
                "state": (res.get("state") or {}).get("current_state"),
                "state_stack": (res.get("state") or {}),
                "objective": (res.get("objective") or {}).get("objective"),
                "risk_detected": bool(res.get("risk_detected")),
                "emotion": emotion,
                "llm_used": bool(res.get("llm_used")),
                "memory_changes": {
                    "added": added[:8],
                    "added_count": len(added),
                    "facts_total": len(memory_after),
                    "trust_score": orch.agents.memory.get_trust_score(),
                },
            }
            turns.append(turn)

            if emotion.get("crisis"):
                break

        result = {
            "scenario_id": scenario_id,
            "label": spec["label"],
            "category": spec.get("category"),
            "difficulty": spec.get("difficulty"),
            "seed": seed,
            "user_id": user_id,
            "turns": len(turns),
            "target_turns": target_turns,
            "truth": spec.get("truth", {}),
            "turns_data": turns,
            "elapsed": round(time.time() - started, 3),
            "evaluation": None,
        }

        if evaluate:
            result["evaluation"] = _evaluate_scenario(orch, turns, scenario_id, seed)
        return result
    finally:
        if not keep_stores:
            _cleanup_stores(user_id)


def _evaluate_scenario(orch, turns, scenario_id, seed):
    """Score the run with the deterministic ConversationJudge (no store write)."""
    judge = orch.agents.conversation_judge
    from wellness_agent.conversation_judge import detect_commit_id
    payload = {"turns": [judge._normalize_turn(t) for t in turns],
               "memory": None, "trust_score": None,
               "beliefs": None, "reasoning_context": None,
               "ended": "risk" if turns and turns[-1]["risk_detected"] else "complete"}
    meta = {"source": "stress", "scenario_id": scenario_id, "seed": seed,
            "commit_id": detect_commit_id()}
    # evaluate(record) writes to the store; here we only need dims,
    # so compute via the same signals path the judge uses.
    s = judge._signals(payload)
    dims = judge._score_dimensions(s)
    return {"dims": dims, "signals": s}
