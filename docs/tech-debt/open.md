# TECH_DEBT — Открытое и упрощения

Что осознанно не сделано, известные ограничения и backlog. Читать перед планированием новой фичи. Часть `docs/TECH_DEBT.md` (индекс); hot-инварианты — в `CLAUDE.md`.

## Открытое


- **`--workers > 1` заблокирован sid-sync'ом.** Deletion-sync к мульти-воркеру готов (супервизор + Redis leader-lock в `app/services/worker_supervisor.py`, этап 4), но revoked-sid store у sid-sync живёт в памяти процесса: не-лидер не узнаёт о ревокациях, а per-process запуск гоняет общий DB-курсор. Для масштабирования нужен Redis-backed revoked-store. Пока `--workers 1`.
- **VAPID-ключ единый для prod+staging.** Удобно (как у Desk), но если staging-баг утечёт public key, теоретически prod-подписки можно подделать. Низкая вероятность. Раздельные ключи — future work.
- **LexoRank-style `tasks.position NUMERIC`** может «насыщаться» при многих DnD-миграциях карточек. Фоновый rebalance колонки так и НЕ реализован (заглушка в `app/api/tasks.py`); при дельте <0.001 порядок может «слипнуться».
- **Подзадачи только 1 уровень** (`parent_task_id` CHECK depth=1). Глубже потребует tree-CTE в запросах и отдельной миграции.
- **Интеграционные тесты бегут от superuser'а testcontainers** → RLS в них НЕ enforced (superuser обходит политики безусловно, FORCE не помогает) — «ловушка testcontainers-superuser». Opt-in фикстура `rls_enforced` (non-superuser роль `hub_app_test`) есть в `tests/integration/conftest.py` и используется в `test_rls_mid_session_commit.py`; перевод всей сьюты на неё — отдельная задача (ре-аудит ассертов 13 файлов, часть намеренно ослаблена под superuser-мир).
- **Email-коллизии между tenant'ами в `shadow_users`** — для пустого старта Hub проблемы нет; если когда-то будем мигрировать данные, нужен pre-migration report (см. `INTEGRATION.md` шаг 12).
- **Sentry не подключён (DSN нет), проводка полностью готова.** Backend инициализируется при `SIGNARIS_HUB_SENTRY_DSN` в `.env` (deploy.sh с этапа 4 ставит extras `[sentry]`), frontend вызывает `initSentry` при DSN из `/api/env`. Включение = прописать DSN в оба `/opt/*/.env` + restart. Варианты на нашем VPS (2 CPU / 2 GB RAM): (a) Sentry.io free tier — 5k events/мес; (b) GlitchTip self-hosted (~500-800 MB RAM); (c) апгрейд VPS под официальный Sentry. По умолчанию приоритет — GlitchTip на `sentry.signaris.ru`.
- **Healthcheck email-канал требует MTA на VPS** (`mail(1)` не установлен: `apt install mailutils` + postfix/ssmtp). Основной канал — Telegram (`@signaris_bot`, креды в `/etc/default/signaris-hub-healthcheck`, mode 600) — **настроен и проверен вживую 2026-07-03** (DOWN + RECOVERED). Email — опциональный резерв.
- **S3 offsite backup** — флаг `BACKUP_S3_BUCKET` поддерживается в `scripts/backup-pg.sh`, но aws-cli не установлен и креды не настроены. При потере VPS-диска восстановление невозможно без offsite-копии. Минимум — настроить snapshot у VPS-провайдера.

## Упрощения MVP

- ~~Поиск без DSL-фильтров (только базовый title-like).~~ Закрыто в 3.6.11 (FTS + DSL `assignee:me status:in_progress due:<DATE "phrase"`, group_by=project).
- ~~Кастом-статусы / кастом-поля задач — отсутствуют.~~ Custom-поля закрыты в 3.6.10 (7 типов). Кастом-статусы — open (Asana workflow rules).
- ~~Гости (внешние пользователи) и публичные ссылки — отсутствуют.~~ Public links закрыты в 3.6.12 (view-only по UUID-токену). Guests с email-приглашением — open (требует scope `hub:guest` в auth.signaris.ru).
- Time tracking — отсутствует.
- ~~Calendar / Timeline / Gantt — отсутствуют.~~ Calendar закрыт в 3.6.9 (месячная сетка с DnD), Timeline/Gantt — в 4.3 (миграция 0010 `task_dependencies`, scale day/week/month, dependency-arrows, BFS cycle-check).

## Открытое — backlog (после 4.x)

