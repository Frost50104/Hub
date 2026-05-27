# Architecture

## Принципы

1. **Единая авторизация.** Никакого собственного логина — только SSO через [auth.signaris.ru](https://auth.signaris.ru) по чек-листу `CentralAuthService/client-libs/INTEGRATION.md` (13 шагов + §14 deletion-sync). Без per-product «снежинок».
2. **Multi-tenancy через RLS.** Каждая бизнес-таблица — `tenant_id UUID NOT NULL` + Postgres-policy. Приложение работает от non-superuser-роли (RLS реально enforced), миграции — от migrate-роли (BYPASSRLS).
3. **Shadow-таблицы.** `shadow_tenants` + `shadow_users` (с `deleted_at TIMESTAMPTZ NULL`) апсертятся на каждый authenticated-запрос. Доменные FK ссылаются на `shadow_users.employee_id` — не на JWT.sub.
4. **Deletion-sync.** Воркер `run_deletion_sync_worker` (lib ≥ 0.4.0) в lifespan тянет события из `auth.signaris.ru/api/products/deletions`. `on_event` — no-op (история тасков сохраняется); списки сотрудников фильтруются `WHERE shadow_users.deleted_at IS NULL`.

## Backend

- **FastAPI** async + lifespan: JWKS-warmup, Redis pool, deletion-sync worker, Sentry init (опц.)
- **`tenant_scoped_session(tenant_id, *, bypass_rls)`** — async ctx manager (`app/db.py`), копия из `CentralAuthService/app/db.py:62-120`. Устанавливает `SET LOCAL app.tenant_id` или `SET app.bypass_rls = 'on'` для системных воркеров.
- **`require_auth = build_require_auth(verifier)`** — `signaris-auth-client.TokenVerifier` валидирует RS256-JWT по JWKS. Никакой собственной валидации.
- **Shadow upsert middleware** — после `require_auth`: `upsert_shadow_tenant(db, principal)` + `upsert_shadow_user(db, principal)` + commit.

## Frontend (PWA)

- **React 18 + TS strict** + Vite + `vite-plugin-pwa` (`registerType: 'prompt'`, `strategies: 'injectManifest'`).
- **Auth:** `createSsoAuthClient({...})` из `@signaris/auth-client/browser` + `attachAxiosAuth(api, authClient)`. Refresh-token — в IndexedDB (PWA standalone), access-token — в памяти через zustand.
- **Service Worker:** `web/src/sw.ts` — precache + push handler + notificationclick + SKIP_WAITING-message.
- **Update mechanism:** `UpdateBanner.tsx` проверяет SW каждые 60с + на `visibilitychange` — лечит iOS PWA-freeze таймеров в фоне.

## Сущности

### Контейнеры
- `Workspace = tenant_id` (из JWT, без своей таблицы)
- `projects` (id, tenant_id, key, name, description, archived_at, created_by)
- `project_members` (project_id, employee_id, role: `owner` | `editor` | `viewer`)
- `sections` (project_id, name, position)

### Задачи
- `tasks` (project_id, section_id, parent_task_id, title, description markdown, status: `todo` | `in_progress` | `in_review` | `done`, priority: `low` | `medium` | `high` | `urgent`, assignee_id, due_at, position NUMERIC)
  - Подзадачи только 1 уровень — CHECK `parent_task_id IS NULL OR (SELECT parent_task_id FROM tasks t2 WHERE t2.id = parent_task_id) IS NULL`
- `task_watchers` — auto-добавление: assignee + creator + mentioned
- `task_comments` (markdown, `mentioned_ids UUID[]`)
- `task_labels`, `task_label_assignments`
- `task_attachments` (whitelist mime, 20 MB)
- `task_activity` (append-only event log)

### Уведомления
- `push_subscriptions` (employee_id, endpoint UNIQUE, p256dh, auth, user_agent)
- `notifications` (in-app Inbox)
- `notification_preferences` (employee_id, prefs JSONB) — пользователь выключает типы

### Служебное
- `shadow_tenants`, `shadow_users`
- `sync_state` (deletion-sync cursor)
- `rate_limits` (DB-fallback для Redis)

## Push-триггеры (MVP)

- `task.assigned_to_me` — мне назначили задачу
- `task.mentioned` — упомянули в комментарии
- `task.commented_on_watched` — комментарий на наблюдаемой задаче
- `task.status_changed_on_watched` — статус изменён
- `task.due_soon` — за 24ч до дедлайна (cron hourly)
- `task.overdue` — просрочена (cron daily 09:00 MSK)

Подробнее — `docs/PUSH.md`.

## Темы

- **Тёмная** — буквальный порт CSS-переменных из `IT_startup/index.html:18-30` (амбер `#FFB200`, фон `#08080E`, glass-эффект).
- **Светлая** — спроектирована с нуля. Палитра согласована на границе Hub-MVP.1.
- Переключатель System/Light/Dark в Topbar (`web/src/components/layout/ThemeToggle.tsx`). Default — `prefers-color-scheme`.

## Безопасность

- JWT claims читаются **только** через `signaris-auth-client` — никакого ручного `jwt.decode`.
- CORS на backend разрешает только `https://hub.signaris.ru` и `https://hub-staging.signaris.ru`.
- Rate-limit через Redis (с DB-fallback): паттерн скопирован из `CentralAuthService/app/security/rate_limit.py`.
- Refresh-cookie общий на `.signaris.ru`. Для PWA standalone (iOS) — режим `X-Auth-Mode: api`, refresh-token в IndexedDB.
