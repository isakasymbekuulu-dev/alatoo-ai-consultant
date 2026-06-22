# CLAUDE.md — AI-консультант Ала-Тоо Университета

> Контекст-файл для Claude. В новом чате с подключённой папкой проекта Claude читает его
> автоматически и продолжает работу без потери контекста. Человек: **Isa**
> (isa.kasymbekuulu@alatoo.edu.kg). Проект **уже работает в проде** — это не «с нуля».
>
> Как продолжить в новом чате: подключить эту папку и написать «продолжаем проект, читай
> CLAUDE.md». Сначала прочитать §0 (живой снимок) и §13 (что дальше).

---

## 0. Текущее состояние (ЖИВОЙ СНИМОК) — обновлять при каждом изменении

**Статус:** в проде, работает. Обновлено 2026-06-22.

- **Сайт (чат):** https://chat.alatoogpt.xyz · тест профориентации: `/test` ·
  админка (по токену): `/admin/logs`, `/admin/graph`, `/healthz`.
- **Сервер:** DigitalOcean дроплет `167.172.176.33` (Ubuntu 22.04, **Basic 4 vCPU / 8 ГБ /
  70 ГБ**, $48/мес — имя дроплета «1vcpu-2gb» врёт). Repo на сервере: `/opt/alatoo-ai-consultant`.
  Docker Compose: `qdrant`, `backend` (FastAPI), `openwebui`. HTTPS — реверс-прокси (уточнить nginx/Caddy).
- **GitHub:** https://github.com/isakasymbekuulu-dev/alatoo-ai-consultant (owner `isakasymbekuulu-dev`).
- **CI/CD:** `.github/workflows/deploy.yml` — пуш в `main` → SSH-деплой (`git reset`, пересборка
  backend, подстановка LLM-ключей в `.env` из секретов, переиндексация **только если менялись
  `data/` или `ingestion/`**, прогрев). Затем job `eval` (`eval/qa_eval.py`). Пуш-токен сохранён
  в `.git/credentials` (chmod 600, не трекается) → `git push origin main` из сессии работает сам.
- **LLM (failover, app/llm.py):** OpenAI `gpt-4o-mini` (основной) → Groq `llama-3.3-70b` (запас)
  → GitHub Models (последний резерв). Ключи приходят из GitHub Secrets через deploy.yml. Стриминг
  защищён (переключение только до первого токена; при полном отказе — короткое сообщение, не разрыв SSE).
- **RAG:** LangChain `QdrantVectorStore` HYBRID (dense **BGE-M3** локально + sparse **BM25**, слияние
  RRF). Реранкер `app/rerank.py` есть, но **выключен по умолчанию** (`RERANK_ENABLED=false`) — на CPU
  медленно для live-чата. Коллекция `alatoo_kb`, `top_k=6`.
- **Языки:** база знаний фактически **только русская**. Принцип: **искать по-русски, отвечать на
  языке пользователя** (см. §8.5, `app/lang.py`).
- **Данные (`data/`):** `Кабинеты.md`, `Справочник_университета_2026.md`, `Цены_и_скидки_2026.md`,
  + 2 брошюры PDF. (Шумные PDF с ценами удалены — таблицы плохо чанковались.)
- **Соц-боты:** пока не запущены. Готов опросник для приёмной комиссии
  `Опросник_приёмная_комиссия_соцбот.docx` (Instagram Direct / WhatsApp / Telegram) — ждём ответы,
  затем системный промпт соц-бота (см. §13).

- **Бэкапы (2026-06-22):** `scripts/backup_local.sh` (полный архив папки → `backups/local/`, храним 10), `scripts/backup_server.sh` (SQLite+Qdrant+OpenWebUI+.env на дроплете → `backups/server/`), `restore_server.sh`, `pull_server_backups.sh`. Авто: weekly scheduled task (локально+push) + cron на дроплете (см. `docs/BACKUP.md`). `backups/` в .gitignore.

