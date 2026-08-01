# Roadmap

> **Историческая справка.** Всё перечисленное здесь ВЫПОЛНЕНО и в проде: Hub-MVP.1..6, Phase 3.6.7-4.9, коммерциализация 1-2-4, LMS Ф0..Ф8 (аттестации), QA-фиксы 2026-07-21. Актуальный статус — `CLAUDE.md` §«Текущая фаза»/«Статус», журнал — `SESSIONS.md`. Статусы 🚧 ниже относятся к периоду MVP и давно не отражают реальность.

Hub-MVP — 6 итераций. На границе каждой — контрольная точка с пользователем (показ staging-домена или артефакта).

## Hub-MVP.1 — Skeleton + Auth + согласование палитры

🚧 **In progress.**

- Backend: FastAPI + Alembic baseline (shadow_tenants, shadow_users, sync_state, rate_limits) + `tenant_scoped_session` + `signaris-auth-client` интеграция (`TokenVerifier`, `require_auth`, shadow upsert middleware).
- Frontend: Vite + TS strict + Tailwind + brand.css (тёмная тема из `IT_startup`) + Welcome.tsx с JWT-claims.
- `CLAUDE.md` / `SESSIONS.md` / `README.md` / `.gitignore` / `docs/`.
- `deploy/deploy.sh` форк из `AXO_bot_web`.

**✦ Контрольная точка:** агент показывает таблицу значений светлой темы (`--bg`, `--surface`, `--text`, `--text2`, `--text3`, `--glass`, тени для карточек на белом фоне). Пользователь подтверждает — значения попадают в `web/src/styles/brand.css` под `[data-theme="light"]`.

## Hub-MVP.2 — Project / Section / Task / Member CRUD

- Миграция 0002: `projects`, `project_members`, `sections`.
- Backend: CRUD + RBAC owner/editor/viewer (внутри-проектные роли, не JWT).
- Frontend: `ProjectListPage` (карточки в `.glass`), `ProjectPage` (только таб «Список»), `MyTasksPage`.
- shadcn-style UI-примитивы (`Button`, `Input`, `Dialog`, `DropdownMenu`, `Avatar`, `Badge`, `Toast`).

## Hub-MVP.3 — Канбан + Comments + Watchers + Activity + @mentions

- Миграция 0003: `tasks` полная, `task_watchers`, `task_comments`, `task_labels`, `task_label_assignments`, `task_activity`.
- `@dnd-kit/core` канбан (Board / Column / TaskCard / DragOverlay, optimistic update).
- `mention_parser.py` — regex `@<local-part>` lookup по `shadow_users.email` (`deleted_at IS NULL`).
- `MentionInput.tsx` (popover-предложения), `ActivityFeed.tsx`.

## Hub-MVP.4 — Push + UpdateBanner + IOSInstallBanner + светлая тема

- Миграция 0004: `push_subscriptions`, `notifications`, `notification_preferences`.
- `push_sender.py` (`pywebpush`), `notification_dispatcher.py` (5 триггеров), cron-jobs `due_soon` (hourly) и `overdue` (daily 09:00 MSK) + systemd timers.
- `sw.ts` / `usePush.ts` / `UpdateBanner.tsx` / `IOSInstallBanner.tsx` — TS-порты из `AXO_bot_web/frontend/src/`.
- Светлая тема (согласованная в MVP.1) + `ThemeToggle` (System / Light / Dark) в Topbar.

## Hub-MVP.5 — Attachments + Sentry + mobile + полировка

- `task_attachments` + multipart upload (whitelist mime: `image/png|jpeg|webp`, `application/pdf|zip|msword`, doc/xlsx, `text/plain`; 20 MB; nginx `client_max_body_size 25M`).
- Sentry backend (`sentry_sdk` + `FastApiIntegration` + `SqlalchemyIntegration`) + frontend (`@sentry/react` + `browserTracingIntegration` + `replayIntegration`). DSN через `GET /api/env`.
- Mobile responsive: off-canvas sidebar `<md`, horizontal kanban scroll с snap, TaskDetail fullscreen `<md`.
- A11y: фокус-rings, role на DnD, contrast AA для светлой темы.

## Hub-MVP.6 — Prod-деплой + регистрация UPPETIT

- `bootstrap-vps.sh` на `94.241.168.8` → DNS → `certbot --nginx`.
- В env auth-prod: `SIGNARIS_AUTH_CORS_ORIGINS += https://hub.signaris.ru` + `SSO_REDIRECT_ORIGINS`.
- В `CentralAuthService/app/constants/products.py:91`: `INTEGRATED_PRODUCTS += {"hub"}`.
- UPPETIT-tenant → `purchased_products += ["hub"]`, владелец → `hub:admin` через RoleEditor.
- Получить service-key для deletion-sync → `/opt/signaris-hub/.env`.
- Smoke-test: SSO-вход без второго логина, создание проекта/таска, push на iPhone PWA standalone.

## Отложено на Phase 3.6.x (при запросе)

- 3.6.1: Asana CSV-импорт
- 3.6.2: Calendar / Timeline / Gantt
- 3.6.3: Custom-поля задач
- 3.6.4: Гости + публичные ссылки
- 3.6.5: Time tracking
- 3.6.6: Полнотекстовый поиск с DSL

