"""RAG core: retrieve context from Qdrant (hybrid + rerank) and build the prompt."""
from typing import Dict, List, Optional, Tuple

from app.config import settings
from app.qdrant_store import get_vector_store

SYSTEM_PROMPT = """Ты — официальный AI-консультант Ала-Тоо Университета (Ala-Too University).
Ты помогаешь абитуриентам и студентам: рассказываешь о программах, факультетах, поступлении,
стоимости, документах, общежитии и отвечаешь на частые вопросы.

Правила:
- Отвечай ТОЛЬКО на основе предоставленного КОНТЕКСТА ниже. Не выдумывай факты, цифры и даты.
- Если в контексте нет ответа — честно скажи, что точной информации нет, и предложи обратиться
  в приёмную комиссию. Не придумывай контакты, если их нет в контексте.
- Отвечай на том языке, на котором задан вопрос (кыргызский, русский или английский).
- Пиши кратко, дружелюбно и по делу. Где уместно — структурируй ответ.
- В конце ответа, если использовал источники, добавь строку "Источники:" с их названиями.

Профориентационный тест:
- В вузе есть онлайн-тест профориентации RIASEC (методика Голланда, адаптация
  O*NET Interest Profiler): 60 вопросов, ~7 минут, результат — профиль интересов
  и подходящие программы Ала-Тоо.
- Если пользователь не знает, какое направление выбрать, сомневается между
  программами или спрашивает «куда мне поступать», предложи пройти тест и дай
  ссылку в формате: [Пройти тест профориентации](/test).
- Если ниже есть блок «РЕЗУЛЬТАТЫ ТЕСТА RIASEC» — пользователь уже прошёл тест.
  Опирайся на его профиль: объясняй типы простыми словами, связывай рекомендации
  с программами вуза из КОНТЕКСТА, отвечай на вопросы о результатах. Повторно
  тест в этом случае не предлагай.
"""


def retrieve(query: str, lang: Optional[str] = None) -> List[dict]:
    """Hybrid (dense BGE-M3 + sparse BM25) retrieval, then optional cross-encoder
    rerank for precision. Hybrid scores are RRF-fused (not cosine), so no cosine
    threshold is applied. Optional ``lang`` filters by metadata.lang.
    """
    vs = get_vector_store()
    flt = None
    if lang:
        from qdrant_client.http import models as qm
        flt = qm.Filter(must=[qm.FieldCondition(
            key="metadata.lang", match=qm.MatchValue(value=lang))])

    fetch_k = settings.rerank_fetch_k if settings.rerank_enabled else settings.top_k
    hits = vs.similarity_search_with_score(query, k=fetch_k, filter=flt)
    results = []
    for doc, score in hits:
        md = doc.metadata or {}
        results.append(
            {
                "score": float(score),
                "text": doc.page_content,
                "title": md.get("title") or md.get("section") or "",
                "source": md.get("source", ""),
                "source_url": md.get("source_url", ""),
                "faculty": md.get("faculty", ""),
                "program": md.get("program", ""),
            }
        )

    if settings.rerank_enabled and results:
        try:
            from app.rerank import rerank
            results = rerank(query, results, settings.top_k)
        except Exception:
            results = results[:settings.top_k]  # graceful fallback to hybrid order
    else:
        results = results[:settings.top_k]
    return results


def build_context(chunks: List[dict]) -> str:
    blocks, total = [], 0
    for i, c in enumerate(chunks, 1):
        label = c.get("title") or c.get("source") or ("фрагмент %d" % i)
        block = "[%d] %s\n%s" % (i, label, c["text"])
        if total + len(block) > settings.max_context_chars:
            break
        blocks.append(block)
        total += len(block)
    return "\n\n---\n\n".join(blocks)


def build_messages(
    history: List[Dict[str, str]],
    riasec_summary: Optional[str] = None,
) -> Tuple[List[Dict[str, str]], List[dict]]:
    """Retrieve for the latest user turn and return LLM messages + chunks."""
    user_turns = [m for m in history if m.get("role") == "user"]
    query = user_turns[-1]["content"] if user_turns else ""
    chunks = retrieve(query)
    context = build_context(chunks) if chunks else "(контекст не найден)"

    convo = [m for m in history if m.get("role") in ("user", "assistant")][-6:]

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if riasec_summary:
        messages.append({
            "role": "system",
            "content": "РЕЗУЛЬТАТЫ ТЕСТА RIASEC этого пользователя:\n\n" + riasec_summary,
        })
    messages.append({
        "role": "system",
        "content": "КОНТЕКСТ (выдержки из базы знаний вуза):\n\n" + context,
    })
    messages.extend(convo)
    return messages, chunks
