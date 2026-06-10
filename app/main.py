"""FastAPI backend: OpenAI-compatible RAG endpoint + public chat page + logging.

- GET  /                       -> public chat page (no auth)
- GET  /healthz                -> health probe
- GET  /v1/models             -> OpenAI-compatible model list (for OpenWebUI)
- POST /v1/chat/completions   -> OpenAI-compatible chat (stream + non-stream), logged
- GET  /admin/logs?token=...  -> protected conversation viewer (for analysis)
"""
import html
import json
import time
import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse, HTMLResponse
from pydantic import BaseModel

from app import logging_store
from app.config import settings
from app.llm import chat, chat_stream
from app.rag import build_messages

app = FastAPI(title="AlaToo AI Consultant")
logging_store.init()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = Path(__file__).parent / "static"


class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: Optional[str] = None
    messages: List[Message]
    stream: bool = False
    temperature: float = 0.2


def _check_auth(authorization: Optional[str]) -> None:
    if not settings.backend_api_key:
        return
    if authorization != f"Bearer {settings.backend_api_key}":
        raise HTTPException(status_code=401, detail="Invalid API key")


def _sources_summary(chunks: List[dict]) -> List[dict]:
    return [
        {"title": c.get("title", ""), "source": c.get("source", ""),
         "source_url": c.get("source_url", ""), "score": round(c.get("score", 0), 3)}
        for c in chunks
    ]


@app.get("/healthz")
def healthz():
    return {"status": "ok", "model": settings.llm_model, "embed": settings.embed_model,
            **logging_store.stats()}


@app.get("/v1/models")
def list_models():
    return {
        "object": "list",
        "data": [{"id": settings.served_model_name, "object": "model",
                  "created": int(time.time()), "owned_by": "alatoo"}],
    }


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.post("/v1/chat/completions")
async def chat_completions(
    req: ChatRequest,
    authorization: Optional[str] = Header(None),
    x_session_id: Optional[str] = Header(None),
    x_client: Optional[str] = Header(None),
    x_consent: Optional[str] = Header(None),
):
    _check_auth(authorization)

    history = [{"role": m.role, "content": m.content} for m in req.messages]
    messages, chunks = build_messages(history)
    user_turns = [m for m in history if m.get("role") == "user"]
    last_user = user_turns[-1]["content"] if user_turns else ""

    session_id = x_session_id or f"auto-{uuid.uuid4().hex[:12]}"
    source = x_client or "openwebui"
    consent = x_consent == "1"
    sources = _sources_summary(chunks)

    cid = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    created = int(time.time())
    model_name = settings.served_model_name

    if req.stream:
        def gen():
            acc = []
            for token in chat_stream(messages, temperature=req.temperature):
                acc.append(token)
                yield _sse({
                    "id": cid, "object": "chat.completion.chunk", "created": created,
                    "model": model_name,
                    "choices": [{"index": 0, "delta": {"content": token}, "finish_reason": None}],
                })
            yield _sse({
                "id": cid, "object": "chat.completion.chunk", "created": created,
                "model": model_name,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            })
            yield "data: [DONE]\n\n"
            logging_store.log_turn(session_id, source, last_user, "".join(acc), sources, consent)

        return StreamingResponse(gen(), media_type="text/event-stream")

    answer = chat(messages, temperature=req.temperature)
    logging_store.log_turn(session_id, source, last_user, answer, sources, consent)
    return JSONResponse({
        "id": cid, "object": "chat.completion", "created": created, "model": model_name,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": answer},
                     "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    })


@app.get("/")
def index():
    page = STATIC_DIR / "index.html"
    if page.exists():
        return FileResponse(page)
    return JSONResponse({"detail": "public chat page not found"}, status_code=404)


# ---------------------------------------------------------------------------
# Protected conversation viewer (OpenWebUI-style, monochrome).
#   /admin/logs?token=...           -> single-page viewer
#   /admin/api/sessions?token=...   -> conversation list (JSON)
#   /admin/api/session?token=&id=   -> one conversation's turns (JSON)
# ---------------------------------------------------------------------------
def _admin_ok(token: str) -> None:
    if not settings.admin_token or token != settings.admin_token:
        raise HTTPException(status_code=401, detail="Unauthorized")


@app.get("/admin/api/sessions")
def admin_sessions(token: str = Query(default="")):
    _admin_ok(token)
    return {"sessions": logging_store.sessions(500), **logging_store.stats()}


@app.get("/admin/api/session")
def admin_session(token: str = Query(default=""), id: str = Query(default="")):
    _admin_ok(token)
    return {"messages": logging_store.session_messages(id)}


@app.get("/admin/logs", response_class=HTMLResponse)
def admin_logs(token: str = Query(default="")):
    _admin_ok(token)
    page = STATIC_DIR / "admin.html"
    if page.exists():
        return HTMLResponse(page.read_text(encoding="utf-8"))
    return HTMLResponse("<p>admin.html not found</p>", status_code=404)