**Реальная структура кода (НЕ та, что в §9 — та была первоначальным планом):**
```
app/        main.py (FastAPI + /v1/chat/completions, /riasec/*, /admin/*),
            graph.py (LangGraph: router→rag|riasec|general), rag.py (retrieve+промпт),
            lang.py (язык: детект+директива+перевод запроса), llm.py (failover),
            config.py, embeddings.py, qdrant_store.py, rerank.py, riasec.py,
            logging_store.py (SQLite), static/ (index.html, test.html, admin.html, graph.html)
ingestion/  ingest.py (scrape→clean→chunk(header-aware)→metadata→hybrid upsert)
eval/       qa_eval.py (регрессия по API), llm_bench.py (скорость/качество провайдеров)
data/       markdown базы знаний (см. выше)
docs/adr/   архитектурные решения (0002 RIASEC, 0003 LangChain hybrid)
tests/      pytest (RIASEC и пр.)
.github/workflows/  deploy.yml, llm-bench.yml
docker-compose.yml, requirements.txt, .env
```

**Деплой/переиндексация вручную (если нужно, на сервере):**
```
docker compose up -d --build --force-recreate backend
docker compose run --rm backend python -m ingestion.ingest --recreate   # пересобрать Qdrant
```

---

## 1. Что строим

AI-консультант вуза для абитуриентов/студентов. Две части в **одном графе LangGraph**:

1. **Профориентационный тест RIASEC** (модель Голланда, 6 типов) → профиль (напр. «ICR») →
   рекомендации программ Ала-Тоо.
2. **RAG-консультация** по базе знаний вуза — программы, факультеты, поступление, цены, FAQ.

## 2. Стек

Python · **LangChain** (загрузчики/сплиттеры/обвязка) · **LangGraph** (оркестрация диалога) ·
**Qdrant** (вектор-БД в Docker) · **FastAPI** (единый бэкенд) · **OpenWebUI** (один из фронтов).
Эмбеддер BGE-M3, sparse BM25. Всё это pip-библиотеки, не коннекторы.

## 3. Каналы

| Канал | Как | Статус |
|---|---|---|
| **Веб-чат** (`chat.alatoogpt.xyz`) | собственный фронт `app/static/index.html` | ✅ в проде |
| **OpenWebUI** | pipeline к бэкенду | в стеке |
| **WhatsApp** | через **Twilio** | плагин стоит, адаптер не написан |
| **Telegram** | `python-telegram-bot` | планируется |
| **Instagram / Facebook** | Meta Graph API + вебхуки | планируется |

Все каналы — тонкие адаптеры к **одному** бэкенду (один граф, одна логика). Соц-боты — см. §13.

## 4. Источник знаний для RAG

Локальные файлы в `data/` (markdown, собранные из Google-таблицы вуза, справочника кабинетов,
брошюр). Фактически **русскоязычные**. Скрейпинг сайта вуза (Bright Data) — на будущее
(тогда же заполнить `source_url`).

## 5. Установленные плагины

- **Engineering** — system-design, architecture (ADR), code-review, testing-strategy, documentation, debug.
- **Twilio Developer Kit** — канал WhatsApp (+ Verify/OTP).
- **Bright Data** — скрейпинг сайта в markdown + соцсети (`scrape`, `scraper-builder`, `data-feeds`, `search`, CLI `bdata`).

## 6. Архитектура

```
   Каналы (адаптеры): Веб-чат / OpenWebUI / WhatsApp(Twilio) / Telegram / Meta
                                  │ единый API (FastAPI, app/main.py)
                                  ▼
                       LangGraph граф (app/graph.py)
                  router → { rag | riasec | general }
                                  ▼
            retrieve (app/rag.py): перевод запроса на RU (app/lang.py)
            → Qdrant HYBRID (dense BGE-M3 + sparse BM25, RRF) [→ rerank]
                                  ▼
                       LLM (app/llm.py, failover) → ответ на языке пользователя
```

## 7. Ingestion-пайплайн (`ingestion/ingest.py`)

`scrape → clean → chunk → metadata → upsert`. Markdown чанкуется header-aware
(`MarkdownHeaderTextSplitter` + recursive), путь заголовков подмешан в текст; метаданные
`source/doc_type/lang/section/faculty/source_url` + payload-индексы. Upsert в `QdrantVectorStore`
(named-векторы dense+sparse). Коллекция пересоздаётся при `--recreate`; чанки дедуплицируются по хешу.

---

## 8. Журнал сделанного (changelog)

### 8.1 (2026-06-10) RIASEC-тест ✅
- `app/riasec.py` — адаптация **O*NET Interest Profiler Short Form**: 60 пунктов (по 10 на тип),
  Ликерт 1–5, ru/ky/en, скоринг + код Голланда + маппинг на программы бакалавриата (топ-6, веса 3/2/1).
