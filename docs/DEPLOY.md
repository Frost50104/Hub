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

## Фронт: старые чанки не удаляются (16.09)

`deploy_frontend` выкладывает `web/dist` **без `--delete`** и следом чистит по возрасту:
`find <remote>/web/dist/assets -type f -mtime +${DIST_KEEP_DAYS:-30} -delete`.

Почему так. `--delete` сносил старые хэшированные чанки в момент выката. Открытая вкладка продолжает их просить, получает 404, Vite шлёт `vite:preloadError`, и `lib/preloadRecovery.ts` перезагружает страницу — вместе с несохранённой работой (ОС 16.09). Попадает это прицельно по редакторам: в `vite.config.ts` тяжёлые чанки (`RichEditor`, `CourseBuilderPage`, `LearnEmployeesPage`, `LearnOrgPage`, `LearnAssessmentsPage`) намеренно исключены из precache и грузятся из сети ровно в момент открытия экрана.

Чистка идёт по ВОЗРАСТУ, а не по «нет в текущей сборке» — второе есть то самое поведение, от которого ушли. Безопасно потому, что `vite build` переписывает весь `dist` каждой сборкой, а `rsync -a` переносит свежий mtime: на проде это видно прямо — неизменившийся `index-B7tNu4VJ.js` получил сегодняшний mtime, а чанк прошлой сборки остался со старым.

**О чём помнить:** файл, ИСЧЕЗНУВШИЙ из сборки, теперь остаётся лежать. Для хэшированных чанков это и нужно, но постоянные имена (`index.html`, `sw.js`, `version.json`, `manifest.webmanifest`) переименовывать нельзя — старый `sw.js` продолжил бы контролировать клиентов. Если пришлось — снять руками.

Замер после первого такого выката на прод: `dist` вырос 4,5 → 7,2 МБ, файлов 112 → 211. Порог `DIST_KEEP_DAYS` переопределяется переменной окружения.

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
3. Frontend: **собирается ЛОКАЛЬНО** (`npm install && npm run build[:staging]` в `web/`, проверка `dist/index.html`), затем `rsync` **БЕЗ `--delete`** внутри `web/dist/` на VPS + чистка по возрасту — см. §«Фронт: старые чанки не удаляются (16.09)» выше. С 2026-08-21 `vite build` на сервере не запускается: сборка росла до ~970 МБ RSS и падала по OOM даже при остановленном STT (тогда в доке значилось «VPS 2 ГБ»; замер 16.09 даёт 3,8 ГБ — см. §«Память VPS» ниже). node на сервере для деплоя больше не нужен.
4. Smoke-check на `https://hub[-staging].signaris.ru/api/env`. **Сверить версию:** `curl …/version.json` должен совпасть с `git rev-parse --short HEAD` (дважды ловили деплой, уехавший без последнего коммита / со старым dist).

**`SSH_JUMP` в `deploy/.env` — деплой через промежуточный узел.** 2026-08-25 маршрут от машины разработчика до Timeweb оборвался на транзитном IX: недоступны оба сервера сети (`hub` и `auth`), при этом сторонний российский хостинг отвечал, а с узлов tailnet владельца прод отдавал 200 — то есть ломалась дорога, а не сервер. `SSH_JUMP=root@<узел>` подставляет `ssh -J` в ssh И rsync; пустой по умолчанию, обычный деплой не меняет. Диагностика в такой ситуации: `traceroute` до обоих IP (обрыв на одном хопе = проблема сети провайдера), `whois` сетей, проверка прода с любого стороннего узла.

**Тяжёлые локальные артефакты исключены из rsync поимённо** (`deploy/deploy.sh`): `LMS/`,
`import_bundle`, `weeek-bundle`, `.weeek-cache`, `redesign`, `'Hub Instructions'`. Бандл переноса
из WEEEK — 377 МБ, без строки в `--exclude` он уезжал бы на VPS каждым деплоем; на сервер он
кладётся отдельным `rsync` в `/opt/signaris-hub[-staging]/weeek-bundle/`.

