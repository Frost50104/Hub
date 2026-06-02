# Tech debt

Открытые вопросы, упрощения и known-issues. Заполняется по мере накопления.

## Открытое

- **Множественные uvicorn-воркеры опрашивают deletion-sync N раз.** В MVP крутим `--workers 1`. При масштабировании — Redis leader-election (см. `INTEGRATION.md` шаг 14, шаблон `try_acquire_lock`).
- **VAPID-ключ единый для prod+staging.** Удобно (как у Desk), но если staging-баг утечёт public key, теоретически prod-подписки можно подделать. Низкая вероятность. Раздельные ключи — future work.
- **LexoRank-style `tasks.position NUMERIC`** может «насыщаться» при многих DnD-миграциях карточек. При дельте <0.001 — фоновый rebalance колонки в PATCH-хендлере (реализуется в MVP.3).
- **Подзадачи только 1 уровень** (`parent_task_id` CHECK depth=1). Глубже потребует tree-CTE в запросах и отдельной миграции.
- **Email-коллизии между tenant'ами в `shadow_users`** — для пустого старта Hub проблемы нет; если когда-то будем мигрировать данные, нужен pre-migration report (см. `INTEGRATION.md` шаг 12).
- **Sentry не подключён.** Backend SDK инициализируется только если `SIGNARIS_HUB_SENTRY_DSN` задан в `.env` — сейчас пусто, прод-баги уходят в `journalctl -u signaris-hub`. Frontend SDK (`@sentry/react` + Replay) ставится на старте через `lib/sentry.ts::initSentry` если `/api/env` отдал DSN — тоже не вызывается. **Решено отложить в финал.** Реальные варианты на нашем VPS (2 CPU / 2 GB RAM): (a) Sentry.io free tier — 5k events/мес, нужна регистрация; (b) GlitchTip self-hosted (Sentry-API-совместимый, Django+Postgres+Redis+Celery, ~500-800 MB RAM, влезает на наш VPS); (c) апгрейд VPS до 16 GB RAM под официальный Sentry self-hosted (15 контейнеров, Kafka+ClickHouse). По умолчанию приоритет — GlitchTip на `sentry.signaris.ru`.
- **nginx `add_header` gotcha + Referrer-Policy для `/p/`.** Server-level security headers молча отменяются first `add_header` в location — обошли через include-snippet `hub-security-headers.conf`. Для `/p/{token}` запросов `try_files /index.html` делает internal-redirect в `location = /index.html` и хeders идут оттуда (Referrer-Policy = `strict-origin-when-cross-origin` вместо желаемого `no-referrer`). Компенсировано per-page `<meta name="referrer" content="no-referrer">` в `PublicViewPage.tsx`. Серверный override — named location или копия `index.html` под другим именем под /p/ root.
- **Healthcheck email alerts требуют MTA на VPS.** `scripts/healthcheck.sh` шлёт `mail -s ... $HEALTHCHECK_ALERT_EMAIL`, но `mail(1)` не установлен. Чтобы включить: `apt install mailutils` + конфиг postfix/ssmtp. Сейчас alerts пишутся только в `journalctl` (`logger -t signaris-hub-health`).
- **S3 offsite backup** — флаг `BACKUP_S3_BUCKET` поддерживается в `scripts/backup-pg.sh`, но aws-cli не установлен и креды не настроены. При потере VPS-диска восстановление невозможно без offsite-копии. Минимум — настроить snapshot у VPS-провайдера.

## Упрощения MVP

- ~~Поиск без DSL-фильтров (только базовый title-like).~~ Закрыто в 3.6.11 (FTS + DSL `assignee:me status:in_progress due:<DATE "phrase"`, group_by=project).
- ~~Кастом-статусы / кастом-поля задач — отсутствуют.~~ Custom-поля закрыты в 3.6.10 (7 типов). Кастом-статусы — open (Asana workflow rules).
- ~~Гости (внешние пользователи) и публичные ссылки — отсутствуют.~~ Public links закрыты в 3.6.12 (view-only по UUID-токену). Guests с email-приглашением — open (требует scope `hub:guest` в auth.signaris.ru).
- Time tracking — отсутствует.
- ~~Calendar / Timeline / Gantt — отсутствуют.~~ Calendar закрыт в 3.6.9 (месячная сетка с DnD). Timeline/Gantt — open (XL, отложено в Phase 4).

## Открытое — Phase 4 backlog (после 3.6.x)

- **Timeline / Gantt view** — XL по сложности (`task_dependencies` миграция, scale day/week/month/quarter, drag-боков, либа vs custom SVG). Calendar + Custom fields покрывают 90% планирования; делаем только по явному запросу.
- **Guests** — email-приглашения внешних пользователей с view/comment-доступом к конкретному проекту. Блокер: нужна фича в `auth.signaris.ru` (новый scope `hub:guest`, JWT-claim `is_guest`, tenant_id хоста для гостя).
- **Saved searches** — сохранить DSL-запрос как «фильтр» / smart-list. Лёгкая надстройка над 3.6.11.
- **FTS по комментариям в SearchPage** — GIN-индекс `ix_task_comments_body_fts` готов с 3.6.11, но UI не использует. Добавить вторую секцию `comments` рядом с `tasks` в `SearchResponseGrouped`.
- **Highlight matches в результатах поиска** — через `ts_headline('russian', text, tsquery)`.
- **Cmd+K hotkey** — global keyboard listener в Sidebar для фокуса в search-input.
- **viewConfig store + custom-fields-колонки в TaskRow (List view)** — zustand persist per-project конфиг видимости колонок. Сейчас custom fields видны только в drawer, не в List view.
- **CF-фильтры в `GET /tasks?cf_<field_id>=<value>`** — server-side JSONB filters через GIN-индекс. Backend готов, добавить query-param parser.
- **UI rename полей в `CustomFieldsManager`** — API PATCH name готов, UI только Delete+Create.
- **Drag-to-reorder definitions** — @dnd-kit + PATCH position.
- **Comment-section в project public view** — на `/p/{token}` для project-скоупа сейчас видны только заголовки задач, без комментов.
- **Security headers full fix для `/p/`** — named location или rewrite-rule чтобы `Referrer-Policy: no-referrer` применялся server-side, не через `<meta>`.
- **Email-уведомления fallback** — когда push не работает (не PWA, не Chrome, не разрешил). Через SMTP в `app/services/push_sender.py`.
- **i18n** — сейчас русский hard-coded. UPPETIT — RU-only, но multi-tenant в будущем потребует.
- **Audit log на admin-действия** — кто добавил/удалил project_member, кто архивировал проект, кто отозвал public link. Расширить `task_activity` или новую `admin_audit_log`.
- **Workflow/automation rules** — Asana-эквивалент (при изменении статуса → action). Большой scope.
- **Reports/Dashboard** — workload, completed tasks, burndown. Asana Dashboards.

## Решённое в MVP

- Single-flight refresh — реализуется через `attachAxiosAuth` из `@signaris/auth-client/browser` (не пишем вручную).
- Rate-limit Redis + DB fallback — копия из `CentralAuthService/app/security/rate_limit.py`.
- iOS PWA-freeze таймеров в фоне — лечится через `visibilitychange`-trigger проверки SW в `UpdateBanner.tsx`.
