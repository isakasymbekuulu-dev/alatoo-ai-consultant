"""FastAPI backend: OpenAI-compatible RAG endpoint + public chat page + logging."""
import base64
import hashlib
import hmac
import json
import threading
import time
import uuid
from collections import defaultdict, deque
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, Form, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse, HTMLResponse, RedirectResponse
from pydantic import BaseModel

from app import channels, feedback, handoff, logging_store, riasec
from app.config import settings
from app.llm import chat, chat_stream
from app.rag import build_messages
from app.graph import run_graph, GRAPH_SPEC
from app.whatsapp import router as whatsapp_router

app = FastAPI(title="AlaToo AI Consultant")
logging_store.init()
handoff.init()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# WhatsApp Cloud API webhook (thin adapter to the same dialog backend)
app.include_router(whatsapp_router)

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
    name: Optional[str] = None
    token: Optional[str] = None   # opaque token from a WhatsApp test link -> wa session


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
        riasec_summary = riasec.summary_for_llm(result, name=stored.get("name"))

    history = [{"role": m.role, "content": m.content} for m in req.messages]
    _t_retr = time.time()
    messages, chunks, intent, trace = run_graph(history, riasec_summary=riasec_summary)
    retrieve_ms = int((time.time() - _t_retr) * 1000)
    user_turns = [m for m in history if m.get("role") == "user"]
    last_user = user_turns[-1]["content"] if user_turns else ""

    session_id = x_session_id or f"auto-{uuid.uuid4().hex[:12]}"
    source = x_client or "openwebui"
    consent = x_consent == "1"
    sources = _sources_summary(chunks)
    logging_store.save_trace(session_id, intent, last_user, trace, len(chunks))

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
            answer = "".join(acc)
            mid = logging_store.log_turn(session_id, source, last_user, answer, sources, consent)
            feedback.review_turn_async(mid, session_id, last_user, answer)

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"X-Retrieve-Ms": str(retrieve_ms)})

    answer = chat(messages, temperature=req.temperature)
    mid = logging_store.log_turn(session_id, source, last_user, answer, sources, consent)
    feedback.review_turn_async(mid, session_id, last_user, answer)
    return JSONResponse({
        "id": cid, "object": "chat.completion", "created": created, "model": model_name,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": answer},
                     "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }, headers={"X-Retrieve-Ms": str(retrieve_ms)})


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
    if req.token:                       # came from WhatsApp: save under the wa session
        wa_sid = logging_store.resolve_wa_token(req.token)
        if wa_sid:
            session_id = wa_sid
    name = (req.name or "").strip() or None
    logging_store.save_riasec(
        result_id, session_id, req.lang, result["code"],
        {"scores": result["scores"], "percents": result["percents"], "ranked": result["ranked"]},
        recs, req.consent, name=name,
    )
    logging_store.log_turn(
        session_id, "riasec-test",
        f"Пройден профориентационный тест RIASEC{(' — ' + name) if name else ''}",
        riasec.summary_for_llm(result, name=name), [], req.consent,
    )
    if session_id.startswith("wa-"):       # came from WhatsApp: push the result proactively
        try:
            from app import whatsapp
            whatsapp.push_riasec_result(session_id[3:], result, req.lang, name)
        except Exception:
            pass
    return {
        "result_id": result_id,
        "session_id": session_id,
        "name": name,
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
        "name": stored.get("name"),
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


# --- Admin auth: HMAC-signed session cookie (JWT-style) + back-compat ?token= ---
_ADMIN_COOKIE = "admin_session"
_ADMIN_TTL = 7 * 24 * 3600


def _b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _b64u_dec(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _sign_session(user: str) -> str:
    if not settings.admin_token:
        return ""
    payload = _b64u(json.dumps({"u": user, "exp": int(time.time()) + _ADMIN_TTL}).encode())
    sig = _b64u(hmac.new(settings.admin_token.encode(), payload.encode(), hashlib.sha256).digest())
    return payload + "." + sig


def _verify_session(cookie: str) -> bool:
    if not cookie or not settings.admin_token or "." not in cookie:
        return False
    payload, sig = cookie.split(".", 1)
    expected = _b64u(hmac.new(settings.admin_token.encode(), payload.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        return False
    try:
        data = json.loads(_b64u_dec(payload))
    except Exception:
        return False
    return int(data.get("exp", 0)) > int(time.time())


def _authed(request: Request) -> bool:
    tok = request.query_params.get("token", "")
    if settings.admin_token and tok == settings.admin_token:   # back-compat token link
        return True
    return _verify_session(request.cookies.get(_ADMIN_COOKIE, ""))


def admin_guard(request: Request) -> None:
    if not _authed(request):
        raise HTTPException(status_code=401, detail="Unauthorized")


_LOGIN_HTML = """<!DOCTYPE html><html lang=ru><head><meta charset=UTF-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Вход - Админка</title><style>
body{font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;background:#0d0d0d;color:#ececec;display:grid;place-items:center;height:100vh;margin:0}
form{background:#171717;border:1px solid #2b2b2b;border-radius:14px;padding:26px;width:300px;display:flex;flex-direction:column;gap:12px}
h1{font-size:17px;margin:0 0 6px}
input{background:#1e1e1e;border:1px solid #2b2b2b;border-radius:9px;padding:11px;color:#ececec;font-size:14px}
button{background:#ececec;color:#111;border:0;border-radius:9px;padding:11px;font-size:14px;font-weight:600;cursor:pointer}
.err{color:#e57373;font-size:12.5px;min-height:14px}</style></head><body>
<form method=post action=/admin/login>
<h1>Вход в панель логов</h1>
<div class=err>%ERR%</div>
<input name=user placeholder="Логин" autocomplete=username autofocus>
<input name=password type=password placeholder="Пароль" autocomplete=current-password>
<button type=submit>Войти</button>
</form></body></html>"""


@app.get("/admin", response_class=HTMLResponse)
def admin_login_page(request: Request):
    if _authed(request):
        return RedirectResponse("/admin/logs", status_code=302)
    return HTMLResponse(_LOGIN_HTML.replace("%ERR%", ""))


@app.post("/admin/login")
def admin_login(user: str = Form(default=""), password: str = Form(default="")):
    if (settings.admin_password and user == settings.admin_user
            and password == settings.admin_password):
        resp = RedirectResponse("/admin/logs", status_code=302)
        resp.set_cookie(_ADMIN_COOKIE, _sign_session(user), max_age=_ADMIN_TTL,
                        httponly=True, samesite="lax", path="/admin")
        return resp
    return HTMLResponse(_LOGIN_HTML.replace("%ERR%", "Неверный логин или пароль"), status_code=401)


@app.get("/admin/logout")
def admin_logout():
    resp = RedirectResponse("/admin", status_code=302)
    resp.delete_cookie(_ADMIN_COOKIE, path="/admin")
    return resp


@app.get("/admin/api/sessions")
def admin_sessions(request: Request):
    admin_guard(request)
    st = logging_store.stats()
    return {"sessions": logging_store.sessions(500),
            "total_sessions": st["sessions"], "total_messages": st["messages"]}


@app.get("/admin/api/session")
def admin_session(request: Request, id: str = Query(default=""), problems_only: int = Query(default=0)):
    admin_guard(request)
    if problems_only:
        return {"messages": logging_store.session_problems(id)}
    return {"messages": logging_store.session_messages(id)}


@app.get("/admin/api/riasec")
def admin_riasec(request: Request, id: str = Query(default="")):
    admin_guard(request)
    stored = logging_store.get_riasec(id) if id else None
    if id and not stored:
        raise HTTPException(status_code=404, detail="result not found")
    return {"result": stored}


@app.get("/admin/logs", response_class=HTMLResponse)
def admin_logs(request: Request):
    if not _authed(request):
        return RedirectResponse("/admin", status_code=302)
    page = STATIC_DIR / "admin.html"
    if page.exists():
        return HTMLResponse(page.read_text(encoding="utf-8"))
    return HTMLResponse("<p>admin.html not found</p>", status_code=404)


@app.get("/admin/api/graph")
def admin_graph(request: Request):
    admin_guard(request)
    return GRAPH_SPEC


@app.get("/admin/api/traces")
def admin_traces(request: Request, session_id: str = Query(default="")):
    admin_guard(request)
    if session_id:
        return {"traces": logging_store.traces_for_session(session_id)}
    return {"traces": logging_store.recent_traces()}


@app.get("/admin/api/analytics")
def admin_analytics(request: Request):
    admin_guard(request)
    return logging_store.analytics()


@app.get("/admin/api/problems")
def admin_problems(request: Request):
    admin_guard(request)
    return {"problems": logging_store.problems(300)}


@app.get("/admin/api/problem_sessions")
def admin_problem_sessions(request: Request):
    admin_guard(request)
    return {"sessions": logging_store.problem_sessions(500)}


@app.post("/admin/api/flag")
def admin_flag(request: Request, id: int = Query(...), flagged: int = Query(default=1)):
    admin_guard(request)
    logging_store.set_flag(id, bool(flagged))
    return {"ok": True}


class OperatorSend(BaseModel):
    id: str
    text: str


@app.get("/admin/api/operator/queue")
def admin_op_queue(request: Request):
    admin_guard(request)
    return {"queue": handoff.queue(200), "counts": handoff.counts()}


@app.get("/admin/api/operator/conversation")
def admin_op_conversation(request: Request, id: str = Query(default="")):
    admin_guard(request)
    return {"conversation": handoff.get(id), "messages": logging_store.session_messages(id)}


@app.post("/admin/api/operator/take")
def admin_op_take(request: Request, id: str = Query(...), operator: str = Query(default="")):
    admin_guard(request)
    handoff.take_over(id, operator)
    return {"ok": True, "conversation": handoff.get(id)}


@app.post("/admin/api/operator/release")
def admin_op_release(request: Request, id: str = Query(...)):
    admin_guard(request)
    handoff.release_to_bot(id)
    return {"ok": True, "conversation": handoff.get(id)}


@app.post("/admin/api/operator/send")
def admin_op_send(request: Request, body: OperatorSend):
    admin_guard(request)
    sid = (body.id or "").strip()
    text = (body.text or "").strip()
    if not sid or not text:
        raise HTTPException(status_code=422, detail="id and text required")
    conv = handoff.get(sid)
    if not conv or conv.get("mode") != "human":
        handoff.take_over(sid, "operator")   # operator reply implies takeover
    ok = channels.send_to_session(sid, text)
    logging_store.log_turn(sid, channels.channel_of(sid) + ":operator", "", text, [], False)
    return {"ok": ok}


@app.post("/admin/api/operator/handled")
def admin_op_handled(request: Request, id: str = Query(...), handled: int = Query(default=1)):
    admin_guard(request)
    handoff.mark_handled(id, bool(handled))
    return {"ok": True}


@app.post("/admin/api/operator/priority")
def admin_op_priority(request: Request, id: str = Query(...), priority: int = Query(default=0)):
    admin_guard(request)
    handoff.set_priority(id, priority)
    return {"ok": True}


@app.post("/admin/api/operator/flag")
def admin_op_flag(request: Request, id: str = Query(...), reason: str = Query(default=""), priority: int = Query(default=1)):
    admin_guard(request)
    handoff.flag(id, reason=reason, priority=priority, auto=False)
    return {"ok": True}


@app.get("/admin/operator", response_class=HTMLResponse)
def admin_operator_page(request: Request):
    if not _authed(request):
        return RedirectResponse("/admin", status_code=302)
    page = STATIC_DIR / "operator.html"
    if page.exists():
        return HTMLResponse(page.read_text(encoding="utf-8"))
    return HTMLResponse("<p>operator.html not found</p>", status_code=404)


@app.get("/admin/graph", response_class=HTMLResponse)
def admin_graph_page(request: Request):
    if not _authed(request):
        return RedirectResponse("/admin", status_code=302)
    page = STATIC_DIR / "graph.html"
    if page.exists():
        return HTMLResponse(page.read_text(encoding="utf-8"))
    return HTMLResponse("<p>graph.html not found</p>", status_code=404)
