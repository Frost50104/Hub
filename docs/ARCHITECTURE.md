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
- `projects` (id, tenant_id, key, name, description, archived_at, created_by, personal_owner_id)
  - `personal_owner_id` (0042) — личное пространство сотрудника «Личное»: NULL у обычных проектов, partial UNIQUE `(tenant_id, personal_owner_id)`. Проект скрыт из ВСЕХ списков (предикаты `app/services/personal_projects.py`), заводится идемпотентно в `GET /api/me`; в чужом личном участник видит только свои задачи. Инвариант целиком — CLAUDE.md §«Задачи и проекты»
- `project_members` (project_id, employee_id, role: `owner` | `editor` | `viewer`)
  - Права фронту отдаёт сервер: `project_access.capabilities()` → `ProjectResponse.can_edit/can_manage` (hub-admin вне членства тоже правит); фронт роли не вычисляет.
- `sections` (project_id, name, position)

### Задачи
- `tasks` (project_id, section_id, parent_task_id, title, description markdown, done BOOLEAN + completed_at под CHECK, priority: `low` | `medium` | `high` | `urgent`, start_at, due_at, position NUMERIC, search_vector tsvector). Колонка `status` (четыре системных статуса) — legacy, дропает 0045
  - Подзадачи только 1 уровень — CHECK `parent_task_id IS NULL OR (SELECT parent_task_id FROM tasks t2 WHERE t2.id = parent_task_id) IS NULL`; UI — секция в карточке (SubtaskList), в топ-уровне List/Board не показываются
- `project_stages` (project_id, name, position; 0040, свободные с 0044) — колонки доски: ТОЛЬКО имя и позиция, системного смысла нет. `tasks.stage_id` NOT NULL (FK без `SET NULL`), у проекта ≥1 колонка; состояние задачи — независимая ось `tasks.done`, пишет её только `app/services/stages.py::set_done`. `create_project` создаёт 4 стартовые колонки, их можно переименовать и удалить. Колонка `system_status` — legacy, дропает 0045. API `app/api/stages.py`
- `tasks.seq` (0032–0033) — номера «KEY-42» внутри проекта, выдача только `allocate_task_seq` под row-lock проекта, `project_id` иммутабелен
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
Список / Доска (по этапам `project_stages`) / Календарь (`app/api/calendar.py`) / Хронология (`app/api/timeline.py`, `include_undated` — строки без полосы) / Дашборд (`app/api/stats.py`: статусы, этапы, приоритеты, тренд, загрузка с `overdue_count`; графики CSS — `Donut`/`MiniBarChart`/`MeterRow`, recharts снят) / Участники. Импорт задач из CSV — `POST /projects/{id}/tasks/import?dry_run=` (`app/api/tasks_import.py`) через общий путь создания `app/services/tasks.py::create_task_record`. Фильтры (assignee/done/priority/label/due) + сортировка списка — состояние в URL searchParams; Board всегда в position-порядке. Полнотекстовый поиск: `app/api/search.py` + DSL `app/services/search_dsl.py` (0008: pg_trgm, tsvector). Мутации задач оптимистичные (rollback из снапшота, `useUpdateTask`), complete/archive — с undo-тостом.

### Уведомления
- `push_subscriptions` (employee_id, endpoint UNIQUE, p256dh, auth, user_agent)
- `notifications` (in-app Inbox)
- `notification_preferences` (employee_id, prefs JSONB) — per-kind, per-channel: `{kind: {push: bool, in_app: bool}}` (legacy `{kind: bool}` нормализуется на чтении)

### Служебное
- `shadow_tenants`, `shadow_users`
- `sync_state` (deletion-sync cursor)
- `rate_limits` (DB-fallback для Redis)

