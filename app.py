"""FastAPI web app — deployable on free tiers (Render, Railway, Fly.io)."""

import os
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse, Response
from wellness_agent.orchestrator import Orchestrator
from wellness_agent.utils.storage import load_json

app = FastAPI(title="Wellness Companion")

# Session store
_sessions: dict[str, Orchestrator] = {}
MAX_SESSIONS = 50


def get_orch(user_id: str = "default") -> Orchestrator:
    if user_id not in _sessions:
        if len(_sessions) >= MAX_SESSIONS:
            _sessions.pop(next(iter(_sessions)))
        _sessions[user_id] = Orchestrator(user_id)
    return _sessions[user_id]

HERE = Path(__file__).parent
LOGIN_PATH = HERE / "templates" / "login.html"
CHAT_PATH = HERE / "templates" / "chat.html"


@app.get("/", response_class=HTMLResponse)
async def login_page(request: Request):
    html = LOGIN_PATH.read_text(encoding="utf-8")
    return HTMLResponse(html)


@app.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request, user: str = "default"):
    html = CHAT_PATH.read_text(encoding="utf-8")
    return HTMLResponse(html)


@app.post("/chat")
async def chat(request: Request, message: str = Form(""), session_id: str = Form("default")):
    orch = get_orch(session_id)
    result = orch.process_message(message)
    resp_data = {
        "response": result["response"],
        "options": result.get("options"),
        "show_quick_replies": result.get("show_quick_replies", False),
        "quick_replies": result.get("quick_replies", []),
        "quick_reply_type": result.get("quick_reply_type", ""),
        "state": result["state"]["current_state"],
        "emotion": result["emotion"]["primary_emotion"],
        "risk": result["risk_detected"],
        "llm": result.get("llm_used", False),
        "pillar": orch.current_pillar,
        "objective": orch.current_objective,
        "behaviors": orch.agents.behavior_engine.get_traits(),
        "hypotheses": orch.agents.hypothesis_engine.get_hypotheses(),
        "whys": orch.agents.why_engine.get_patterns()[:5],
        "beliefs": orch.agents.belief_engine.get_beliefs()[:5],
        "pending_confirmation": orch.agents.memory.get_pending_confirmation(),
        "last_checkin": orch.last_checkin,
        "ranked_interventions": orch._ranked_interventions,
        "reasoning_context": orch.reasoning_ctx,
        "self_evaluation": orch._last_eval,
        "evaluation_track": orch.agents.self_evaluator.get_track(),
    }

    if result.get("judge"):
        resp_data["judge"] = {
            k: result["judge"][k]
            for k in ("conversation_id", "overall_score", "coaching", "memory",
                      "conversation", "issues", "recommendations")
        }

    if result.get("risk_detected"):
        resp_data["crisis"] = True

    return JSONResponse(resp_data)


@app.post("/judge/{session_id}")
async def judge(session_id: str = "default"):
    """Score the stored conversation for a session with the Conversation Judge."""
    orch = get_orch(session_id)
    payload = {
        "turns": (load_json(orch.session_path) or {}).get("turns", []),
        "memory": orch.agents.memory.get_all_facts(),
        "trust_score": orch.agents.memory.get_trust_score(),
        "reasoning_context": orch.reasoning_ctx,
    }
    meta = {"source": "live", "session_id": session_id}
    record = orch.agents.conversation_judge.evaluate(payload, meta=meta)
    return JSONResponse({
        "conversation_id": record["conversation_id"],
        "overall_score": record["overall_score"],
        "coaching": record["coaching"],
        "memory": record["memory"],
        "conversation": record["conversation"],
        "dimensions": record["dimensions"],
        "issues": record["issues"],
        "recommendations": record["recommendations"],
    })


@app.get("/summary/{session_id}")
async def summary(session_id: str = "default"):
    orch = get_orch(session_id)
    return JSONResponse(orch.get_summary())


@app.get("/memory/{session_id}")
async def memory(session_id: str = "default"):
    orch = get_orch(session_id)
    return JSONResponse({"facts": orch.agents.memory.get_all_facts()})


@app.get("/insight/{session_id}")
async def insight(session_id: str = "default"):
    orch = get_orch(session_id)
    if orch.current_insight:
        return JSONResponse(orch.current_insight)
    return JSONResponse({"error": "No insight yet"})


@app.get("/routine/{session_id}")
async def routine(session_id: str = "default"):
    orch = get_orch(session_id)
    if orch.current_routine:
        return JSONResponse(orch.current_routine)
    return JSONResponse({"error": "No routine yet"})


@app.post("/report/{session_id}")
async def report(session_id: str = "default", period: str = "daily"):
    orch = get_orch(session_id)
    report_data = orch.agents.report_generator.generate(period)
    return JSONResponse(report_data)


@app.post("/reset/{session_id}")
async def reset(session_id: str = "default"):
    orch = get_orch(session_id)
    orch.reset_state()
    return JSONResponse({"status": "reset"})


@app.get("/api/logs")
async def api_logs():
    """List all recorded conversation logs (JSON files)."""
    from wellness_agent.conversation_logger import get_conversation_logger
    logger = get_conversation_logger()
    logger.flush()
    entries = []
    for f in sorted(logger.log_dir.glob("conversation_*.json")):
        data = load_json(f) or {}
        meta = data.get("metadata") or {}
        entries.append({
            "filename": f.name,
            "conversation_id": meta.get("conversation_id") or data.get("conversation_id"),
            "started_at": meta.get("started_at") or data.get("started_at"),
            "ended": (meta.get("ended_at") or data.get("ended_at")) is not None,
            "turns": len(data.get("turns", []) or []),
            "size_bytes": f.stat().st_size,
        })
    return JSONResponse({"count": len(entries), "conversations": entries})


@app.get("/api/logs/{filename}")
async def api_log_download(filename: str, format: str = "json"):
    """Download one conversation log as JSON or Markdown (default: json)."""
    from wellness_agent.conversation_logger import (
        _render_markdown_turn,
        get_conversation_logger,
    )
    logger = get_conversation_logger()
    logger.flush()
    name = Path(filename).name
    if not name.startswith("conversation_") or not name.endswith(".json"):
        return JSONResponse({"error": "invalid filename"}, status_code=400)
    path = (logger.log_dir / name).resolve()
    if path.parent != logger.log_dir.resolve():
        return JSONResponse({"error": "invalid filename"}, status_code=400)
    if not path.exists():
        return JSONResponse({"error": "not found"}, status_code=404)
    data = load_json(path) or {}
    if format == "md":
        turns = data.get("turns", []) or []
        md = "".join(
            _render_markdown_turn(None, turn, include_header=(i == 0))
            for i, turn in enumerate(turns)
        )
        return Response(
            content=md, media_type="text/markdown",
            headers={"Content-Disposition": f'attachment; filename="{name[:-5]}.md"'},
        )
    return JSONResponse(
        data,
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@app.get("/health")
async def health():
    from wellness_agent.llm_service import GroqLLM
    llm = GroqLLM()
    return {"status": "ok", "llm_available": llm.is_available()}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)
