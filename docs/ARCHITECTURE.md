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
- `tasks` (project_id, section_id, parent_task_id, title, description markdown, status: `todo` | `in_progress` | `in_review` | `done`, priority: `low` | `medium` | `high` | `urgent`, assignee_id, start_at, due_at, position NUMERIC, search_vector tsvector)
  - Подзадачи только 1 уровень — CHECK `parent_task_id IS NULL OR (SELECT parent_task_id FROM tasks t2 WHERE t2.id = parent_task_id) IS NULL`; UI — секция в карточке (SubtaskList), в топ-уровне List/Board не показываются
- `task_watchers` — auto-добавление: assignee + creator + mentioned
- `task_comments` (markdown, `mentioned_ids UUID[]`)
- `task_labels` (name, color) + `task_label_assignments` (с tenant_id и RLS с миграции 0011); API `app/api/labels.py`, чипы в List/Board/drawer, фильтр
- `task_attachments` (whitelist mime без SVG, 20 MB)
- `task_activity` (append-only event log)
- `task_dependencies` (predecessor/successor, finish-to-start, BFS cycle-check `app/services/dependency_cycle.py`, миграция 0010) — стрелки на Timeline
- `custom_field_definitions` + `task_custom_field_values` (7 типов, миграция 0007) — колонки List, агрегаты Dashboard
- `public_share_tokens` (scope task|project, БЕЗ RLS — cross-tenant lookup по токену, миграция 0009) — view-only `/p/{token}`
- `project_members.is_favorite` (миграция 0012) — личное избранное, секция в Sidebar

### Представления проекта
Список / Доска / Календарь (`app/api/calendar.py`) / Хронология (`app/api/timeline.py`) / Дашборд (`app/api/stats.py`, recharts lazy-chunk) / Участники. Фильтры (assignee/status/priority/label/due) + сортировка списка — состояние в URL searchParams; Board всегда в position-порядке. Полнотекстовый поиск: `app/api/search.py` + DSL `app/services/search_dsl.py` (0008: pg_trgm, tsvector). Мутации задач оптимистичные (rollback из снапшота, `useUpdateTask`), complete/archive — с undo-тостом.

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
- Переключатель Светлая/Тёмная — в Настройках → «Оформление» (`web/src/components/ThemeToggle.tsx`). Default — тёмная, `data-theme` на `<html>` всегда явный (режима System нет). Палитра recharts на дашборде читается из CSS-токенов при смене темы.

## Безопасность

- JWT claims читаются **только** через `signaris-auth-client` — никакого ручного `jwt.decode`.
- CORS на backend разрешает только `https://hub.signaris.ru` и `https://hub-staging.signaris.ru`.
- Rate-limit через Redis (с DB-fallback): паттерн скопирован из `CentralAuthService/app/security/rate_limit.py`.
- Refresh-cookie общий на `.signaris.ru`. Для PWA standalone (iOS) — режим `X-Auth-Mode: api`, refresh-token в IndexedDB.
