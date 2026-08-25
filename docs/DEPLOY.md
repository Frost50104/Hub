# Deploy

## Окружения

| | staging | prod |
|---|---|---|
| Домен | `hub-staging.signaris.ru` | `hub.signaris.ru` |
| systemd | `signaris-hub-staging.service` | `signaris-hub.service` |
| `/opt` путь | `/opt/signaris-hub-staging/` | `/opt/signaris-hub/` |
| Postgres DB | `signaris_hub_staging_db` | `signaris_hub_db` |
| Redis DB | 5 | 4 |
| Backend port | 5060 | 5059 |
| Build команда | `npm run build:staging` | `npm run build` |

**VPS:** оба окружения на одном новом VPS `94.241.168.8` (Ubuntu 24.04 LTS). Авторизация — root по паролю (пароль в локальном `Hub/CLAUDE.md` → СЕКРЕТЫ).

**VAPID-ключ:** единый для двух env, лежит в `/opt/signaris-hub/vapid_private.pem` (mode 600 root:signaris).

## deploy.sh

Форк из `AXO_bot_web/deploy/deploy.sh`. Использование:

```bash
./deploy/deploy.sh staging              # backend + frontend
./deploy/deploy.sh prod                 # backend + frontend
./deploy/deploy.sh staging backend      # только backend
./deploy/deploy.sh prod frontend        # только frontend
```

Что делает:

1. Пишет корневой `VERSION` и `web/public/version.json` — git-hash + dirty-флаг + timestamp.
2. Backend: `rsync` (без `--delete`) в `/opt/signaris-hub[-staging]/`, pre-migration снапшот БД, `pip install` + `alembic upgrade head`, `systemctl restart signaris-hub[-staging]` (+ extraction-воркер).
3. Frontend: **собирается ЛОКАЛЬНО** (`npm install && npm run build[:staging]` в `web/`, проверка `dist/index.html`), затем `rsync --delete` только внутри `web/dist/` на VPS. С 2026-08-21 `vite build` на сервере не запускается: на VPS 2 ГБ без swap сборка росла до ~970 МБ RSS и падала по OOM даже при остановленном STT. node на сервере для деплоя больше не нужен.
4. Smoke-check на `https://hub[-staging].signaris.ru/api/env`. **Сверить версию:** `curl …/version.json` должен совпасть с `git rev-parse --short HEAD` (дважды ловили деплой, уехавший без последнего коммита / со старым dist).

## Rollback

Релизного каталога нет (rsync поверх `/opt/...`), откат = redeploy предыдущего git-состояния + при необходимости откат БД.

1. **Код (backend + frontend):**
   ```bash
   git stash                      # если есть незакоммиченное
   git checkout <прошлый-hash>    # хеш из version.json до деплоя
   ./deploy/deploy.sh prod
   git checkout main && git stash pop
   ```
   `alembic upgrade head` на старом коде — no-op (лишние ревизии БД он не откатит, аддитивные миграции старому коду не мешают).

2. **Миграция, которую нужно откатить** (деструктивная/сломанная):
   ```bash
   ssh root@94.241.168.8
   cd /opt/signaris-hub && ./.venv/bin/alembic downgrade <prev_rev>
   ```

3. **Данные испорчены** — restore из pre-migration снапшота (deploy.sh снимает его перед каждым `alembic upgrade`, хранятся последние 5 в `/opt/signaris-hub/backups/pre-migrate/`):
   ```bash
   systemctl stop signaris-hub
   sudo -u postgres pg_restore --clean --if-exists -d signaris_hub_db \
     /opt/signaris-hub/backups/pre-migrate/db-signaris_hub_db-<ts>.dump
   systemctl start signaris-hub
   ```
   Суточные дампы — в `/opt/signaris-hub/backups/daily/` (plain SQL.gz: `zcat ... | sudo -u postgres psql -d <db>`).

После любого отката: `curl https://hub.signaris.ru/api/env` + smoke по основным страницам; фронт может требовать hard-refresh из-за PWA-кэша (баннер обновления).

## Bootstrap нового VPS

Один раз при provision'е `94.241.168.8`:

```bash
./deploy/bootstrap-vps.sh
```

Что делает (idempotent):