**Пути с пробелом в `--exclude` пишутся `--exclude="'Имя с пробелом'"`.** rsync зовётся через `eval`, и одинарные кавычки обязаны пережить ПЕРВЫЙ разбор строки — иначе имя распадается на два аргумента, rsync ругается на несуществующий путь и молча уносит папку на сервер (так `Hub Instructions/` уехала на staging 25.08).

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
   Суточные дампы — в `/opt/signaris-hub/backups/daily/`. Это **`pg_dump -Fc`, поверх которого ещё раз `gzip -9`**, а НЕ plain SQL: `psql` его не примет, а `pg_restore` без `gunzip` отвечает «input file does not appear to be a valid archive» (здесь до 31.08 стояло неверное `zcat … | psql`). Правильно так:
   ```bash
   gunzip -c /opt/signaris-hub/backups/daily/db-signaris_hub_db-<date>.sql.gz |
     sudo -u postgres pg_restore --clean --if-exists -d signaris_hub_db
   ```

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

**In-process воркеры (lifespan `app/main.py`, `worker_supervisor.supervise` — рестарт с backoff + Redis leader-lock; systemd-юнитов у них НЕТ):**
- **deletion-sync** — фид удалений/переименований auth, poll 60 c; курсор `sync_state(key='deletion_sync')`.
- **staff-sync** (0052) — pull штата, 15 мин; гейт `STAFF_SERVICE_KEY` + `STAFF_SYNC_ENABLED` (staging выключен навсегда — общий VAPID).
- **sid-sync** — фид ревокаций SSO-сессий; in-memory store блокирует `--workers > 1`.
- **sites-sync** (0053) — воркера НЕТ СОЗНАТЕЛЬНО (данные меняются ~4 раза в год): только ручной `POST /api/learn/sites/sync` под advisory-локом.

**Cron timers (due-soon hourly / overdue daily 09:00 MSK):** есть в обоих env — prod (`signaris-hub-{due-soon,overdue}.timer`) и staging (`signaris-hub-staging-{due-soon,overdue}.timer`).

**Cron timers (общие для prod+staging, 3.6.8):**
- `signaris-hub-backup.timer` — 00:00 UTC daily, один run для обеих БД, `User=postgres`. Файлы в `/opt/signaris-hub/backups/daily/db-<db>-<date>.sql.gz`, Sunday hardlink → `weekly/`. Optional S3 offsite через `/etc/default/signaris-hub-backup` (BACKUP_S3_BUCKET + AWS creds).
- `signaris-hub-backup-cleanup.timer` — 00:30 UTC daily, **`User=root`**. Дампы чистятся по mtime (14d daily + 42d weekly), снапшоты вложений и архивы ключей — **по ИМЕНИ каталога, 14 штук**: `rsync -a` переносит на снапшот mtime исходного каталога, и `-mtime` находил там ВСЕ снапшоты разом, включая свежий (31.08). Цель симлинка `latest` не удаляется никогда — иначе `backup-files.sh` молча уходит в полный rsync без `--link-dest`.
- `signaris-hub-backup-secrets.timer` — 00:20 UTC daily, root. Зашифрованный (gpg AES256) архив того, чего нет в git: оба `.env`, `vapid_private.pem`, `/etc/default/signaris-hub-*`. Пароль — `BACKUP_SECRETS_PASSPHRASE` в `/etc/default/signaris-hub-backup` и **обязательным дублем в CLAUDE.md → СЕКРЕТЫ**.
- `signaris-hub[-staging]-course-due-soon.timer` — daily 06:15 UTC, напоминание о дедлайне назначенного курса (`app/jobs/course_due_soon.py`); включён на обоих env.
- `signaris-hub[-staging]-automations.timer` — hourly :20, исполнение automation_jobs чанком 200 (`app/jobs/automations_run.py`); включён на обоих env.
- `signaris-hub[-staging]-inactivity.timer` — daily 07:00 UTC, правило неактивности warn→grace→авто-архив (`app/jobs/inactivity.py`); включён на обоих env.
- `signaris-hub[-staging]-extraction.service` — long-running воркер извлечения текста + RAG-reconcile (Ф6, без таймера); включён на обоих env.
- `signaris-hub-healthcheck.timer` — `OnUnitActiveSec=5min`, state-files в `/var/lib/signaris-hub/health.<url>.state`, edge-trigger email через `mail(1)` на 2 consecutive failures (`/etc/default/signaris-hub-healthcheck::HEALTHCHECK_ALERT_EMAIL`).
- `signaris-hub-backup-files.timer` — 00:15 UTC daily, root, rsync --link-dest снапшоты attachments обоих env в `backups/files/<env>/<date>` (retention 14д в backup-cleanup).
- `signaris-hub[-staging]-review-due.timer` — 06:30 UTC daily, напоминания владельцам материалов (`app/jobs/review_due.py`); включён на обоих env.

