"""HTTP API + static PWA."""
import logging
import os
import secrets
import time
from collections import deque
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config
from .agent import Agent
from .memory import Memory
from .tools import load_tools

log = logging.getLogger("bit")
app = FastAPI(title="Bit agent", docs_url=None, redoc_url=None)
memory = Memory(config.DATA_DIR / "bit.db")
tools = load_tools()
_agent: Agent | None = None


def get_agent() -> Agent:
    global _agent
    if _agent is None:
        if not config.llm_configured():
            key = "ANTHROPIC_API_KEY" if config.LLM_PROVIDER == "anthropic" else "OPENAI_API_KEY / OPENAI_BASE_URL"
            raise HTTPException(503, f"{key} is not set on the server")
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
    now = time.time()  # simple global rate limit: 60 requests per minute
    while _hits and now - _hits[0] > 60:
        _hits.popleft()
    if len(_hits) >= 60:
        raise HTTPException(429, "too many requests")
    _hits.append(now)


class ChatIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    lang_mode: str = "auto"
    smart: bool = False


class TtsIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    lang: str = "uz"


class ConfirmIn(BaseModel):
    id: str = Field(min_length=1, max_length=40)
    approve: bool


@app.get("/api/health")
def health():
    return {"ok": True, "tools": sorted(tools), "autonomy": config.AUTONOMY_LEVEL,
            "telegram": bool(config.TELEGRAM_SESSION), "llm": config.llm_configured(), "provider": config.LLM_PROVIDER, "tts": config.TTS_MODE}


@app.post("/api/chat", dependencies=[Depends(auth)])
async def chat(body: ChatIn):
    agent = get_agent()
    try:
        return await agent.chat(body.text.strip(), body.lang_mode, body.smart)
    except HTTPException:
        raise
    except Exception as e:
        log.exception("chat failed")  # full traceback in the server terminal
        status = getattr(e, "status_code", None)
        if status == 429:
            raise HTTPException(429, "LLM rate limit")
        msg = str(getattr(e, "message", "") or e).replace(config.ANTHROPIC_API_KEY or "\0", "***").replace(config.OPENAI_API_KEY or "\0", "***")[:300]
        raise HTTPException(502, f"LLM error: {type(e).__name__}: {msg}")


@app.post("/api/tts", dependencies=[Depends(auth)])
async def tts(body: TtsIn):
    if config.TTS_MODE != "edge":
        raise HTTPException(404, "server TTS is off (BIT_TTS)")
    from .tts import synthesize
    try:
        audio = await synthesize(body.text, body.lang if body.lang in ("uz", "ru", "en") else "uz")
    except Exception as e:
        log.warning("tts failed: %r", e)
        raise HTTPException(502, f"TTS error: {type(e).__name__}")
    return Response(content=audio, media_type="audio/mpeg", headers={"Cache-Control": "no-store"})


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