1. `apt install postgresql-16 redis-server nginx certbot python3.12 python3.12-venv nodejs npm` (nodejs/npm с 2026-08-21 для деплоя не нужны — фронт собирается локально)
2. `useradd signaris`, создание `/opt/signaris-hub[-staging]/`
3. Генерация VAPID-пары → `/opt/signaris-hub/vapid_private.pem` (mode 600 root:signaris)
4. `createdb signaris_hub_db signaris_hub_staging_db`, `createuser signaris_hub` (non-superuser, пароль в `/opt/signaris-hub/.env`)
5. Redis: `bind 127.0.0.1`, `databases >= 6` (auth=3, hub-prod=4, hub-staging=5)
6. Копирование systemd-юнитов из `ops/systemd/` + `systemctl enable`
7. Копирование nginx-конфигов из `ops/nginx/`
8. `certbot --nginx -d hub.signaris.ru -d hub-staging.signaris.ru`

## Юниты помимо backend (ops/systemd/)

| Юнит | Что | Где включён |
|---|---|---|
| `signaris-hub[-staging]-extraction.service` | long-running воркер `app/workers/extraction.py` (извлечение текста + RAG-reconcile) | оба env |
| `signaris-hub-stt.service` | faster-whisper `small` для голосового ввода ассистента (`app/stt_service.py`), `MemoryHigh=800M`+`MemoryMax=1100M`, выгрузка модели по 5 мин | **только прод** — одна STT-машина на хост, staging-юнит disable-нут |
| `signaris-hub[-staging]-{due-soon,overdue,course-due-soon,review-due,inactivity,automations}.timer` | cron-джобы `app/jobs/*` (расписание — `docs/PUSH.md`) | оба env |
| `signaris-hub-backup.timer` / `backup-cleanup.timer` / `backup-files.timer` / `healthcheck.timer` | общие для двух env | прод-хост |

Staging-копии юнитов генерируются `ops/systemd/make-staging-unit.py` — не копировать руками.

## Cron timers и воркеры (полный список)

**Cron timers (due-soon hourly / overdue daily 09:00 MSK):** есть в обоих env — prod (`signaris-hub-{due-soon,overdue}.timer`) и staging (`signaris-hub-staging-{due-soon,overdue}.timer`).

**Cron timers (общие для prod+staging, 3.6.8):**
- `signaris-hub-backup.timer` — 00:00 UTC daily, один run для обеих БД, `User=postgres`. Файлы в `/opt/signaris-hub/backups/daily/db-<db>-<date>.sql.gz`, Sunday hardlink → `weekly/`. Optional S3 offsite через `/etc/default/signaris-hub-backup` (BACKUP_S3_BUCKET + AWS creds).
- `signaris-hub-backup-cleanup.timer` — 00:30 UTC daily, retention 14d daily + 42d weekly.
- `signaris-hub[-staging]-course-due-soon.timer` — daily 06:15 UTC, напоминание о дедлайне назначенного курса (`app/jobs/course_due_soon.py`); включён на обоих env.
- `signaris-hub[-staging]-automations.timer` — hourly :20, исполнение automation_jobs чанком 200 (`app/jobs/automations_run.py`); включён на обоих env.
- `signaris-hub[-staging]-inactivity.timer` — daily 07:00 UTC, правило неактивности warn→grace→авто-архив (`app/jobs/inactivity.py`); включён на обоих env.
- `signaris-hub[-staging]-extraction.service` — long-running воркер извлечения текста + RAG-reconcile (Ф6, без таймера); включён на обоих env.
- `signaris-hub-healthcheck.timer` — `OnUnitActiveSec=5min`, state-files в `/var/lib/signaris-hub/health.<url>.state`, edge-trigger email через `mail(1)` на 2 consecutive failures (`/etc/default/signaris-hub-healthcheck::HEALTHCHECK_ALERT_EMAIL`).
- `signaris-hub-backup-files.timer` — 00:15 UTC daily, root, rsync --link-dest снапшоты attachments обоих env в `backups/files/<env>/<date>` (retention 14д в backup-cleanup).
- `signaris-hub[-staging]-review-due.timer` — 06:30 UTC daily, напоминания владельцам материалов (`app/jobs/review_due.py`); включён на обоих env.

## nginx-инварианты

локации `/api/*` и `/_protected_media/` ОБЯЗАНЫ иметь `^~` (иначе статик-regex перехватывает media → 404); media-локации (`/api/media/`, `/_protected_media/`) переиздают ПОЛНЫЙ набор security-заголовков с `X-Frame-Options SAMEORIGIN` + CSP `frame-ancestors 'self'` и БЕЗ `sandbox` (первый `add_header` в локации сбрасывает server-level набор; server-DENY убьёт PDF-iframe уроков); `location ^~ /api/ai/` — `proxy_read_timeout 120s` и без `add_header`; локация, которая переиздаёт заголовки И отдаёт SPA (`/p/`), обязана заканчивать `try_files $uri /index.html =404;` кодом, а не URI (иначе внутренний редирект теряет `Referrer-Policy: no-referrer`); `Permissions-Policy: microphone=(self)` во ВСЕХ дублях строки, кроме `/p/`; правка анти-FOUC скрипта темы в `index.html` требует пересчёта sha256 в CSP (`ops/nginx/hub-security-headers.conf`); шрифты self-hosted (`web/src/assets/fonts/`); staging обязан иметь `SIGNARIS_HUB_PUBLIC_BASE_URL`.

