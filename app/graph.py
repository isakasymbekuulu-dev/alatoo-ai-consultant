"""LangGraph dialog orchestration.

A single compiled StateGraph routes each user turn:

    START -> router -> { rag | riasec | general } -> END

The graph only *assembles* the prompt (intent + retrieval + RIASEC profile)
and records a trace of the path it took. The final token-by-token LLM
streaming stays in the API layer (app/main.py), so streaming is preserved.

LangChain is used separately in the ingestion pipeline
(ingestion/ingest.py: RecursiveCharacterTextSplitter).
"""
from typing import List, Dict, Optional, TypedDict
import re

from langgraph.graph import StateGraph, START, END

from app.rag import build_messages, SYSTEM_PROMPT
from app.lang import answer_directive, detect_lang

_GREETING = re.compile(
    r"^(привет|здравствуй|здрасьте|салам|саламатсыз|ассалам|hello|hi|hey|"
    r"рахмат|спасибо|thanks|thank you|пока|до свидания|bye)\b",
    re.I,
)
_RIASEC_HINT = re.compile(
    r"(тест|riasec|риасек|профил|результат|кем мне|кем стать|куда поступать|"
    r"какое направлени|какую профессию|подходит мне|менин жыйынтыг|кесип)",
    re.I,
)


class GState(TypedDict, total=False):
    history: List[Dict[str, str]]
    riasec_summary: Optional[str]
    query: str
    intent: str
    messages: List[Dict[str, str]]
    chunks: List[dict]
    trace: List[str]


def _last_user(history) -> str:
    ut = [m for m in (history or []) if m.get("role") == "user"]
    return ut[-1]["content"] if ut else ""


def router_node(state: GState) -> GState:
    q = _last_user(state.get("history"))
    state["query"] = q
    ql = (q or "").strip()
    trace = state.get("trace") or []
    if not ql or (_GREETING.search(ql) and len(ql) < 40):
        intent = "general"
    elif state.get("riasec_summary") and _RIASEC_HINT.search(ql):
        intent = "riasec"
    else:
        intent = "rag"
    state["intent"] = intent
    trace.append(f"router → {intent}")
    state["trace"] = trace
    return state


def rag_node(state: GState) -> GState:
    messages, chunks = build_messages(state.get("history"), riasec_summary=state.get("riasec_summary"))
    state["messages"] = messages
    state["chunks"] = chunks
    state.setdefault("trace", []).append(f"rag: найдено фрагментов — {len(chunks)}")
    return state


def riasec_node(state: GState) -> GState:
    # profile-aware answer; build_messages already injects the RIASEC summary
    messages, chunks = build_messages(state.get("history"), riasec_summary=state.get("riasec_summary"))
    state["messages"] = messages
    state["chunks"] = chunks
    state.setdefault("trace", []).append(f"riasec: с учётом профиля, фрагментов — {len(chunks)}")
    return state


def general_node(state: GState) -> GState:
    convo = [m for m in (state.get("history") or []) if m.get("role") in ("user", "assistant")][-6:]
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if state.get("riasec_summary"):
        messages.append({
            "role": "system",
            "content": f"РЕЗУЛЬТАТЫ ТЕСТА RIASEC этого пользователя:\n\n{state['riasec_summary']}",
        })
    messages.extend(convo)
    # Reply in the user's language even for greetings/smalltalk.
    messages.append({"role": "system",
                     "content": answer_directive(detect_lang(_last_user(state.get("history"))))})
    state["messages"] = messages
    state["chunks"] = []
    state.setdefault("trace", []).append("general: без поиска по базе")
    return state


def _route(state: GState) -> str:
    return state.get("intent", "rag")


def _build():
    g = StateGraph(GState)
    g.add_node("router", router_node)
    g.add_node("rag", rag_node)
    g.add_node("riasec", riasec_node)
    g.add_node("general", general_node)
    g.add_edge(START, "router")
    g.add_conditional_edges("router", _route,
                            {"rag": "rag", "riasec": "riasec", "general": "general"})
    g.add_edge("rag", END)
    g.add_edge("riasec", END)
    g.add_edge("general", END)
    return g.compile()


GRAPH = _build()

# Static description for the admin graph visualization.
GRAPH_SPEC = {
    "nodes": [
        {"id": "router",  "label": "Роутер намерения", "desc": "Классифицирует запрос: general / rag / riasec"},
        {"id": "rag",     "label": "RAG-консультация", "desc": "Поиск в Qdrant + ответ по базе знаний вуза"},
        {"id": "riasec",  "label": "RIASEC-ветка",     "desc": "Ответ с учётом профиля профориентации"},
        {"id": "general", "label": "Общий узел",       "desc": "Приветствия и смолток без поиска"},
    ],
    "edges": [
        {"from": "START",  "to": "router",  "cond": ""},
        {"from": "router", "to": "rag",     "cond": "intent=rag"},
        {"from": "router", "to": "riasec",  "cond": "intent=riasec"},
        {"from": "router", "to": "general", "cond": "intent=general"},
        {"from": "rag",     "to": "END", "cond": ""},
        {"from": "riasec",  "to": "END", "cond": ""},
        {"from": "general", "to": "END", "cond": ""},
    ],
}


def run_graph(history, riasec_summary=None):
    """Run the dialog graph. Returns (messages, chunks, intent, trace)."""
    state = GRAPH.invoke({
        "history": history or [],
        "riasec_summary": riasec_summary,
        "trace": [],
    })
    return (state["messages"], state.get("chunks", []),
            state.get("intent", "rag"), state.get("trace", []))
