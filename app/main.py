"""FastAPI backend: OpenAI-compatible RAG endpoint + public chat page + logging."""
import json
import threading
import time
import uuid
from collections import defaultdict, deque
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse, HTMLResponse
from pydantic import BaseModel

from app import logging_store, riasec
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


class RiasecSubmit(BaseModel):
    answers: dict
    lang: str = "ru"
    chat_id: Optional[str] = None
    consent: bool = False


def _check_auth(authorization: Optional[str]) -> None:
    if not settings.backend_api_key:
        return
    if authorization != f"Bearer {settings.backend_api_key}":
        raise HTTPException(status_code=401, detail="Invalid API key")


_rl_lock = threading.Lock()
_rl_hits: dict = defaultdict(deque)


def _client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _rate_ok(ip: str) -> bool:
    now = time.time()
    with _rl_lock:
        dq = _rl_hits[ip]
        while dq and now - dq[0] > 60:
            dq.popleft()
        if len(dq) >= settings.rate_limit_per_min:
            return False
        dq.append(now)
        return True


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
    request: Request,
    authorization: Optional[str] = Header(None),
    x_session_id: Optional[str] = Header(None),
    x_client: Optional[str] = Header(None),
    x_consent: Optional[str] = Header(None),
    x_riasec_id: Optional[str] = Header(None),
):
    _check_auth(authorization)

    if x_client == "public" and not _rate_ok(_client_ip(request)):
        raise HTTPException(status_code=429,
                            detail="Слишком много запросов. Подождите минуту и попробуйте снова.")

    riasec_summary = None
    stored = None
    if x_riasec_id:
        stored = logging_store.get_riasec(x_riasec_id)
    if stored is None and x_session_id:
        stored = logging_store.riasec_for_session(x_session_id)
    if stored:
        result = {
            "code": stored["code"],
            "scores": stored["scores"]["scores"],
            "percents": stored["scores"]["percents"],
            "ranked": stored["scores"]["ranked"],
            "recommendations": stored["recs"],
        }
        riasec_summary = riasec.summary_for_llm(result)

    history = [{"role": m.role, "content": m.content} for m in req.messages]
    messages, chunks = build_messages(history, riasec_summary=riasec_summary)
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


@app.get("/test")
def test_page():
    page = STATIC_DIR / "test.html"
    if page.exists():
        return FileResponse(page)
    return JSONResponse({"detail": "test page not found"}, status_code=404)


@app.get("/riasec/api/questions")
def riasec_questions(lang: str = Query(default="ru")):
    return {"lang": lang, "scale": [1, 5], "questions": riasec.questions(lang)}


@app.post("/riasec/api/submit")
def riasec_submit(req: RiasecSubmit, request: Request):
    if not _rate_ok(_client_ip(request)):
        raise HTTPException(status_code=429, detail="Слишком много запросов.")
    try:
        result = riasec.score({k: int(v) for k, v in req.answers.items()})
    except (ValueError, TypeError) as e:
        raise HTTPException(status_code=422, detail=str(e))

    recs = riasec.recommend(result["scores"], lang=req.lang)
    result["recommendations"] = recs

    result_id = riasec.new_result_id()
    session_id = req.chat_id or f"riasec-{result_id}"
    logging_store.save_riasec(
        result_id, session_id, req.lang, result["code"],
        {"scores": result["scores"], "percents": result["percents"], "ranked": result["ranked"]},
        recs, req.consent,
    )
    logging_store.log_turn(
        session_id, "riasec-test",
        "Пройден профориентационный тест RIASEC",
        riasec.summary_for_llm(result), [], req.consent,
    )
    return {
        "result_id": result_id,
        "session_id": session_id,
        "code": result["code"],
        "scores": result["scores"],
        "percents": result["percents"],
        "ranked": result["ranked"],
        "types": {t: riasec.TYPES[t][req.lang if req.lang in ("ru", "ky", "en") else "ru"]
                  for t in riasec.RIASEC_ORDER},
        "recommendations": recs,
    }


@app.get("/riasec/api/result")
def riasec_result(id: str = Query(default=""), lang: str = Query(default="ru")):
    stored = logging_store.get_riasec(id)
    if not stored:
        raise HTTPException(status_code=404, detail="result not found")
    lang = lang if lang in ("ru", "ky", "en") else "ru"
    return {
        "result_id": stored["id"],
        "session_id": stored["session_id"],
        "code": stored["code"],
        "scores": stored["scores"]["scores"],
        "percents": stored["scores"]["percents"],
        "ranked": stored["scores"]["ranked"],
        "types": {t: riasec.TYPES[t][lang] for t in riasec.RIASEC_ORDER},
        "recommendations": stored["recs"],
    }


@app.get("/")
def index():
    page = STATIC_DIR / "index.html"
    if page.exists():
        return FileResponse(page)
    return JSONResponse({"detail": "public chat page not found"}, status_code=404)


@app.get("/logo.png")
def logo():
    p = STATIC_DIR / "logo.png"
    if p.exists():
        return FileResponse(p, media_type="image/png")
    raise HTTPException(status_code=404, detail="logo not found")


def _admin_ok(token: str) -> None:
    if not settings.admin_token or token != settings.admin_token:
        raise HTTPException(status_code=401, detail="Unauthorized")


@app.get("/admin/api/sessions")
def admin_sessions(token: str = Query(default="")):
    _admin_ok(token)
    st = logging_store.stats()
    return {"sessions": logging_store.sessions(500),
            "total_sessions": st["sessions"], "total_messages": st["messages"]}


@app.get("/admin/api/session")
def admin_session(token: str = Query(default=""), id: str = Query(default="")):
    _admin_ok(token)
    return {"messages": logging_store.session_messages(id)}


@app.get("/admin/api/riasec")
def admin_riasec(token: str = Query(default=""), id: str = Query(default="")):
    _admin_ok(token)
    stored = logging_store.get_riasec(id) if id else None
    if id and not stored:
        raise HTTPException(status_code=404, detail="result not found")
    return {"result": stored}


@app.get("/admin/logs", response_class=HTMLResponse)
def admin_logs(token: str = Query(default="")):
    _admin_ok(token)
    page = STATIC_DIR / "admin.html"
    if page.exists():
        return HTMLResponse(page.read_text(encoding="utf-8"))
    return HTMLResponse("<p>admin.html not found</p>", status_code=404)