## nginx-инварианты

локации `/api/*` и `/_protected_media/` ОБЯЗАНЫ иметь `^~` (иначе статик-regex перехватывает media → 404); media-локации (`/api/media/`, `/_protected_media/`) переиздают ПОЛНЫЙ набор security-заголовков с `X-Frame-Options SAMEORIGIN` + CSP `frame-ancestors 'self'` и БЕЗ `sandbox` (первый `add_header` в локации сбрасывает server-level набор; server-DENY убьёт PDF-iframe уроков); `location ^~ /api/ai/` — `proxy_read_timeout 120s` и без `add_header`; локация, которая переиздаёт заголовки И отдаёт SPA (`/p/`), обязана заканчивать `try_files $uri /index.html =404;` кодом, а не URI (иначе внутренний редирект теряет `Referrer-Policy: no-referrer`); `Permissions-Policy: microphone=(self)` во ВСЕХ дублях строки, кроме `/p/`; правка анти-FOUC скрипта темы в `index.html` требует пересчёта sha256 в CSP (`ops/nginx/hub-security-headers.conf`); шрифты self-hosted (`web/src/assets/fonts/`); staging обязан иметь `SIGNARIS_HUB_PUBLIC_BASE_URL`.

**Потолок тела задаёт ЛОКАЦИЯ, а локацию нельзя навесить на путь с UUID (15.09).** Server-level `client_max_body_size` — 25 МБ; всё, что грузится крупнее, обязано иметь свой адрес БЕЗ переменных: `location = /api/learn/media` (350m) и `location = /api/attachments` (1100m, видео во вложениях). Regex-локация под `/api/tasks/{uuid}/attachments` не помогла бы — модификатор `^~` у `location ^~ /api/` **отменяет проверку regex-локаций**, блок прошёл бы `nginx -t` и не сработал никогда; поэтому ручка загрузки вложений и переехала на фиксированный `POST /api/attachments` с `task_id` в теле формы. Поднимать потолок всему `^~ /api/tasks/` нельзя — это разрешило бы гигабайтное тело в `PATCH /tasks/{id}`. У обеих upload-локаций `proxy_request_buffering off` (иначе nginx пишет тело на диск сам — лишняя копия) и увеличенный `proxy_read_timeout`. Отдача вложений — `location ^~ /api/attachments/` с зоной `hub_media` (перемотка видео это серия Range-запросов; в общей `hub_api` они ловят 429); локация накрывает ТРИ ручки (отдача, `/download`, `DELETE`), поэтому набор `proxy_set_header` в ней обязан быть полным. Под саму отдачу файла менять ничего не нужно: `^~ /_protected_media/` уже алиасит весь `attachments_root`.

**Инструкции по Hub (`/guides/`, 25.08).** Две автономные HTML-страницы лежат в `guides/` в корне репо и приезжают обычным backend-rsync'ом в `/opt/signaris-hub[-staging]/guides/`. Отдаёт их `GET /api/guides/{kind}?e&s` (подпись как у медиа) через internal-локацию `^~ /_guides/` — публичной статикой класть нельзя: внутри реальные экраны с ФИО сотрудников и адресами точек. У локации СВОЙ набор заголовков с ослабленным `script-src 'self' 'unsafe-inline'` (у инструкции свой inline-скрипт: поиск по документу и отметки о прочтении) и `connect-src 'none'`; `~^/api/guides/` исключён из access_log — подписанная ссылка это capability. На staging обязателен `SIGNARIS_HUB_GUIDES_ROOT` в `.env` (как `ATTACHMENTS_ROOT`). Правка конфигов деплоем НЕ применяется: `scp` в `/etc/nginx/sites-available/`, `nginx -t`, `systemctl reload nginx`. Обновление самих инструкций — `scripts/sync_guides.py --apply`: копирует под фиксированными именами, проверяет совместимость с этой CSP (никакого `eval`/`new Function`, `blob:`, сети и соседних файлов — присланная 25.08 bundler-сборка нарушала всё сразу и молча теряла поиск с лайтбоксом) дописывает неприметный скроллбар как в сайдбаре Hub и плавающую ссылку «Вернуться в Hub» (в PWA на домашнем экране инструкция открывается ТЕМ ЖЕ окном — браузерной обвязки нет, выйти нечем; в обычной вкладке она новая, и её «Назад» тоже пуста).