**Инструкции по Hub (`/guides/`, 25.08).** Две автономные HTML-страницы лежат в `guides/` в корне репо и приезжают обычным backend-rsync'ом в `/opt/signaris-hub[-staging]/guides/`. Отдаёт их `GET /api/guides/{kind}?e&s` (подпись как у медиа) через internal-локацию `^~ /_guides/` — публичной статикой класть нельзя: внутри реальные экраны с ФИО сотрудников и адресами точек. У локации СВОЙ набор заголовков с ослабленным `script-src 'self' 'unsafe-inline'` (у инструкции свой inline-скрипт: поиск по документу и отметки о прочтении) и `connect-src 'none'`; `~^/api/guides/` исключён из access_log — подписанная ссылка это capability. На staging обязателен `SIGNARIS_HUB_GUIDES_ROOT` в `.env` (как `ATTACHMENTS_ROOT`). Правка конфигов деплоем НЕ применяется: `scp` в `/etc/nginx/sites-available/`, `nginx -t`, `systemctl reload nginx`.

## Память VPS: STT и сборка фронта

STT-юнит — пара `MemoryHigh=800M` + `MemoryMax=1100M` (одиночный `MemoryMax` ловит OOM на странице кэша весов) + выгрузка модели по 5 мин простоя; **одна STT-машина на хост** — включён ПРОД, staging-юнит disable-нут; staging-юниты собирать `ops/systemd/make-staging-unit.py`. `vite build` на VPS больше не запускается — `deploy.sh` собирает фронт локально и заливает `web/dist` (сборка на сервере росла до ~970 МБ RSS и падала по OOM).

## Healthcheck-алерты

`signaris-hub-healthcheck.timer` каждые 5 минут запускает `scripts/healthcheck.sh` (деплоится bootstrap-скриптом в `/opt/signaris-hub/scripts/`). Скрипт curl-ит `/api/env` обоих окружений и на 2 consecutive failures шлёт алерт (edge-trigger, recovery-сообщение при восстановлении).

Каналы (оба опциональны, настраиваются в `/etc/default/signaris-hub-healthcheck` на VPS — файл НЕ в git):

```bash
# email — требует установленного mail(1)/MTA на VPS
HEALTHCHECK_ALERT_EMAIL=ops@signaris.ru
# Telegram — бот от @BotFather; без обеих переменных канал молча выключен
TELEGRAM_BOT_TOKEN=123456:ABC-...
TELEGRAM_CHAT_ID=-100123456789
```

После правки env-файла ничего перезапускать не нужно (oneshot-сервис читает его при каждом запуске). Проверка: временно вписать несуществующий URL в `HEALTHCHECK_URLS` → через ~10 минут придёт DOWN-сообщение, после удаления — OK-сообщение.

## DNS

A-записи:
- `hub.signaris.ru` → `94.241.168.8`
- `hub-staging.signaris.ru` → `94.241.168.8`

## CORS / SSO redirect whitelist (в env auth)

`signaris-auth` развёрнут в **единственном экземпляре** на VPS `194.87.215.15` (`auth.signaris.ru`) — отдельного staging-instance нет. Staging-домены продуктов добавляются в env того же сервиса. Env-файл на хосте auth: `/etc/signaris-auth/signaris-auth.env`. После правки — `systemctl restart signaris-auth` (не `reload` — в unit нет `ExecReload`, и `EnvironmentFile` читается только при старте процесса).

Добавляется в две фазы:

- **Hub-MVP.1 (staging):** `SIGNARIS_AUTH_CORS_ORIGINS += https://hub-staging.signaris.ru` + `SIGNARIS_AUTH_SSO_REDIRECT_ORIGINS += https://hub-staging.signaris.ru` → `systemctl restart signaris-auth`.
- **Hub-MVP.6 (prod):** то же для `https://hub.signaris.ru` → `systemctl restart signaris-auth`.

## Активация hub в auth (после Hub-MVP.6)