- `app/static/test.html` — страница `/test`: согласие, переключатель языка, прогресс, экран
  результатов, кнопка «Обсудить с ИИ».
- API: `GET /riasec/api/questions`, `POST /riasec/api/submit`, `GET /riasec/api/result`,
  `GET /admin/api/riasec`. Результаты в SQLite; ход теста логируется (`source=riasec-test`).
- Интеграция: профиль подмешивается в контекст LLM по заголовку `X-Riasec-Id` или по `session_id`.
- Тесты `tests/test_riasec.py`. ADR `docs/adr/0002-riasec-test.md`.

### 8.2 (2026-06-16) Справочник кабинетов ✅
- `data/Кабинеты.md` (337 сотрудников, 119 кабинетов, 44 подразделения): проекции «по подразделениям»
  и «указатель по кабинетам». Повреждённый `Кабинеты.csv` удалён.

### 8.3 (2026-06-18) RAG на LangChain + гибрид ✅
- Ingestion+retrieval на `QdrantVectorStore` HYBRID (dense BGE-M3 + sparse BM25, RRF). Header-aware
  чанкинг, метаданные+индексы, `top_k=6`, без cosine-threshold (RRF-скоры). ADR `0003`.

### 8.4 (2026-06-18) Cross-encoder реранкер ✅ (сейчас ВЫКЛ)
- `app/rerank.py` — `jina-reranker-v2-base-multilingual` (FastEmbed/ONNX). Флаг `RERANK_ENABLED`,
  по умолчанию **off** (на 1 vCPU медленно для live). Мягкий фолбэк на гибридный порядок.

### 8.5 (2026-06-21) Многоязычность + контакты + провайдеры LLM ✅
- **LLM-провайдеры**: OpenAI gpt-4o-mini (осн.) → Groq (запас) → GitHub Models. Failover в `app/llm.py`,
  ключи из секретов через `deploy.yml`. (Azure не вышло активировать — код поддерживает, но не используется.)
- **Цены**: `data/Цены_и_скидки_2026.md` — по одной строке на программу (КР/иностранцы, все ступени)
  + правила скидок. Чинит баг, когда из PDF-таблиц утекали чужие цены (финансы выдавал 216 000 вместо 288 000).
- **3 бага многоязычности (`app/lang.py` + `rag.py` + `graph.py`, commit 693469f):**
  1. *Соскок на русский* → строгая директива языка ответа последним system-сообщением (перебивает RU-контекст).
  2. *«Обратитесь в комиссию» без контактов* → `ADMISSIONS_CONTACT` всегда в промпте; правило: не знаешь/отправляешь — дай контакты (555 820 000, admission@alatoo.edu.kg, блок А каб.107, 9:00–17:00).
  3. *Кыргызский поиск мимо* → база русская, поэтому **поисковый запрос переводится на RU** (глоссарий
     ky/en→ru мгновенно + короткий LLM-перевод), а ответ — на языке пользователя. «женилдетүүлөр»→находит скидки.
- Проверено на ru/ky/en вживую. **Известный минорный баг:** в мультитёрне («Экономика» → «баасы канча?»)
  может выдать не ту ступень цены — название программы не переносится в поисковый запрос (фикс — см. §13).
- **Опросник соц-бота** `Опросник_приёмная_комиссия_соцбот.docx` готов.

### 8.6 (2026-06-22) Бэкап-система ✅
- **Цель:** ничего не потерять, восстановить с нуля. Карта данных: код/данные → GitHub; незаменимое → SQLite на сервере (логи чата + RIASEC).
- **Скрипты `scripts/`:** `backup_local.sh` (tar.gz всей папки, retention 10), `backup_server.sh` (online-бэкап SQLite через python в контейнере + тома `qdrant_data`/`openwebui-data` + `.env`, шифрование по `BACKUP_PASSPHRASE`), `restore_server.sh`, `pull_server_backups.sh` (rsync с дроплета).
- **Авто:** weekly scheduled task `alatoo-weekly-backup` (Пн 09:00, локальный архив + git push); на сервере — cron `0 3 * * *` (см. `docs/BACKUP.md`). Первый локальный снимок снят и проверен (~10 МБ, 124 файла).
- **Среда:** подключённая папка БЛОКИРУЕТ удаление файлов, но разрешает rename → перед git-операциями переименовываем `.git/*.lock` в сторону (`mv L L.stale-TS`); предупреждения 'unable to unlink' безвредны.
- Runbook восстановления с нуля — `docs/BACKUP.md`.

