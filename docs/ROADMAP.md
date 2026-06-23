# Roadmap

> **Историческая справка (Hub-MVP.1..6).** Файл описывает исходные 6 MVP-итераций. Актуальный roadmap и статус фаз (3.6.x + 4.x; текущая — 4.9 на staging, прод на 3.6.12) — в `CLAUDE.md` § «Roadmap (hot)» и в `SESSIONS.md`. Статусы 🚧 ниже относятся к периоду MVP и давно не отражают реальность.

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