В `CentralAuthService/app/constants/products.py`:
```python
INTEGRATED_PRODUCTS: frozenset[str] = frozenset({"net", "sonar", "hub"})
```

Затем через UI auth.signaris.ru:
1. UPPETIT-tenant → `purchased_products += ["hub"]`
2. Владелец UPPETIT → RoleEditor → выдать `hub:admin`
3. Получить service-key для deletion-sync → `SIGNARIS_HUB_SIGNARIS_SERVICE_KEY` в `/opt/signaris-hub/.env`
4. `systemctl restart signaris-hub`

## Ключевые env-переменные (`SIGNARIS_HUB_*`, полный список — `app/config.py`, 54 поля)

Значения живут ТОЛЬКО в `/opt/signaris-hub[-staging]/.env` на VPS (+ секреты в локальном CLAUDE.md → СЕКРЕТЫ). Операционно-значимые:

| Переменная | Зачем |
|---|---|
| `APP_VERSION` | **НЕ задавать в `.env`**: default читается из файла `VERSION` в корне (пишет `deploy.sh` — git-hash + dirty + timestamp, тот же источник, что `web/public/version.json`); env перебивает файл — до 2026-08-21 оба окружения держали `0.1.0-bootstrap` и `/api/env.version` врал (QA-0821 #1) |
| `DISPLAY_TIMEZONE` | часовой пояс человекочитаемых дат в уведомлениях/CSV (`app/services/timefmt.py`), default `Europe/Moscow`; tenant-tz нет |
| `PUBLIC_BASE_URL` | база для публичных ссылок `/p/<token>`. **На staging ОБЯЗАТЕЛЬНА** (`https://hub-staging.signaris.ru`) — дефолт прод-домен, иначе staging-ссылки битые (QA-находка 2026-07-20) |
| `MEDIA_URL_SECRET` | HMAC-секрет подписи learn-медиа URL; если не задан — деривится из database_url. Смена = все выданные ссылки протухают |
| `MEDIA_ACCEL_ENABLED` / `MEDIA_URL_TTL_SEC` / `MEDIA_MIN_FREE_BYTES` | X-Accel-отдача, TTL подписи (6ч), statvfs-порог upload'а |
| `AI_PROVIDER` / `AI_API_KEY` / `AI_BASE_URL` / `AI_CHAT_MODEL` / `AI_EMBED_MODEL` / `AI_FOLDER_ID` | LLM-провайдер Ф6 (yandex\|gigachat\|openai-compatible). Без ключа `/api/ai/ask` → 503, extraction-воркер пропускает RAG-шаг |
| `AI_ENABLED` / `AI_TOOL_MODEL` | выключатель ассистента и отдельная модель для tool-calling (по умолчанию = chat-модель) |
| `IIKO_BASE_URL` / `IIKO_LOGIN` / `IIKO_PASSWORD` / `IIKO_VERIFY_SSL` / `IIKO_TIMEOUT_SEC` / `IIKO_CACHE_TTL_SEC` | отчёты ассистента поверх iiko OLAP. **Слот лицензии сети общий с продуктом Listen** — стоит отдельная учётка под Hub; без переменных экран отчётов показывает «не подключены» |
| `STT_ENABLED` / `STT_PROVIDER` / `STT_MODEL` / `STT_LANGUAGE` / `STT_COMPUTE_TYPE` / `STT_CPU_THREADS` / `STT_URL` / `STT_IDLE_UNLOAD_SEC` / `STT_MAX_BYTES` / `STT_TIMEOUT_SEC` / `STT_API_KEY` / `STT_BASE_URL` | голосовой ввод: backend ходит в отдельный юнит `signaris-hub-stt` по `STT_URL`; без `STT_ENABLED` микрофон в UI не рисуется |
| `SID_SYNC_ENABLED` / `SID_SYNC_POLL_SEC` | воркер ревокаций SSO-сессий (блокирует `--workers > 1`) |
| `DELETION_SYNC_ENABLED` / `SIGNARIS_SERVICE_KEY` | deletion-sync из auth |
| `ATTACHMENTS_ROOT` / `ATTACHMENT_MAX_BYTES` | корень файлов (вложения задач + learn-медиа), лимит вложений задач |
| `VAPID_PUBLIC_KEY` / `VAPID_PRIVATE_KEY_PATH` / `VAPID_SUBJECT` | Web Push |
| `SENTRY_DSN` | включает Sentry backend (+frontend через /api/env); пока не задан |
| `PUBLIC_LINKS_ENABLED` | feature-flag публичных ссылок (default true) |