**Закрыто в Phase 4.1..4.9** (вынесено из backlog): Timeline/Gantt + task dependencies (4.3); Reports/Dashboard на recharts (4.6); FTS по комментам + `ts_headline` highlight + Cmd+K + comment-section в project public view (4.1.2); viewConfig + custom-fields-колонки в List view + UI rename + drag-to-reorder definitions (4.1.1); server-side `Referrer-Policy: no-referrer` для `/p/` (3.6.12, nginx per-route — см. `ops/nginx/hub.signaris.ru.conf`).

**Закрыто в этапах 1-2 плана коммерциализации (2026-07-03, staging):** assignee-пикер + null-семантика PATCH; управление участниками в UI; фильтры (assignee/status/priority/label/due) + сортировка в List/Board/Calendar с состоянием в URL; подзадачи в UI; labels end-to-end (+RLS-фикс `task_label_assignments`, миграция 0011); избранные проекты (0012); rename секций; глобальный onError мутаций + QueryError; optimistic updates + undo; markdown в описании/комментах; скелетоны; My Tasks группы по срокам; route code-splitting (бандл 961→688 KB); Telegram-канал healthcheck; ~~аватары-фото отложены~~ — подключены в LMS Ф4 (learn_home/learn_profile отдают `avatar_url` на публичный `auth.signaris.ru/api/avatars/{employee_id}`, CSP img-src расширен, фронт с onError-фолбэком на инициалы).

Осталось открытым:

- **Guests** — email-приглашения внешних пользователей с view/comment-доступом к конкретному проекту. Блокер: нужна фича в `auth.signaris.ru` (новый scope `hub:guest`, JWT-claim `is_guest`, tenant_id хоста для гостя).
- **Saved searches** — сохранить DSL-запрос как «фильтр» / smart-list. Лёгкая надстройка над 3.6.11.
- **CF-фильтры в `GET /tasks?cf_<field_id>=<value>`** — server-side JSONB filters через GIN-индекс (базовые фильтры priority/due/label/sort добавлены в этапе 1; кастом-поля — нет).
- **Time tracking** — оценка/факт по задаче.
- **Email-уведомления fallback** — когда push не работает (не PWA, не Chrome, не разрешил). Через SMTP в `app/services/push_sender.py`.
- **i18n** — сейчас русский hard-coded (англ. утечки enum'ов вычищены в этапе 2). UPPETIT — RU-only, но multi-tenant в будущем потребует.
- **Audit log на admin-действия** — кто добавил/удалил project_member, кто архивировал проект, кто отозвал public link. Расширить `task_activity` или новую `admin_audit_log`.
- **Кастом-статусы задач / Workflow-automation rules** — Asana-эквивалент (при изменении статуса → action). Большой scope.
- **Offsite backup (S3/restic)** — локальный backup покрывает 95% (плюс pre-migration снапшоты deploy.sh с этапа 4); offsite-флаг `BACKUP_S3_BUCKET` есть, нужен бакет+креды. Минимум — snapshot у VPS-провайдера.
- **Импорт из Asana НЕ планируется** — решение 2026-07-03: переноса данных из Asana не будет. Обычный импорт задач из CSV по фиксированному шаблону сделан в редизайне-2 (волна 2, `POST /projects/{id}/tasks/import`).

- **Ассортимент: ссылки в «Что предложить вместе»** (идея тестировщика, 2026-08-21, отложено владельцем). Готовый дизайн: расширить `product_card_links.object_type` на `product`/`product_category` (миграция: `String(32)` + CHECK, `models/product.py:34,97-107`, `schemas/product.py:31-33`), `_resolve_links` → `/learn/products/{id}` (сотруднику — только published) и `/learn/products?category={id}` (добавить `?category=` в `LearnProductsPage`), self-link 422, редактор — `SheetPicker` (searchable, multi) по товарам и категориям, чипы по типу у сотрудника; `upsell` остаётся свободным текстом. ~1 день.
- **Библиотека: LibreOffice-конвертация docx/xlsx → PDF** в extraction-воркере (полный просмотр вместо текстового предпросмотра) — требует апгрейда VPS (2 ГБ без swap, STT до 1,1 ГБ; `soffice --headless` ~150 МБ RSS + ~400 МБ установки).
- **«Личный проект» / перенос задачи между проектами** — `project_id` иммутабелен (нумерация KEY-42); если понадобится «поставить себе и перекинуть на доску» — отдельная фича, не перенос.
- **Tenant timezone** — `display_timezone` один на инсталляцию (`timefmt.display_tz`, `taskdates`); календарь/таймлайн раскладывают по локальным дням браузера — расхождение ≤1 дня для не-МСК браузера.