## Phase 3.6.7 … 4.9 — история (всё выполнено, в проде)

Детали фаз, вынесенные из hot-конспекта `CLAUDE.md` при синке 2026-07-31:

- ✅ **Phase 3.6.7** — Polish (mobile responsive, Sentry frontend + ErrorBoundary, a11y, /settings/notifications). Backend prefs формат расширен с `{kind: bool}` на `{kind: {push, in_app}}` с обратной совместимостью.
- ✅ **Phase 3.6.8** — Production infra: pg_dump systemd-timer @ 00:00 UTC (оба DB, retention 14d+6w, optional S3 offsite через `BACKUP_S3_BUCKET`), nginx security headers (HSTS + DENY + nosniff + CSP с whitelist auth.signaris.ru + *.ingest.sentry.io + 'wasm-unsafe-eval'), rate-limit per-user (`task:write` 120/мин, `search` 60/мин, `attach:upload` 30/мин, `comment:write` 60/мин) через `app/deps.py::enforce_rate_limit`, GitHub Actions CI (ruff + pytest -m "not integration" + tsc + npm build), healthcheck timer @ 5min с edge-trigger email на 2 consecutive failures.
- ✅ **Phase 3.6.9** — Calendar view. Миграция 0006 `tasks.start_at TIMESTAMPTZ NULL` + partial indexes. Router `app/api/calendar.py` (GET `/api/projects/{id}/tasks/calendar?from=&to=`, MAX 92 дня, range-overlap). Frontend `web/src/components/calendar/{CalendarView,CalendarCell,CalendarTaskBar}.tsx` — 6×7 grid, понедельник первый день, DnD `task-${id}|${sourceDay}` → `cal-${targetDay}` с offset-based PATCH (due_at + start_at если span). Multi-day задача повторяется в каждой ячейке (проще + работает через границы месяца). Таб «Календарь» в ProjectPage. TaskDetailDrawer — поле «Старт».
- ✅ **Phase 3.6.10** — Custom fields (7 типов: text/number/date/select/multi_select/person/checkbox). Миграция 0007 `custom_field_definitions` + `task_custom_field_values` (PK task_id+field_id, value JSONB, GIN) с RLS. Validator `app/services/custom_field_validator.py` (pure/sync, 9 unit-тестов). API `app/api/custom_fields.py` — CRUD definitions (owner+) + PUT/DELETE values (editor+, rate-limit task:write). Frontend `CustomFieldEditor`, `CustomFieldsManager`, `TaskCustomFields`, кнопка «Поля» в ProjectPage header.
- ✅ **Phase 3.6.11** — Full-text search + DSL. Миграция 0008: pg_trgm + unaccent, `tasks.search_vector` STORED GENERATED tsvector (russian, title=A, description=B), GIN + trgm индексы. DSL parser `app/services/search_dsl.py` (5 операторов, 18 unit-тестов): `assignee:me|UUID`, `status:`, `priority:`, `due:<|>|=DATE`, `created:`, quoted phrases. Endpoint: `?group_by=project` → `{groups, total, parsed}`, без него — legacy для Sidebar. websearch_to_tsquery + ILIKE-fallback. Frontend: `/search`, SearchPage с chips, SidebarSearch → «Расширенный поиск».
- ✅ **Phase 3.6.12** — Public links view-only без логина. Миграция 0009 `public_share_tokens` БЕЗ RLS (cross-tenant lookup, UUID v4 entropy 122 bit). `app/services/public_token.py` (load_active_token + initials). `app/api/share.py` CRUD + `app/api/public.py` БЕЗ auth (token resolve → bypass_rls→tenant-scoped read → sanitized payload без email/employee_id/tenant_slug/download URL). Feature-flag `SIGNARIS_HUB_PUBLIC_LINKS_ENABLED` (default true). Frontend: PublicViewPage ВНЕ Shell, publicApi без attachAxiosAuth, ShareDialog с copy + revoke. Nginx: access_log skip + Referrer-Policy no-referrer для `/p/` + `/api/public/`. Per-page `<meta name="referrer" content="no-referrer">`.
- ✅ **Phase 4.1..4.9** — CF в List view + rename/reorder (4.1.1); FTS по комментам + `ts_headline` highlight + публичные комменты + Cmd+K (4.1.2); Timeline/Gantt + task dependencies (4.3 — миграция 0010 `task_dependencies`, BFS cycle-check `app/services/dependency_cycle.py`, `app/api/{timeline,dependencies}.py`, `web/src/components/timeline/`); Reports/Dashboard на recharts (4.6 — `app/api/stats.py`, `ProjectDashboard` lazy-loaded); mobile-редизайн под Asana iOS — bottom tab bar/FAB/bottom sheets (4.8); lazy-load ProjectDashboard в отдельный chunk (4.9).

Подробнее каждой подфазы — `/Users/petrpopov/.claude/plans/wobbly-percolating-penguin.md`. LMS-фазы Ф0..Ф8 — `CLAUDE.md` §«Текущая фаза» и `SESSIONS.md`.
