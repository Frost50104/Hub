# Architecture

## Принципы

1. **Единая авторизация.** Никакого собственного логина — только SSO через [auth.signaris.ru](https://auth.signaris.ru) по чек-листу `CentralAuthService/client-libs/INTEGRATION.md` (13 шагов + §14 deletion-sync). Без per-product «снежинок».
2. **Multi-tenancy через RLS.** Каждая бизнес-таблица — `tenant_id UUID NOT NULL` + Postgres-policy. Приложение работает от non-superuser-роли (RLS реально enforced), миграции — от migrate-роли (BYPASSRLS).
3. **Shadow-таблицы.** `shadow_tenants` + `shadow_users` (с `deleted_at TIMESTAMPTZ NULL`) апсертятся на каждый authenticated-запрос. Доменные FK ссылаются на `shadow_users.employee_id` — не на JWT.sub.
4. **Deletion-sync.** Воркер `run_deletion_sync_worker` (lib ≥ 0.4.0) в lifespan тянет события из `auth.signaris.ru/api/products/deletions`. `on_event` — no-op (история тасков сохраняется); списки сотрудников фильтруются `WHERE shadow_users.deleted_at IS NULL`.

## Backend

- **FastAPI** async + lifespan: JWKS-warmup, Redis pool, фоновые воркеры deletion-sync и sid-sync (оба через `worker_supervisor.supervise` — рестарт с backoff + Redis leader-lock), Sentry init (опц.). In-memory store sid-sync блокирует `--workers > 1` (см. TECH_DEBT).
- **`tenant_scoped_session(tenant_id, *, bypass_rls)`** — async ctx manager (`app/db.py`), паттерн CentralAuthService (post-`3cfb256`). Помечает сессию `session.info["rls_scope"]`; листенер `_apply_rls_on_begin` (`after_begin`) ставит `app.tenant_id`/`app.bypass_rls` через `SET LOCAL` на старте каждой транзакции (переживает mid-request commit + смену соединения в пуле — session-level вариант дал кросс-tenant утечку 2026-08-01, см. TECH_DEBT). Для lib-воркеров с сырой фабрикой — `bypass_session_factory()`.
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
  - Права фронту отдаёт сервер: `project_access.capabilities()` → `ProjectResponse.can_edit/can_manage` (hub-admin вне членства тоже правит); фронт роли не вычисляет.
- `sections` (project_id, name, position)

### Задачи
- `tasks` (project_id, section_id, parent_task_id, title, description markdown, status: `todo` | `in_progress` | `in_review` | `done`, priority: `low` | `medium` | `high` | `urgent`, start_at, due_at, position NUMERIC, search_vector tsvector)
  - Подзадачи только 1 уровень — CHECK `parent_task_id IS NULL OR (SELECT parent_task_id FROM tasks t2 WHERE t2.id = parent_task_id) IS NULL`; UI — секция в карточке (SubtaskList), в топ-уровне List/Board не показываются
- `task_assignees` (task_id, employee_id, position, assigned_by; PK составной, RLS с 0034) — **единственное место, где живут исполнители**; колонка-зеркало `tasks.assignee_id` удалена ревизией 0036. Пишет только `app/services/task_assignees.py`; в списках — EXISTS/батч, не JOIN
- `task_watchers` — auto-добавление: assignee + creator + mentioned
- `task_comments` (markdown, `mentioned_ids UUID[]`)
- `task_labels` (name, color) + `task_label_assignments` (с tenant_id и RLS с миграции 0011); API `app/api/labels.py`, чипы в List/Board/drawer, фильтр
- `task_attachments` (whitelist mime без SVG, 20 MB)
- `task_activity` (append-only event log)
- `task_dependencies` (predecessor/successor, finish-to-start, BFS cycle-check `app/services/dependency_cycle.py`, миграция 0010) — стрелки на Timeline
- `custom_field_definitions` + `task_custom_field_values` (7 типов, миграция 0007) — колонки List, агрегаты Dashboard
- `public_share_tokens` (scope task|project, БЕЗ RLS — cross-tenant lookup по токену, миграция 0009) — view-only `/p/{token}`
- `project_members.is_favorite` (миграция 0012) — личное избранное, секция в Sidebar
- `project_folders` (name, position) + `projects.folder_id` (0035) — общие для тенанта папки, ровно один уровень; удаление папки не удаляет проекты (ON DELETE SET NULL); API `app/api/project_folders.py` на префиксе `/project-folders`

### Представления проекта
Список / Доска / Календарь (`app/api/calendar.py`) / Хронология (`app/api/timeline.py`) / Дашборд (`app/api/stats.py`, recharts lazy-chunk) / Участники. Фильтры (assignee/status/priority/label/due) + сортировка списка — состояние в URL searchParams; Board всегда в position-порядке. Полнотекстовый поиск: `app/api/search.py` + DSL `app/services/search_dsl.py` (0008: pg_trgm, tsvector). Мутации задач оптимистичные (rollback из снапшота, `useUpdateTask`), complete/archive — с undo-тостом.

### Уведомления
- `push_subscriptions` (employee_id, endpoint UNIQUE, p256dh, auth, user_agent)
- `notifications` (in-app Inbox)
- `notification_preferences` (employee_id, prefs JSONB) — per-kind, per-channel: `{kind: {push: bool, in_app: bool}}` (legacy `{kind: bool}` нормализуется на чтении)

### Служебное
- `shadow_tenants`, `shadow_users`
- `sync_state` (deletion-sync cursor)
- `rate_limits` (DB-fallback для Redis)

## Learn-домен (LMS, миграции 0014-0031)

Второе пространство Hub («Обучение», `/learn/*`) — LMS-замена ServiceGuru. Hot-инварианты — в `CLAUDE.md` §«Learn-домен»; здесь — каталог сущностей.

### Таблицы по доменам (таблица → миграция)

- **Оргструктура (0014):** `departments`, `positions`, `position_groups(+members)`, `stores`, `store_groups(+members)`, `franchisees`, `franchisee_groups(+members)`, `user_groups(+members)`, `employee_profiles` (employee_id NULL до первого входа, матчинг по lower(email)), `tu_store_assignments`.
- **Аудитории (0015):** `audiences`, `audience_rules` (include/exclude, AND внутри строки / OR между; 9 uuid[]-измерений + `org_roles text[]` — измерение «контур», 0031), `audience_members` (материализация, granted_at). Read-back правил для пикера — `GET /learn/audiences/{id}`.
- **Журнал и настройки (0016):** `audit_log` (append-only), `learning_settings` (singleton per tenant, jsonb).
- **Библиотека (0017):** `library_sections` (дерево), `library_materials` (lifecycle+audience, requires_acknowledgement), `material_versions`, `material_acknowledgements`.
- **Поиск/индекс (0018):** `search_documents` (только published; вход для FTS и RAG), `text_extraction_jobs`, `view_history`.
- **Новости (0019):** `news_posts` (TipTap JSONB), `news_comments`, `news_reactions`, `news_acknowledgements`.
- **Опросы (0020):** `surveys`, `survey_questions`, `survey_participations` (факт), `survey_answer_sets` (анти-деанон: без timestamp/identity), `survey_answers`; все выходы ответов — только через `survey_stats` (k-anonymity).
- **Избранное/лог поиска (0021):** `favorites`, `search_queries`.
- **Курсы (0022-0023):** `courses`, `course_lessons` (content JSONB, unlock_rule), `lesson_templates`, `media_files` (подписанные URL); `course_assignments`, `lesson_progress` (block_state: gate-ответы, видео-интервалы), `course_progress`.
- **Тесты (0024):** `quizzes` (владелец: урок ИЛИ кампания — CHECK), `quiz_questions` (5 типов), `quiz_attempts` (снапшот вопросов + seed, needs_review для open-вопросов).
- **Рейтинг (0025):** `activity_events` (append-only, partial-unique «первое действие»), `certificates`.
- **Ассортимент (0026):** `product_categories`, `product_cards` (lifecycle+audience), `product_card_links` (изучить по теме).
- **Автосценарии (0027):** `automation_rules` (applies_from — без ретро), `automation_jobs` (UNIQUE rule+profile).
- **AI (0028):** `ai_conversations`, `ai_messages`, `rag_chunks` (pgvector, embedding без typmod + embedding_model).
- **Биржа смен (0029):** `shift_postings` (open→assigned→done|cancelled), `shift_applications` (UNIQUE posting+profile).
- **Аттестации (0030):** `assessment_campaigns` (draft|active|closed, audience, окно дат; владеет квизом через `quizzes.campaign_id`).

### Роутеры и воркеры

Learn-роутеры в `app/api/`: org, employees, audit, library, news, surveys, favorites, courses, media, quizzes (включая рейтинг и review), products, learn_home, learn_search, learn_analytics, automations, ai, shifts, assessments. Всего в приложении 40 роутеров (см. `app/main.py`).

Фоновая обработка: systemd-таймеры `course-due-soon`, `review-due`, `inactivity`, `automations` (джобы в `app/jobs/`) + long-running воркер `app/workers/extraction.py` (отдельный сервис `signaris-hub[-staging]-extraction.service`: извлечение текста pypdf/docx → search_documents.body_text → RAG-reconcile).

### Frontend

`web/src/pages/learn/` — 22 страницы: витрина (LearnHomePage), курсы/уроки/тесты (LearnCoursesPage, LearnCoursePage, LearnLessonPage, CourseBuilderPage, QuizBuilder), библиотека, новости, опросы, ассортимент, рейтинг, AI-ассистент, биржа смен, аттестации, админка (org, employees, review, analytics, automations, audit), сертификат.

Активное пространство — `resolveSpace` (`web/src/lib/workspace.ts`): `/learn*` → learn, нейтральные `/inbox|/search|/profile|/settings` наследуют последнее посещённое (`lastSpace`), cold-start на `/` возвращает в learn (one-shot флаг; boot-redirect и remember живут в ОДНОМ эффекте Shell — порядок критичен, иначе remember перетирает lastSpace до чтения). У learn свой Sidebar; мобильный таб-бар — Desk-стиль (плоские 50px), 5-я вкладка learn — «Меню» (BottomSheet, списки из `learnNav.ts` — единый источник с сайдбаром). Уроки: картинки открываются в `ImageLightbox` (fullscreen, листание галерей), PDF (уроки-документы и `pdfEmbed`-блоки) рендерится `PdfViewer` (pdfjs-dist, canvas, lazy-чанк вне precache — инварианты worker/MIME в TECH_DEBT), на последнем завершённом уроке — кнопка «Завершить курс».

### Роли learn-домена

JWT `hub:admin|member|viewer` + hub-side `org_role` (employee|tu|franchisee_owner|office — скоуп аналитики через `org_scope.resolve_scope`) + `content_role` (none|author|publisher — права на контент).

## Push-триггеры (task-домен, 6 из 20 kinds)

- `task.assigned_to_me` — мне назначили задачу
- `task.mentioned` — упомянули в комментарии
- `task.commented_on_watched` — комментарий на наблюдаемой задаче
- `task.status_changed_on_watched` — статус изменён
- `task.due_soon` — за 24ч до дедлайна (cron hourly)
- `task.overdue` — просрочена (cron daily 09:00 MSK)

Ещё 14 learn-kinds (library/news/survey/course/quiz/profile/shift/assessment) — полный список с триггерами в `docs/PUSH.md`; источник истины — `app/services/notification_prefs.py::NOTIFICATION_KINDS`.

## Темы

- **Тёмная** — буквальный порт CSS-переменных из `IT_startup/index.html:18-30` (амбер `#FFB200`, фон `#08080E`, glass-эффект).
- **Светлая** — спроектирована с нуля. Палитра согласована на границе Hub-MVP.1.
- Переключатель Светлая/Тёмная — в Настройках → «Оформление» (`web/src/components/ThemeToggle.tsx`). Default — тёмная, `data-theme` на `<html>` всегда явный (режима System нет). Палитра recharts на дашборде читается из CSS-токенов при смене темы.

## Безопасность

- JWT claims читаются **только** через `signaris-auth-client` — никакого ручного `jwt.decode`.
- CORS на backend разрешает только `https://hub.signaris.ru` и `https://hub-staging.signaris.ru`.
- Rate-limit через Redis (с DB-fallback): паттерн скопирован из `CentralAuthService/app/security/rate_limit.py`.
- Refresh-cookie общий на `.signaris.ru`. Для PWA standalone (iOS) — режим `X-Auth-Mode: api`, refresh-token в IndexedDB.