---

## 9. (Историческое) Первоначальный план структуры репозитория

> Оставлено для истории. **Актуальная структура — в §0.** Изначально предполагались каталоги
> `riasec/ graph/ api/ channels/`, но всё реализовано в `app/`.

## 10. Решённые вопросы (бывшие «открытые»)

- LLM/эмбеддер: OpenAI gpt-4o-mini + BGE-M3 (sparse BM25). Языки контента — русский.
- Деплой: DigitalOcean дроплет + Docker Compose (см. §0).
- RIASEC: O*NET Interest Profiler (адаптация), маппинг на программы готов.
- Ключи: OpenAI/Groq/GitHub в GitHub Secrets; пуш-токен в `.git/credentials`.
- **Остаётся уточнить:** чем терминируется HTTPS (nginx/Caddy); носитель кыргызского — проверка формулировок RIASEC.

## 11. Безопасность/честность для защиты

- CORS открыт `*`; публичный чат анонимный (rate-limit по IP). Реранкер выключен (CPU).
- Подавать по схеме «что есть → почему → как улучшу». Подробный Q&A для защиты —
  в сессии «Droplet deployment error» (`docs/defense_qa.md`).

---

## 12. ПРОТОКОЛ САМОТРЕКИНГА (чтобы важное трекалось само)

Чтобы в новом чате продолжать без потерь, **после каждого значимого изменения** Claude обязан:

1. **Обновить §0 (живой снимок)** — статус, дату, что поменялось (провайдеры, URL, флаги, данные).
2. **Добавить запись `§8.x (дата) ... ✅`** в журнал — кратко: что, зачем, какие файлы, известные баги/TODO.
3. **Закоммитить и запушить** (`git push origin main` — токен уже в `.git/credentials`). CI/CD сам
   задеплоит; переиндексация — только если менялись `data/` или `ingestion/`.
4. **Обновить долгую память** (см. §14) — файлы в memory-каталоге авто-подгружаются в каждую сессию.

> Технический нюанс среды: инструменты Write/Edit иногда **обрезают** файлы на bash-mount (файл
> заканчивается на середине, но парсится). Для коммитимых файлов — писать через bash heredoc и
> проверять `git diff` + `python -c "import ast; ast.parse(open(f).read())"` перед коммитом.

## 13. Что дальше (next steps)

1. **Соц-боты.** Получить заполненный `Опросник_приёмная_комиссия_соцбот.docx` от приёмной комиссии →
   собрать системный промпт соц-бота (тон, длина **отдельно по каналам**, что обязан/нельзя, эскалация
   с контактами) → адаптеры `channels/` (Telegram → WhatsApp(Twilio) → Meta), все к одному бэкенду.
2. **Минорный фикс мультитёрна цен.** Подмешивать программу/тему из предыдущих реплик в поисковый
   запрос (`app/rag.py` build_messages / `app/lang.py`), чтобы «баасы канча?» давало нужную ступень.
3. **Фаза 2 RAG.** Скрейп сайта вуза (Bright Data) + заполнение `source_url`; multi-query; при росте
   нагрузки — +vCPU и включить реранкер (`RERANK_ENABLED=true`).
4. **RIASEC.** Проверка кыргызских формулировок носителем; валидация маппинга программ.

## 14. Долгая память (авто-подгружается)

Каталог памяти содержит факты, которые подхватываются в каждой сессии (индекс — `MEMORY.md`):
- `alatoo-deploy-cicd` — дроплет, repo, CI/CD, пуш-креды в `.git/credentials`.
- `alatoo-multilang-rag` — KB только RU, искать по-RU/отвечать на языке юзера, `app/lang.py`, 3 фикса.
- `alatoo-backup` — бэкап-система: scripts/, docs/BACKUP.md, weekly task + cron; мост блокирует delete (rename-aside .git locks).

## 15. Как Isa заводит проект в новом чате

1. Подключить (mount) папку проекта. 2. Написать «продолжаем проект, читай CLAUDE.md».
3. Claude читает §0 и §13 и продолжает. Плагины (Engineering, Twilio, Bright Data) стоят глобально.
