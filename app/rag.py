"""RAG core: retrieve context from Qdrant and build the prompt."""
from typing import Dict, List, Optional, Tuple

from app.config import settings
from app.embeddings import embed_query
from app.qdrant_store import get_client, search

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


def retrieve(query: str) -> List[dict]:
    client = get_client()
    qvec = embed_query(query)
    hits = search(
        client,
        query_vector=qvec,
        top_k=settings.top_k,
        score_threshold=settings.score_threshold,
    )
    results = []
    for h in hits:
        payload = h.payload or {}
        results.append(
            {
                "score": h.score,
                "text": payload.get("text", ""),
                "title": payload.get("title", ""),
                "source": payload.get("source", ""),
                "source_url": payload.get("source_url", ""),
            }
        )
    return results


def build_context(chunks: List[dict]) -> str:
    blocks, total = [], 0
    for i, c in enumerate(chunks, 1):
        label = c.get("title") or c.get("source") or f"фрагмент {i}"
        block = f"[{i}] {label}\n{c['text']}"
        if total + len(block) > settings.max_context_chars:
            break
        blocks.append(block)
        total += len(block)
    return "\n\n---\n\n".join(blocks)


def build_messages(
    history: List[Dict[str, str]],
    riasec_summary: Optional[str] = None,
) -> Tuple[List[Dict[str, str]], List[dict]]:
    """Take incoming chat history, retrieve for the latest user turn, and
    return messages ready for the LLM plus the retrieved chunks."""
    user_turns = [m for m in history if m.get("role") == "user"]
    query = user_turns[-1]["content"] if user_turns else ""
    chunks = retrieve(query)
    context = build_context(chunks) if chunks else "(контекст не найден)"

    # Keep a short tail of the conversation for follow-up coherence.
    convo = [m for m in history if m.get("role") in ("user", "assistant")][-6:]

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if riasec_summary:
        messages.append(
            {
                "role": "system",
                "content": f"РЕЗУЛЬТАТЫ ТЕСТА RIASEC этого пользователя:\n\n{riasec_summary}",
            }
        )
    messages.append(
        {
            "role": "system",
            "content": f"КОНТЕКСТ (выдержки из базы знаний вуза):\n\n{context}",
        }
    )
    messages.extend(convo)
    return messages, chunks