## Learn-домен (LMS, миграции 0014–0031; трекер/ассистент/этапы — 0032–0040)

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
- **Курсы (0022-0023):** `courses`, `course_lessons` (content JSONB, unlock_rule), `lesson_templates`, `media_files` (подписанные URL; `duration_sec` — длительность видео, прочитанная сервером из mp4, 0043); `course_assignments`, `lesson_progress` (block_state: gate-ответы, видео-интервалы), `course_progress`.
- **Тесты (0024):** `quizzes` (владелец: урок ИЛИ кампания — CHECK), `quiz_questions` (5 типов), `quiz_attempts` (снапшот вопросов + seed, needs_review для open-вопросов).
- **Рейтинг (0025):** `activity_events` (append-only, partial-unique «первое действие»), `certificates`.
- **Ассортимент (0026):** `product_categories`, `product_cards` (lifecycle+audience), `product_card_links` (изучить по теме).
- **Автосценарии (0027):** `automation_rules` (applies_from — без ретро), `automation_jobs` (UNIQUE rule+profile).
- **AI (0028):** `ai_conversations`, `ai_messages`, `rag_chunks` (pgvector, embedding без typmod + embedding_model).
- **Биржа смен (0029):** `shift_postings` (open→assigned→done|cancelled), `shift_applications` (UNIQUE posting+profile).
- **Аттестации (0030):** `assessment_campaigns` (draft|active|closed, audience, окно дат; владеет квизом через `quizzes.campaign_id`).

### Роутеры и воркеры

Learn-роутеры в `app/api/`: org, employees, audit, library, news, surveys, favorites, courses, media, quizzes (включая рейтинг и review), products, learn_home, learn_search, learn_analytics, automations, ai, shifts, assessments; общие для двух пространств — assistant, reports (iiko). Трекер: env, me, me_tasks, projects, project_folders, sections, **stages**, tasks, **tasks_import**, calendar, custom_fields, labels, dependencies, timeline, share, public, comments, watchers, activity, attachments, search, tenant, push, notifications, stats. Всего 45 роутеров (см. `app/main.py`).

Фоновая обработка: systemd-таймеры `course-due-soon`, `review-due`, `inactivity`, `automations` (джобы в `app/jobs/`) + long-running воркер `app/workers/extraction.py` (отдельный сервис `signaris-hub[-staging]-extraction.service`: извлечение текста pypdf/docx → search_documents.body_text → RAG-reconcile). Голосовой ввод ассистента — отдельный юнит `signaris-hub[-staging]-stt.service` (`app/stt_service.py`, faster-whisper; включён только на проде).

### Frontend

`web/src/pages/learn/` — 22 страницы: витрина (LearnHomePage), курсы/уроки/тесты (LearnCoursesPage, LearnCoursePage с `?preview=1` «глазами сотрудника», LearnLessonPage, CourseBuilderPage, QuizBuilder), библиотека, новости, опросы (`/learn/surveys/:id` — прохождение), ассортимент (`/learn/products/:id` — карточка), рейтинг, биржа смен, аттестации, сертификат и **«Управление» одним маршрутом `/learn/admin?tab=review|analytics|employees|automations|audit|org`** (`LearnAdminPage`; шесть прежних страниц — вкладки через `AdminEmbedContext`, гейты по сегментам `adminSegmentsFor`, старые URL — редиректы). AI-ассистент — общий `web/src/pages/AssistantPage.tsx` + `components/assistant/*` (маршрут `/assistant`).

Активное пространство — `resolveSpace` (`web/src/lib/workspace.ts`): `/learn*` → learn, нейтральные `/inbox|/search|/profile|/settings` наследуют последнее посещённое (`lastSpace`), cold-start на `/` возвращает в learn (one-shot флаг; boot-redirect и remember живут в ОДНОМ эффекте Shell — порядок критичен, иначе remember перетирает lastSpace до чтения). У learn свой Sidebar; мобильный таб-бар — Desk-стиль (плоские 50px), 5-я вкладка learn — «Меню» (BottomSheet, списки из `learnNav.ts` — единый источник с сайдбаром). Уроки: картинки открываются в `ImageLightbox` (fullscreen, листание галерей), PDF (уроки-документы и `pdfEmbed`-блоки) рендерится `PdfViewer` (pdfjs-dist, canvas, lazy-чанк вне precache — инварианты worker/MIME в TECH_DEBT), на последнем завершённом уроке — кнопка «Завершить курс».

### Инварианты по доменам (полный список, hot-выжимка — в CLAUDE.md)

