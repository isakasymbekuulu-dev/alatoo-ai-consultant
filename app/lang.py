"""Language handling for the consultant: detect the user's language, force the
answer language, and translate/expand the *search query* into Russian.

Why: the knowledge base is essentially Russian-only. A Kyrgyz or English query
(e.g. "женилдетүүлөр барбы?") embeds far from the Russian text and shares no
lexical tokens for BM25, so hybrid retrieval misses. We therefore search in
Russian (translate the query) but still answer in the user's own language.
"""
import logging
import re
from functools import lru_cache

log = logging.getLogger("alatoo.lang")

# Kyrgyz often uses plain Cyrillic, so letter-only detection is not enough.
# Stems (no trailing word-boundary) so suffixed forms also match, e.g.
# "женилдет" catches "женилдетүүлөр" / "женилдетуулор".
# Full distinctive Kyrgyz words (both word boundaries → no false hits on Russian
# words that merely start with these letters, e.g. "булка"/"болото"/"сено").
_KY_WORDS = re.compile(
    r"\b(кандай|канча|кайсы|кайда|кайдан|качан|эмне|эмнеге|болобу|болбойт|болот|"
    r"керек|керекпи|үчүн|жөнүндө|тууралуу|жана|жок|ооба|рахмат|мүмкүн|"
    r"силер|сиздер|менин|сиздин|биздин|кыргызча|кыргыз|менен|аркылуу|экен|ушул|"
    r"абдан|аябай|жакшы|жаман|баасы|акча|акысы|жатакана|барбы|келеби|бекен|"
    r"саламатсызбы|саламатсыз|кантип|кантем|сурайм|сурагым|каалайм|билем|билгим|"
    r"келет|жатам|жатат|окуу акысы)\b",
    re.I,
)
# Kyrgyz stems (leading boundary only → catch suffixed forms; chosen so they are
# not prefixes of common Russian words).
_KY_STEMS = re.compile(
    r"\b(женилдет|жеңилдет|женилдик|жеңилдик|тапшыр|кабыл алуу|окуй|окуу|сура|каала)",
    re.I,
)
_KY_LETTERS = re.compile(r"[ңүөҢҮӨ]")
_CYR = re.compile(r"[а-яёА-ЯЁ]")
_LAT = re.compile(r"[a-zA-Z]")


def detect_lang(text: str) -> str:
    """Return 'ru' | 'ky' | 'en' for a user message (best-effort, fast)."""
    s = (text or "").strip()
    if not s:
        return "ru"
    sample = s[:600]
    cyr = len(_CYR.findall(sample))
    lat = len(_LAT.findall(sample))
    if _KY_LETTERS.search(sample) or _KY_WORDS.search(sample) or _KY_STEMS.search(sample):
        return "ky"
    if cyr >= lat:
        return "ru"
    if lat > 0:
        return "en"
    return "ru"


# Directive injected as the LAST system message so it dominates the (Russian)
# context. gpt-4o-mini otherwise drifts to the language of the retrieved text.
_DIRECTIVE = {
    "ru": "ЯЗЫК ОТВЕТА: русский. Отвечай на русском языке.",
    "ky": ("ЖООП ТИЛИ: кыргызча. Колдонуучу кыргыз тилинде жазып жатат — "
           "ТОЛУГУ МЕНЕН кыргыз тилинде жооп бер. Контекст орусча болсо да, "
           "керектүү маалыматты которуп, кыргызча жаз. Орус тилине өтпө."),
    "en": ("ANSWER LANGUAGE: English. The user is writing in English — reply "
           "fully in English. Even if the context is in Russian, translate the "
           "relevant facts and answer in English. Do not switch to Russian."),
}


def answer_directive(lang: str) -> str:
    return _DIRECTIVE.get(lang, _DIRECTIVE["ru"])


# ky/en -> ru glossary for instant query expansion (no LLM latency). Maps the
# high-value admissions terms that cross-lingual embeddings tend to miss.
_GLOSSARY = {
    # discounts / benefits
    "женилдетуу": "скидки льготы", "жеңилдетүү": "скидки льготы",
    "женилдетуулор": "скидки льготы", "жеңилдетүүлөр": "скидки льготы",
    "женилдик": "скидки льготы", "жеңилдик": "скидки льготы",
    "жеңилдиктер": "скидки льготы", "discount": "скидки льготы",
    "discounts": "скидки льготы", "scholarship": "скидка грант стипендия",
    # tuition / price
    "окуу акысы": "стоимость обучения цена", "акысы": "стоимость цена",
    "канча турат": "стоимость цена сколько стоит", "баасы": "стоимость цена",
    "tuition": "стоимость обучения цена", "price": "стоимость цена",
    "fee": "стоимость оплата", "cost": "стоимость цена",
    # admission
    "тапшыруу": "поступление приём", "кабыл алуу": "поступление приём",
    "admission": "поступление приём", "apply": "поступление подать заявку",
    "документтер": "документы", "documents": "документы",
    # study / programs
    "программа": "программа направление", "багыт": "направление программа",
    "факультет": "факультет", "faculty": "факультет",
    "адистик": "специальность направление", "кесип": "профессия специальность",
    "major": "направление специальность", "program": "программа направление",
    # exam
    "орт": "ОРТ проходной балл", "балл": "балл проходной",
    # dormitory / contacts
    "жатакана": "общежитие", "dormitory": "общежитие",
    "байланыш": "контакты телефон", "contact": "контакты телефон",
    "общежитие": "общежитие",
}


def _glossary_expand(query: str) -> str:
    ql = (query or "").lower()
    extra = []
    for term, ru in _GLOSSARY.items():
        if term in ql:
            extra.extend(ru.split())
    seen, out = set(), []
    for w in extra:
        if w not in seen:
            seen.add(w)
            out.append(w)
    return " ".join(out)


def _llm_translate_to_ru(query: str) -> str:
    """One short LLM call to translate the search query to Russian. Best-effort;
    on any error returns "" and the caller falls back to glossary-only."""
    try:
        from app.llm import chat
        msg = [
            {"role": "system", "content":
                "Translate the user's search query to Russian. Output ONLY the "
                "Russian translation, no quotes, no explanation. Keep proper "
                "names. If it is already Russian, repeat it unchanged."},
            {"role": "user", "content": query[:300]},
        ]
        out = chat(msg, temperature=0.0)
        out = (out or "").strip().strip('"').strip()
        if out and len(out) <= 300:
            return out
    except Exception as e:  # noqa: BLE001
        log.warning("query translate failed: %s", str(e)[:160])
    return ""


@lru_cache(maxsize=512)
def search_query(query: str, lang: str) -> str:
    """Build the Russian-leaning search string. Glossary expansion is applied
    in ALL languages (harmless for Russian, and catches mis-detected Kyrgyz
    terms like a bare "женилдетуулор"). The LLM Russian translation runs only
    for non-Russian queries. Original text is always kept."""
    if not query.strip():
        return query
    parts = [query]
    g = _glossary_expand(query)
    if g:
        parts.append(g)
    if lang != "ru":
        tr = _llm_translate_to_ru(query)
        if tr and tr.lower() != query.lower():
            parts.append(tr)
    return "  ".join(parts) if len(parts) > 1 else query
