"""HTTP API + static PWA."""
import os
import secrets
import time
from collections import deque
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config
from .agent import Agent
from .memory import Memory
from .tools import load_tools

app = FastAPI(title="Bit agent", docs_url=None, redoc_url=None)
memory = Memory(config.DATA_DIR / "bit.db")
tools = load_tools()
_agent: Agent | None = None


def get_agent() -> Agent:
    global _agent
    if _agent is None:
        if not config.ANTHROPIC_API_KEY:
            raise HTTPException(503, "ANTHROPIC_API_KEY is not set on the server")
        _agent = Agent(memory, tools)
    return _agent


_hits: deque = deque()


def auth(request: Request):
    if not config.API_TOKEN:
        raise HTTPException(503, "BIT_API_TOKEN is not set on the server")
    header = request.headers.get("authorization", "")
    token = header[7:] if header.lower().startswith("bearer ") else ""
    if not secrets.compare_digest(token.encode(), config.API_TOKEN.encode()):
        raise HTTPException(401, "bad token")
    now = time.time()  # simple global rate limit: 30 requests per minute
    while _hits and now - _hits[0] > 60:
        _hits.popleft()
    if len(_hits) >= 30:
        raise HTTPException(429, "too many requests")
    _hits.append(now)


class ChatIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    lang_mode: str = "auto"
    smart: bool = False


class ConfirmIn(BaseModel):
    id: str = Field(min_length=1, max_length=40)
    approve: bool


@app.get("/api/health")
def health():
    return {"ok": True, "tools": sorted(tools), "autonomy": config.AUTONOMY_LEVEL,
            "telegram": bool(config.TELEGRAM_SESSION), "llm": bool(config.ANTHROPIC_API_KEY)}


@app.post("/api/chat", dependencies=[Depends(auth)])
async def chat(body: ChatIn):
    agent = get_agent()
    try:
        return await agent.chat(body.text.strip(), body.lang_mode, body.smart)
    except HTTPException:
        raise
    except Exception as e:
        status = getattr(e, "status_code", None)
        if status == 429:
            raise HTTPException(429, "LLM rate limit")
        raise HTTPException(502, f"LLM error: {type(e).__name__}")


@app.post("/api/confirm", dependencies=[Depends(auth)])
async def confirm(body: ConfirmIn):
    return await get_agent().confirm(body.id, body.approve)


@app.get("/api/memory", dependencies=[Depends(auth)])
def get_memory():
    return {"facts": memory.facts()}


@app.delete("/api/memory", dependencies=[Depends(auth)])
def clear_memory():
    return {"deleted": memory.forget("*")}


@app.get("/api/audit", dependencies=[Depends(auth)])
def audit(limit: int = 50):
    return {"items": memory.audit_log(min(max(limit, 1), 500))}


_front = Path(os.getenv("BIT_FRONTEND_DIR", Path(__file__).resolve().parents[2] / "frontend"))
if _front.is_dir():
    app.mount("/", StaticFiles(directory=str(_front), html=True), name="app")
