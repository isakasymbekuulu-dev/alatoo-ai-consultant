# AlaToo AI Consultant — MVP

AI-консультант Ала-Тоо Университета: абитуриент по ссылке без авторизации открывает
чат и задаёт вопросы о поступлении/программах. Ответы строятся по базе знаний вуза (RAG).

## Архитектура (кратко)
```
Абитуриент ──► Публичная страница чата ( /  )          ┐
Сотрудник  ──► OpenWebUI (логин)                       ├─► FastAPI /v1/chat/completions
                                                       │      │ ретрив (BGE-M3)
                                                       │      ▼
                                                       │   Qdrant (volume, постоянный)
                                                       │      │ контекст
                                                       │      ▼
                                                       └─► GitHub Models (gpt-4o-mini)
```
Подробности и обоснование — в `docs/adr/0001-mvp-architecture.md`.

## Стек
- **FastAPI** — OpenAI-совместимый бэкенд с RAG
- **Qdrant** — векторная БД (Docker volume → данные не теряются)
- **GitHub Models** — LLM `openai/gpt-4o-mini` (бесплатно по GitHub-токену)
- **BGE-M3** — локальные мультиязычные эмбеддинги (ky/ru/en), dim 1024
  (переключается на API `openai/text-embedding-3-small` одной строкой в `.env`)
- **OpenWebUI** — фронт для сотрудников

## Структура
```
app/            FastAPI + RAG (config, embeddings, qdrant_store, llm, rag, main)
  static/       публичная страница чата (index.html)
ingestion/      ingest.py: файлы data/ → clean → chunk → embed → Qdrant
data/           ИСХОДНЫЕ ФАЙЛЫ вуза (PDF/DOCX/TXT/MD) — положить сюда
docker-compose.yml / Dockerfile / requirements.txt
docs/adr/       архитектурные решения
```

## Запуск (на дроплете)
```bash
# 1. Настроить окружение
cp .env.example .env
nano .env                 # вставить GITHUB_TOKEN (PAT с правом Models: read)

# 2. Положить файлы вуза в ./data/

# 3. Поднять стек
docker compose up -d --build

# 4. Загрузить базу знаний в Qdrant (один раз / после обновления данных)
docker compose run --rm backend python -m ingestion.ingest --recreate

# 5. Проверить
curl localhost:8000/healthz
```
- Публичный чат абитуриента: `http://<IP>:8000/`
- OpenWebUI (сотрудники): `http://<IP>:3000/`
- Qdrant: `http://<IP>:6333/` (в проде закрыть фаерволом)

## Настройка GitHub Models
1. https://github.com/settings/personal-access-tokens → Fine-grained token
2. Permissions → **Models: Read-only**
3. Вставить токен в `.env` как `GITHUB_TOKEN`

## Эмбеддинги
По умолчанию локальный **BGE-M3** (dim 1024, лучшее качество ky/ru/en),
требует ~3-4 ГБ RAM. Если RAM мало — переключить на API в `.env`:
```
EMBED_MODEL=openai/text-embedding-3-small
EMBED_DIM=1536
```
и заново прогнать ingestion с `--recreate`.

## Дальше (roadmap)
RIASEC-тест (ветка LangGraph) · скрейпинг сайта (Bright Data) ·
каналы Telegram/WhatsApp/Meta к тому же `/v1` · TLS+домен · rate-limit.
