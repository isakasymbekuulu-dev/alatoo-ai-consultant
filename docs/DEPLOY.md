# Деплой и CI/CD — памятка

Краткая шпаргалка по тому, как развёрнут и обновляется AI-консультант Ала-Тоо.
Секретов здесь нет (приватный ключ и токен хранятся в защищённых местах — см. ниже).

## Где что находится

| Что | Значение |
|---|---|
| Сервер (DigitalOcean droplet) | `167.172.176.33` (Ubuntu 22.04, FRA1) |
| Путь к репозиторию на сервере | `/opt/alatoo-ai-consultant` |
| Публичный сайт | https://chat.alatoogpt.xyz |
| GitHub-репозиторий | https://github.com/isakasymbekuulu-dev/alatoo-ai-consultant |
| Сервисы (docker compose) | `qdrant`, `backend` (FastAPI, порт 8000), `openwebui` |
| Вход на сервер | DigitalOcean → Droplets → **Web Console** (по email через Google) |

## Как обновлять контент (главное)

1. Меняете файлы в папке `data/` (или код).
2. `git push` в ветку `main`.
3. Дальше **всё автоматически**: GitHub Actions заходит на сервер, обновляет код,
   пересобирает контейнеры и переиндексирует базу знаний (Qdrant) — но переиндексация
   запускается, только если менялись `data/` или `ingestion/`.

Руками на сервер заходить больше не нужно. Прогресс виден во вкладке
**Actions → Deploy to droplet**.

## CI/CD: как устроено

Файл `.github/workflows/deploy.yml`. Триггеры: push в `main` и ручной запуск
(**Actions → Deploy to droplet → Run workflow**). На сервере выполняется:
`git reset --hard origin/main` → `docker compose up -d --build` →
(если менялись данные) `docker compose run --rm backend python -m ingestion.ingest --recreate`.

Первый прогон ~3 минуты; переиндексация на 2 ГБ RAM занимает пару минут (эмбеддер BGE-M3).

### Секреты GitHub (Settings → Secrets and variables → Actions)

| Секрет | Значение | Кто хранит |
|---|---|---|
| `DEPLOY_HOST` | `167.172.176.33` | в секретах GitHub |
| `DEPLOY_USER` | `root` | в секретах GitHub |
| `DEPLOY_PATH` | `/opt/alatoo-ai-consultant` | в секретах GitHub |
| `DEPLOY_SSH_KEY` | приватный SSH-ключ деплоя | в секретах GitHub (значение не показывается) |
| `DEPLOY_PORT` | не задан → по умолчанию 22 | — |

SSH-ключ деплоя: публичная часть лежит на сервере в `~/.ssh/authorized_keys`
(имя ключа `github-actions-deploy`), приватная — в секрете `DEPLOY_SSH_KEY`.
Если нужно отозвать доступ — удалите эту строку из `authorized_keys` на сервере
и пересоздайте ключ + секрет.

### GitHub-токен для push

Fine-grained PAT **`alatoo-deploy-push`** (только репозиторий alatoo-ai-consultant,
права Contents + Workflows: Read and write). **Истекает 16 июля 2026** — после этого
выпустить новый: GitHub → Settings → Developer settings → Fine-grained tokens.
Сам токен хранится только у вас (в файл не записан).

## Ручной деплой (запасной вариант, без GitHub Actions)

Если нужно выкатить вручную — в Web Console дроплета:

```
cd /opt/alatoo-ai-consultant
git pull
docker compose up -d --build
docker compose run --rm backend python -m ingestion.ingest --recreate
```

## Что было сделано 2026-06-16

- Справочник кабинетов: повреждённый `data/Кабинеты.csv` заменён на чистый
  `data/Кабинеты.md` (337 сотрудников, 119 кабинетов, 44 подразделения) — ИИ
  отвечает «кто в каком кабинете».
- Настроен CI/CD (этот файл), деплой проверен (зелёный прогон + живой ответ на сайте).