## Память VPS: STT и сборка фронта

Машина — **3,8 ГБ без swap** (замер 16.09: `free -h` 3.8Gi, ядро `Memory: 3970312K/4193764K available`, `swapon --show` пуст). До 15.09 в этом файле и в CLAUDE.md значилось «2 ГБ» — неверно; было ли это опечаткой или машину расширили при перезагрузке 01.09, установить не удалось: kernel-строки предыдущей загрузки (29.06) вытеснены ротацией журнала. Августовские записи про OOM сборки поэтому оставлены как есть.

STT-юнит — пара `MemoryHigh=800M` + `MemoryMax=1100M` (одиночный `MemoryMax` ловит OOM на странице кэша весов) + выгрузка модели по 5 мин простоя; **одна STT-машина на хост** — включён ПРОД, staging-юнит disable-нут; staging-юниты собирать `ops/systemd/make-staging-unit.py`. `vite build` на VPS больше не запускается — `deploy.sh` собирает фронт локально и заливает `web/dist` (сборка на сервере росла до ~970 МБ RSS и падала по OOM).

## Offsite-бэкап (Timeweb S3, 01.09)

Бакет `signaris-hub-backups`, класс «Холодный», приватный. Клиент — `rclone` из
apt: `awscli` в Ubuntu 24.04 отсутствует как пакет, а вендорный установщик тянет
~250 МБ ради одной команды.

**Конфиг лежит в `/etc/signaris-hub-rclone.conf` (640 root:postgres), а не в
`/root`:** `signaris-hub-backup.service` бежит от `postgres` (peer-auth для
`pg_dump`), и rclone искал бы конфиг в `/var/lib/postgresql`. Путь задан
`RCLONE_CONFIG=` в `/etc/default/signaris-hub-backup`; у root — симлинк на тот
же файл, чтобы копия кредов была одна.

Что уезжает и что нет:

| Раздел | Что | Почему так |
|---|---|---|
| `db/` | дампы **прода** | staging воспроизводим, и это вторая копия тех же ПДн |
| `attachments/` | ТОЛЬКО последний снапшот прода | hardlink'и в S3 не переживают: все 14 копий уехали бы как ~21 ГБ вместо 1,5 |

**Локальные снапшоты — тоже только прод (15.09).** `backup-files.sh` снимал ещё и вложения staging, и это стоило 3,8 ГБ из 5,3 ГБ всего дерева снапшотов — при том что offsite их никогда не возил, а восстанавливать тестовый стенд из бэкапа никто не собирался. Место понадобилось под видео во вложениях. Уже накопленные снапшоты staging скрипт НЕ удаляет: снять их разово, убедившись, что прод на месте —

```bash
du -sh /opt/signaris-hub/backups/files/*          # что есть сейчас
ls /opt/signaris-hub/backups/files/signaris-hub   # прод обязан быть непустым
rm -rf /opt/signaris-hub/backups/files/signaris-hub-staging
```
| `secrets/` | зашифрованные архивы ключей | единицы килобайт |

**Везде `rclone copy`, а не `sync`.** Синхронизация отражала бы локальную
ротацию в бакет, и любая беда с локальным каталогом (пустой том, ошибка в
ретенции) стёрла бы offsite-копию — ровно то, ради чего она существует. Цена:
удалённые вложения остаются в бакете сиротами, но их мало. Побочный плюс: в
бакете история дампов длиннее локальных 14 дней.

**Ручной запуск `backup-files.sh` offsite НЕ делает** — `BACKUP_S3_REMOTE`
приезжает из `EnvironmentFile`, который читает systemd. Гонять через
`systemctl start signaris-hub-backup-files.service`.

Первая заливка 01.09: 1320 объектов, 1,42 ГиБ, ~1 минута.

## Репетиция восстановления

