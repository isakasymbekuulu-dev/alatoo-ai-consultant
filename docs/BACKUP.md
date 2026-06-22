# Бэкап и восстановление — AI-консультант Ала-Тоо

> Цель: **ничего не потерять** и **восстановить проект с нуля** при любом сбое
> (умер дроплет, пропал ноутбук, удалили данные). Обновлено 2026-06-22.

## Что и где хранится (карта данных)

| Актив | Где живёт | Заменим? | Чем бэкапится |
|---|---|---|---|
| Исходный код, данные `data/`, презентации, docs | git → **GitHub** + локально | да (GitHub) | `git push` + локальный архив |
| Полный снимок папки проекта | `backups/local/*.tar.gz` (на машине) | — | `scripts/backup_local.sh` |
| **SQLite `chat.db`** (логи чата + результаты RIASEC) | том `chatlogs` на дроплете | **НЕТ — незаменим** | `scripts/backup_server.sh` |
| Qdrant `alatoo_kb` | том `qdrant_data` на дроплете | да (переиндексация) | `scripts/backup_server.sh` |
| OpenWebUI (юзеры + чаты) | том `openwebui-data` на дроплете | частично | `scripts/backup_server.sh` |
| Секреты `.env` | дроплет + **GitHub Secrets** | да (Secrets) | `scripts/backup_server.sh` (шифрует) |

Главный незаменимый актив — **SQLite на сервере**. Всё остальное либо в GitHub, либо
пересобирается. Поэтому серверный бэкап — обязателен; локальный — подстраховка.

## Три уровня защиты

1. **GitHub** — весь код и данные. Делается `git push` (CI/CD уже настроен).
2. **Локальный архив** — полный снимок папки проекта, `backups/local/`.
3. **Серверный архив** — SQLite + Qdrant + OpenWebUI + `.env`, `backups/server/`,
   стягивается домой через `pull_server_backups.sh`.

---

## Скрипты

### `scripts/backup_local.sh` (запускать локально / по расписанию)
Полный `tar.gz` папки проекта (без `.git`, кэшей и самих бэкапов) в `backups/local/`.
Хранит последние `KEEP` (по умолчанию 10).
```bash
bash scripts/backup_local.sh          # KEEP=10 по умолчанию
KEEP=20 bash scripts/backup_local.sh  # хранить 20 снимков
```

### `scripts/backup_server.sh` (запускать НА дроплете)
Снимает SQLite (консистентно, через online-backup), тома Qdrant и OpenWebUI, `.env`.
```bash
cd /opt/alatoo-ai-consultant
BACKUP_PASSPHRASE='придумай-пароль' bash scripts/backup_server.sh
```
Без `BACKUP_PASSPHRASE` `.env` ляжет в архив **в открытом виде** — тогда храните архив приватно.

### `scripts/pull_server_backups.sh` (запускать локально)
Стягивает серверные архивы в `backups/server/`.
```bash
DEPLOY_HOST=167.172.176.33 DEPLOY_USER=root bash scripts/pull_server_backups.sh
```

### `scripts/restore_server.sh` (запускать НА дроплете)
Восстанавливает данные из архива (спросит подтверждение, перезапишет тома).
```bash
cd /opt/alatoo-ai-consultant
bash scripts/restore_server.sh backups/server/alatoo-server-20260622-030000.tar.gz
```

---

## Автоматизация

### Локально (раз в неделю) — через Cowork scheduled task
Настроено в этой сессии: бэкап папки + `git push` каждую неделю. Работает, когда
открыто приложение Claude; если было закрыто — выполнится при следующем запуске.

### На сервере (каждую ночь) — cron на дроплете
**УСТАНОВЛЕНО 2026-06-22** (03:00 UTC, хранит 7 архивов, без шифрования .env). Строка cron:
```bash
crontab -e
# каждый день в 03:00 по серверному времени:
0 3 * * * cd /opt/alatoo-ai-consultant && KEEP=7 bash scripts/backup_server.sh >> /var/log/alatoo-backup.log 2>&1
```
### На твой Windows-комп (каждый день) — Планировщик заданий Windows
Серверные архивы лежат только на дроплете, пока не стянуты. Настройка автостягивания (делается один раз):

1. Настроить SSH-ключ (генерит ключ + ssh config, печатает публичный ключ и команду для сервера):
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\setup_pull_ssh.ps1
   ```
2. Вставить показанную одну строку в **web-консоль дроплета** (она добавляет твой публичный ключ в `~/.ssh/authorized_keys`). Это единственный шаг, который делаешь сам — он даёт доступ на вход.
3. Проверить: `ssh root@167.172.176.33 echo OK` → должно вывести `OK` без пароля.
4. Включить ежедневное автостягивание:
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\pull_server_backups.ps1 -LocalDir "D:\Backups\AlaToo\server" -Install
   ```
   Задача «AlaToo pull server backups» будет каждый день в 10:00 копировать новые архивы в `D:\Backups\AlaToo\server\`, хранит 7. (Без `-LocalDir` путь по умолчанию — `backups\server\` в папке проекта.) Работает, когда комп включён и ты в системе.

Скрипты Windows: `scripts/setup_pull_ssh.ps1`, `scripts/pull_server_backups.ps1` (использует встроенный `scp`).
Вариант для Linux/Mac/WSL остаётся в `scripts/pull_server_backups.sh`.

---

## Восстановление С НУЛЯ (новый сервер)

1. **Код:** `git clone https://github.com/isakasymbekuulu-dev/alatoo-ai-consultant.git /opt/alatoo-ai-consultant`
2. **Секреты:** восстановить `.env` из серверного архива (или из GitHub Secrets / `.env.example`).
3. **Поднять стек:** `docker compose up -d --build`
4. **Данные:** `bash scripts/restore_server.sh backups/server/<последний>.tar.gz`
   - если Qdrant-тома нет — пересобрать индекс: `docker compose run --rm backend python -m ingestion.ingest --recreate`
5. **Проверить:** `curl -s https://chat.alatoogpt.xyz/healthz` и открыть `/admin/logs`.

Полностью потеряли сервер И архивы, но есть GitHub? Код и `data/` целы → шаги 1–3 + переиндексация.
Теряются только исторические логи чата и результаты RIASEC (поэтому серверный бэкап важен).

---

## Заметки и риски

- **Удаление файлов** в подключённой папке из агента заблокировано средой — старые
  локальные архивы, возможно, придётся чистить вручную (или это сделает скрипт на вашей машине).
- **Приватность:** `chat.db` и OpenWebUI содержат пользовательские сообщения. Серверные
  архивы по умолчанию **не** коммитятся в git (`.gitignore: backups/`). Не кладите их в публичный репозиторий.
- **Офсайт-копия (на будущее):** для защиты от потери и GitHub, и дроплета, и ноутбука —
  завести DigitalOcean Spaces / Google Drive и заливать туда `backups/server/`. Сейчас не настроено.
