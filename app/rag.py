"""RAG core: retrieve context from Qdrant (hybrid + rerank) and build the prompt.

Cross-lingual: the KB is essentially Russian. We translate the *search query*
to Russian (app.lang.search_query) so Kyrgyz/English questions still match, but
we force the *answer* into the user's own language (app.lang.answer_directive).
"""
from typing import Dict, List, Optional, Tuple

from app.config import settings
from app.lang import answer_directive, detect_lang, search_query
from app.qdrant_store import get_vector_store

# Official admissions contacts — a stable fact, always available to the model so
# it never deflects to the приёмная комиссия without telling people how to reach it.
ADMISSIONS_CONTACT = (
    "ОФИЦИАЛЬНЫЕ КОНТАКТЫ ПРИЁМНОЙ КОМИССИИ (используй именно их):\n"
    "- Телефон / WhatsApp: 555 820 000\n"
    "- E-mail: admission@alatoo.edu.kg\n"
    "- Адрес: ул. Анкара 1/8, блок А, кабинет 107\n"
    "- Часы работы: 9:00–17:00"
)

SYSTEM_PROMPT = """Ты — официальный AI-консультант Ала-Тоо Университета (Ala-Too University).
Ты помогаешь абитуриентам и студентам: рассказываешь о программах, факультетах, поступлении,
стоимости, документах, общежитии и отвечаешь на частые вопросы.

Правила:
- Отвечай ТОЛЬКО на основе предоставленного КОНТЕКСТА ниже. Не выдумывай факты, цифры и даты.
- Если в КОНТЕКСТЕ есть ответ — дай его сразу, полно и по делу. В этом случае НЕ отправляй
  человека в приёмную комиссию и НЕ добавляй её контакты: ты уже ответил на вопрос.
- НЕ УГАДЫВАЙ при неоднозначном вопросе. Если человек спрашивает про стоимость, сроки, документы,
  сроки приёма или направления, но НЕ указал ступень (бакалавриат / магистратура / аспирантура /
  IT & Business колледж) или конкретную программу — не подставляй наугад первую попавшуюся ступень.
  Сначала задай ОДИН короткий уточняющий вопрос, какую ступень или программу он имеет в виду, и
  только после его ответа давай точные данные.
- Контакты приёмной комиссии (см. блок контактов) давай ТОЛЬКО когда они действительно нужны:
  (а) если в КОНТЕКСТЕ нет ответа на вопрос; либо
  (б) если вопрос индивидуальный или требует живого общения (статус документов, оплата,
  индивидуальные скидки, жалобы, спорные случаи).
  Никогда не пиши «обратитесь в приёмную комиссию» без самих контактов и не выдумывай другие контакты.
- Отвечай на ЯЗЫКЕ ПОЛЬЗОВАТЕЛЯ (см. отдельную пометку «ЯЗЫК ОТВЕТА» в конце). Даже если
  контекст на русском, переведи нужные сведения на язык пользователя.
- Пиши кратко, дружелюбно и по делу. Где уместно — структурируй ответ.

Источники (обязательная часть ответа):
- Фрагменты КОНТЕКСТА могут содержать пометку «| URL: …». Если хотя бы один фрагмент, который ты
  использовал в ответе, имеет такую пометку, ты ОБЯЗАН закончить ответ отдельной строкой
  «Источники:» и перечислить эти источники кликабельными markdown-ссылками формата [название](URL),
  по одной на каждый использованный источник, без повторов. Не пропускай этот блок.
- Бери URL только из пометки «URL:» соответствующего фрагмента. Никогда не выдумывай и не угадывай
  URL. Если ни у одного использованного фрагмента нет пометки «URL:» — строку «Источники:» не добавляй.

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
    threshold is applied. Optional ``lang`` filters by metadata.lang (off by
    default — the KB is Russian, so filtering would hurt cross-lingual queries).
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
        url = (c.get("source_url") or "").strip()
        header = "[%d] %s" % (i, label)
        if url:                                   # expose URL so the model can cite it
            header += " | URL: %s" % url
        block = "%s\n%s" % (header, c["text"])
        if total + len(block) > settings.max_context_chars:
            break
        blocks.append(block)
        total += len(block)
    return "\n\n---\n\n".join(blocks)


def build_messages(
    history: List[Dict[str, str]],
    riasec_summary: Optional[str] = None,
) -> Tuple[List[Dict[str, str]], List[dict]]:
    """Retrieve for the latest user turn and return LLM messages + chunks.

    The query is translated to Russian for retrieval (KB is Russian); the answer
    language is forced to the user's language via a trailing system directive.
    """
    user_turns = [m for m in history if m.get("role") == "user"]
    query = user_turns[-1]["content"] if user_turns else ""
    lang = detect_lang(query)
    sq = search_query(query, lang)         # Russian-leaning search string
    chunks = retrieve(sq)
    context = build_context(chunks) if chunks else "(контекст не найден)"

    convo = [m for m in history if m.get("role") in ("user", "assistant")][-6:]

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.append({"role": "system", "content": ADMISSIONS_CONTACT})
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
    # Language directive LAST so it dominates the (Russian) context.
    messages.append({"role": "system", "content": answer_directive(lang)})
    return messages, chunks