- **FK-инвариант:** «действует человек (actor/author/owner) → `shadow_users.employee_id`; данные О человеке (прогресс, назначения, ознакомления, членства) → `employee_profiles.id`». `employee_profiles.employee_id` NULL до первого входа; матчинг по `lower(email)` в `/api/me` — ТОЛЬКО для principals с hub-ролью.
- **Audience-движок:** контентный объект несёт `audience_id NULL`(=всем) → правила в `audience_rules` (include: AND непустых измерений внутри строки, OR между строками; exclude вычитается; пустая include-строка запрещена) → материализация в `audience_members` (granted_at!). Фильтр списков — `visible_filter()` из `app/services/audience_resolver.py`. Пересчёты — под per-tenant advisory-lock, diff/upsert (granted_at сохраняется). Атрибуты ТУ расширяются закреплёнными магазинами, франчайзи-владельца — его магазинами; франчайзи рядового — из store.franchisee_id. Измерения: 9 uuid[]-справочников + скалярный «контур» `org_roles` (employee|tu|franchisee_owner|office, 0031). Правила перечитываются: `GET /learn/audiences/{id}` (+`profile_labels`) → посев диалогов через `useAudienceDraft` (пока грузится — скелетон и гейт `ready`, иначе можно сохранить пустую аудиторию «никому»); dry-run — publisher+ (не только admin).
- **Архивация** — только через `archive_profile()` (каскад: members, с Ф5 — automation_jobs); история обучения не удаляется. Deletion-sync архивирует профиль в СВОЕЙ tenant-scoped сессии (bypass — только для чтения очередей; политики без WITH CHECK — под bypass можно случайно писать в чужой tenant).
- **audit_log** — append-only (RLS только SELECT+INSERT), пишется `app/services/audit.py::record()` в транзакции действия; diff — только метаполя, НИКОГДА не содержимое ответов (ПДн).
- **learning_settings** — singleton per tenant, обновление ТОЛЬКО по-ключево (`learn_settings.set_setting`, jsonb_set).
- **Lifecycle контента (Ф1+):** переходы ТОЛЬКО через `app/services/lifecycle.py::transition` (матрица + роли + audit); `content_access.require_content_role` — guard author/publisher. Поисковый индекс `search_documents` наполняется ТОЛЬКО `search_indexer` (upsert при publish, delete при archive — черновики не индексируются). Ack-инварианты библиотеки: version_no валидируется против выданной версии, гейт по view_history, дедлайн от max(published_at, granted_at члена). Файлы материалов — под attachments_root/{tenant}/learn/, бэкап — `signaris-hub-backup-files.timer` (rsync --link-dest снапшоты, retention 14д).
- **Курсы (Ф3a):** видимость потребителю = published AND (audience-член OR активное назначение). Sequential-замки — НА СЕРВЕРЕ (`_lesson_locked` в `app/api/courses.py`, GET урока → 403) с монотонностью: урок с progress не запирается. «Завершить урок» — явное действие с предусловиями (gate-checkQuestion отвечены + required-видео coverage≥0.9, `app/services/video_progress.py`); completed_at курса иммутабелен (coalesce в upsert). Контент урока: `lesson_content.validate_lesson_content` (extra-ноды figure/gallery/video/pdfEmbed/surveyEmbed/checkQuestion поверх rich_content); отдача потребителю через `prepare_for_consumer` — подписывает media-src и ВЫРЕЗАЕТ attrs.correct (manager'у оставляет: strip_correct=False).
- **Медиа (Ф3a):** отдача ТОЛЬКО по подписанным URL `/api/media/{id}?e&s` (`learn_media.sign_media_path`, HMAC, TTL 6ч; теги video/img не несут Bearer) → nginx X-Accel-Redirect `/_protected_media/`. Upload `/api/learn/media`: whitelist MIME (видео только mp4 + обязательный faststart-чек), statvfs-порог 5ГБ. Файлы под attachments_root/{tenant}/learn/media/ (в общем rsync-бэкапе).
- **Тесты (Ф3b):** правильные ответы живут ТОЛЬКО в снапшоте попытки (`quiz_attempts.snapshot`, shuffle по seed через `quiz_scoring.build_snapshot` — типо-специфичный: match только правая колонка, order всегда перемешан); потребителю — `sanitize_snapshot`. Лимит попыток — по `finished_at IS NOT NULL` (обрыв связи не сжигает попытку, резюм с тем же снапшотом). Open-вопросы → `needs_review`: до проверки HR НЕТ score/passed/событий и новых попыток; финализация ТОЛЬКО через `/quiz-attempts/{id}/review`. Замок `after_prev_test` требует passed required-квиза предыдущего урока (`quiz_gate.passed_required_quiz_lessons`).
- **Рейтинг (Ф3b):** запись в `activity_events` ТОЛЬКО через `points.award` (идемпотентно: partial-unique «первое действие»; points — снапшот веса из learning_settings.rating_weights, история не пересчитывается). Лидерборд считается на лету по occurred_at (месяц/квартал; отдельной таблицы rating_cohorts НЕТ — осознанное упрощение плана). Сертификаты: `certificate.issue_if_earned` при завершении курса, UNIQUE(course, profile), снапшот названий.
- **Ассортимент (Ф4):** карточки товаров — lifecycle+audience по паттерну библиотеки; фото — media_files (подписанные URL); линки «изучить по теме» (course|lesson|material) резолвятся при отдаче, мёртвые скрываются. Открытие карточки → view_history + идемпотентный product.first_view. Витрина `/api/learn/home` переиспользует доменные ручки (list_courses/_not_acked/rating); `/api/learn/profile` — орг-имена+стаж+`avatar_url` на публичный auth-эндпоинт (фронт с onError-фолбэком на инициалы).
- **Автосценарии (Ф5):** правило применяется ТОЛЬКО к профилям с created_at >= rule.applies_from (без ретро-назначений ветеранам); jobs UNIQUE(rule, profile), исполняются hourly-cron чанком 200 (`app/jobs/automations_run.py`); правка правила не ретро-меняет jobs; archive_profile отменяет pending. Правило неактивности (`app/jobs/inactivity.py`): warn (сотрудник+руководитель, kind profile.inactivity) → grace → авто-архив; маркер inactivity_warned_at сбрасывается при активности; пороги/тексты — learning_settings.
- **Аналитика (Ф5):** `app/api/learn_analytics.py` — доступ publisher+/hub-admin (вся сеть) или ТУ/франчайзи (свои магазины через org_scope), линейным 403. Опросы в аналитику НЕ входят (только survey_stats). CSV-экспорт ≤5000 строк. Learn-поиск `/api/learn/search` — FTS search_documents + лог search_queries.
- **AI-помощник (Ф6):** RAG строится ПОВЕРХ search_documents (только published, audience_id денормализован) воркером `app/workers/extraction.py` (ОТДЕЛЬНЫЙ systemd-сервис `signaris-hub[-staging]-extraction.service`: text_extraction_jobs → pypdf/docx → body_text; затем rag-reconcile). ИНВАРИАНТ: retrieval (`app/api/ai.py::retrieve_chunks`) фильтрует по audience_members + embedding_model — тест в test_ai.py обязателен при правках. LLM — `app/services/llm/` (yandex|gigachat|openai-compatible), переключение SIGNARIS_HUB_AI_* конфигом; без ключа /ask → 503, воркер пропускает RAG-шаг. Провайдер без /embeddings (DeepSeek → LLMEmbeddingsUnsupported) — retrieval падает на лексический FTS-fallback (`retrieve_lexical`: OR-семантика по словам вопроса, тот же visible_filter — инвариант аудитории сохранён и покрыт тестом). Тексты уроков включаются в body_text документа курса при publish/правке (иначе поиск и AI видят только название курса). rag_chunks.embedding — vector БЕЗ размерности (смена провайдера без ALTER, сверка по embedding_model). Тестовые контейнеры — pgvector/pgvector:pg16.
- **Биржа смен (Ф7):** posting open→assigned→done|cancelled; application pending→accepted|declined|withdrawn (UNIQUE posting+profile). Матчинг отклика — НА СЕРВЕРЕ (active + та же должность + завершённые required_course_ids, 409 с названиями недостающих курсов). Менеджер = org_scope stores (ТУ/франчайзи) или hub-admin; создание смены проверяет, что store в скоупе. auto_confirm назначает первый прошедший отклик; withdraw назначенного возвращает смену в open + сигнал менеджеру. Kinds shift.new (батч по должности) / shift.application / shift.result.
- **Аттестации (Ф8):** кампания (`assessment_campaigns`: draft|active|closed, audience, окно дат) владеет СВОИМ квизом — `quizzes.campaign_id` FK CASCADE, `course_id` стал nullable, CHECK «ровно один владелец»; весь квиз-движок Ф3b (снапшоты/seed/лимит попыток/review-flow) переиспользован. **Управление кампаниями — только hub-admin (ОС 2026-08-10)**: create/patch/audience/quiz/import/activate/close/delete + `_quiz_manager`; publisher — обычный участник (audience+окно, `_consumer_quiz_access` без обхода), но **review открытых ответов, reset-attempts, уведомления `quiz.review_needed` и отчёт (+stores-скоуп ТУ) остаются publisher'ам** — списка админов в БД нет (роль только в JWT), иначе пришлось бы отключать уведомления. Consumer-доступ = campaign active + окно + audience-членство; admin — всегда. Импорт вопросов из тестов уроков (позиции продолжаются); activate требует ≥1 вопрос → quiz published + батч kind assessment.assigned с дедлайном; отчёт not_started|in_progress|pending_review|passed|failed со срезом org_scope. Активные несданные кампании показываются на витрине (learn_home).
- **Роли:** JWT hub:admin|member|viewer + hub-side `org_role` (employee|tu|franchisee_owner|office → скоуп аналитики через `org_scope.resolve_scope`) + `content_role` (none|author|publisher → права на контент, с Ф1).

### Роли learn-домена

JWT `hub:admin|member|viewer` + hub-side `org_role` (employee|tu|franchisee_owner|office — скоуп аналитики через `org_scope.resolve_scope`) + `content_role` (none|author|publisher — права на контент).

## Ассистент и отчёты iiko (Ф6+, миграции 0028, 0037)

- Таблицы: `ai_conversations`, `ai_messages` (0028; журнал операций — роли user/assistant, `kind`, `data` JSONB с планом/отчётом/отказом), `assistant_plans` (0037; план действий: статус pending→done|rejected|failed, TTL 30 мин, исполняется один раз), `rag_chunks` (pgvector).
- Сервисы: `app/services/assistant/` (`tools.py` — инструменты трекера и базы знаний, `runner.py` — цикл витков tool-calling, `plans.py`, `context.py` — резолверы «имя → id», `prompts.py`), `app/services/llm/` (yandex|gigachat|openai-compatible; DeepSeek в проде), `app/services/iiko/` (async-порт OLAP-клиента Listen: per-tenant Redis-лок, кэш 15 мин, logout в `__aexit__`), `app/services/stt/` (local faster-whisper | openai) + `app/stt_service.py`.
- Роутеры: `ai` (`/api/ai/ask`, RAG), `assistant` (`/api/ai/*` журнал/планы; `/api/learn/ai/*` — алиасы), `reports` (пять отчётов iiko + CSV).
- Hot-инварианты (порог подтверждения, гейты, слот лицензии, «точки НЕ связаны») — CLAUDE.md §«Ассистент и отчёты iiko (hot)».

## Push-триггеры (task-домен, 6 из 20 kinds)

- `task.assigned_to_me` — мне назначили задачу
- `task.mentioned` — упомянули в комментарии
- `task.commented_on_watched` — комментарий на наблюдаемой задаче
- `task.status_changed_on_watched` — задача выполнена или вернулась в работу (kind исторический: ключи лежат в JSONB-настройках людей и переименованию не подлежат)
- `task.due_soon` — за 24ч до дедлайна (cron hourly)
- `task.overdue` — просрочена (cron daily 09:00 MSK)

Ещё 14 learn-kinds (library/news/survey/course/quiz/profile/shift/assessment) — полный список с триггерами в `docs/PUSH.md`; источник истины — `app/services/notification_prefs.py::NOTIFICATION_KINDS`.

## Темы

- **Тёмная** — буквальный порт CSS-переменных из `IT_startup/index.html:18-30` (амбер `#FFB200`, фон `#08080E`, glass-эффект).
- **Светлая** — спроектирована с нуля. Палитра согласована на границе Hub-MVP.1.
- Переключатель Светлая/Тёмная — в Настройках → «Оформление» (`web/src/components/ThemeToggle.tsx`). Default — тёмная, `data-theme` на `<html>` всегда явный (режима System нет). Графики — CSS-примитивы на токенах темы (`lib/tone.ts`: красный — просрочка/ошибка, зелёный — «сделано», ряды — амбер / `--blue-deep` / `--text2`).

## Безопасность

- JWT claims читаются **только** через `signaris-auth-client` — никакого ручного `jwt.decode`.
- CORS на backend разрешает только `https://hub.signaris.ru` и `https://hub-staging.signaris.ru`.
- Rate-limit через Redis (с DB-fallback): паттерн скопирован из `CentralAuthService/app/security/rate_limit.py`.
- Refresh-cookie общий на `.signaris.ru`. Для PWA standalone (iOS) — режим `X-Auth-Mode: api`, refresh-token в IndexedDB.