Бэкап, из которого ни разу не разворачивались, — гипотеза. `scripts/restore-check.sh`
проверяет её целиком: разворачивает дамп во ВРЕМЕННУЮ базу `restore_check_<ts>`,
сверяет и сносит её (`trap` на выходе, имя собирается только из литерала и метки
времени — снаружи в `DROP DATABASE` не попадает ничего).

```bash
ssh root@94.241.168.8
/opt/signaris-hub/scripts/restore-check.sh \
  /opt/signaris-hub/backups/daily/db-signaris_hub_db-$(date +%F).sql.gz
```

Что проверяется и почему именно это:

- `pg_restore` без единой ошибки;
- **`alembic_version` совпадает с живой базой** — дамп «полный, но от старой
  схемы» иначе выглядит совершенно здоровым;
- `projects`, `tasks`, `employee_profiles`, `task_comments` непусты, счётчики
  печатаются рядом с живыми (живые больше на дневной прирост — это норма);
- **есть RLS-политики** — они восстанавливаются отдельно от таблиц, и дамп без
  них работает ровно до первого кросс-tenant запроса.

Первый прогон — 31.08.2026: 0 ошибок, alembic 0049 = 0049, 82 политики,
16 802 задачи против 16 813 живых. На таймер сознательно не повешено: пусть
остаётся осознанным действием, а не фоном, который никто не видел вживую.

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

**Свободное место (15.09).** Тот же скрипт проверяет диск: `HEALTHCHECK_DISK_PATH` (default `/`) и `HEALTHCHECK_DISK_MIN_GB` (default 8). До этой правки проверки диска не было вовсе, и единственной защитой оставался statvfs-порог на загрузке медиа — то есть о заканчивающемся месте узнавали бы в момент, когда сотрудник уже получил отказ. Порог 8 ГБ выше порога отказа загрузки (`media_min_free_bytes` 5 ГБ + размер файла), чтобы алерт пришёл ДО того, как загрузки начнут отбиваться. Триггер краевой (состояние в `/var/lib/signaris-hub/disk.*.state`) — иначе сообщение уходило бы каждые 5 минут и его перестали бы читать. Проверка без ожидания реального заполнения: `HEALTHCHECK_DISK_MIN_GB=999 /opt/signaris-hub/scripts/healthcheck.sh` → алерт, затем обычный запуск → recovery.

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

## Ключевые env-переменные (`SIGNARIS_HUB_*`, полный список — `app/config.py`, 57 полей)

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
| `DELETION_SYNC_ENABLED` / `SIGNARIS_SERVICE_KEY` | deletion-sync из auth (тот же общий ключ — у sid-sync) |
| `STAFF_SERVICE_KEY` | **отдельный** ключ метки hub (штат + реестр объектов): ошибка в общем ключе молча отняла бы отзыв SSO-сессий. Значение — CLAUDE.md → СЕКРЕТЫ |
| `STAFF_SYNC_ENABLED` / `STAFF_SYNC_INTERVAL_SEC` | pull-воркер штата (0052), 15 мин; **staging=false навсегда** — VAPID общий с прод, bootstrap-залп по staging-копии подписок ушёл бы на реальные устройства |
| `SITES_SYNC_ENABLED` | зеркало реестра объектов (0053): планировщика НЕТ, флаг гейтит живой прогон ручного `POST /api/learn/sites/sync` (false = форс dry-run) |
| `SITES_SNAPSHOT_FRESH_DAYS` | свежесть снимка зеркала, фиксированные сутки (14): протухло → карточки магазинов показывают локальные поля с меткой |
| `ATTACHMENTS_ROOT` / `ATTACHMENT_MAX_BYTES` | корень файлов (вложения задач + learn-медиа), лимит вложений задач |
| `ATTACHMENT_VIDEO_MAX_BYTES` | отдельный потолок видео во вложениях (default 1 ГБ). Меняется ВМЕСТЕ с `client_max_body_size` у `location = /api/attachments` и с зеркалом `web/src/lib/attachmentTypes.ts` |
| `VAPID_PUBLIC_KEY` / `VAPID_PRIVATE_KEY_PATH` / `VAPID_SUBJECT` | Web Push |
| `SENTRY_DSN` | включает Sentry backend (+frontend через /api/env); пока не задан |
| `PUBLIC_LINKS_ENABLED` | feature-flag публичных ссылок (default true) |
