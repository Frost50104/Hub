# Tech debt

Открытые вопросы, упрощения и known-issues. Заполняется по мере накопления.

## Инцидент 2026-08-01 — кросс-tenant RLS-утечка через пул соединений (ИСПРАВЛЕНО)

Пётр (tenant `signaris`) на проде видел проекты/задачи tenant'а `uppetit`: флаппинг 404/200 одного URL, сайдбар с чужими проектами, `/api/me` 500 (`InsufficientPrivilegeError` на INSERT `employee_profiles`).

**Корень:** `tenant_scoped_session` ставил GUC **session-level** один раз при открытии сессии, а `get_db` коммитит shadow-upsert'ы ДО yield → соединение возвращалось в пул (FIFO), и бизнес-запросы роутов исполнялись на другом соединении со stale-GUC чужого tenant'а (или `bypass_rls=on` от воркеров sid-sync/deletion-sync в том же пуле). Пока активен один tenant — не проявлялось; накануне последним в проде был UPPETIT → пул «покрашен» в чужой tenant.

**Фикс:** листенер `app/db.py::_apply_rls_on_begin` (`after_begin` + `SET LOCAL`, порт эталона `CentralAuthService/app/db.py` post-`3cfb256`) перепроставляет оба GUC на старте каждой транзакции. Сопутствующее: `bypass_session_factory()` для lib-воркера deletion-sync (сырая фабрика работала только благодаря утечке — иначе `mark_shadow_deleted` молча обновлял 0 строк); `public.py` stage 2 переведён с bypass на tenant-скоуп (`_mention_names` раскрывал имена/email чужих tenant'ов). Регресс — `tests/integration/test_rls_mid_session_commit.py` (фикстура `rls_enforced`: non-superuser роль, RLS реально enforced; до-фиксовый код валит 2 из 4 тестов).

**Тот же пре-фиксовый `db.py` несёт Listen** (`Listen/app/db.py` + pre-yield commit в `deps.py`; хуже — `device_auth.py` коммитит bypass-сессии → наследник получает полный bypass). Чинить отдельной сессией.

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
- **Импорт из Asana НЕ планируется** — решение 2026-07-03: переноса данных из Asana не будет, CSV-импорт снят с roadmap.

## QA-прогон 2026-07-20 (27 находок, всё исправлено 2026-07-21)

Полный ручной прогон браузером дал 5 критичных + 9 средних + 13 мелких находок — все закрыты (`cc3fe07..ec42e17`, оба env). Ключевые регрессии и их страховки:

- **Поиск задач 500** (func-объект в bindparams) и **дашборд 500** (NullType-cast) — регрессии обновления SQLAlchemy dependabot'ом; закрыты + регресс-тесты `tests/integration/test_stats_search.py`, которые ловят этот класс при будущих апгрейдах.
- **Learn-картинки 404**: nginx regex-локация статики перехватывала internal redirect `X-Accel-Redirect` (видео работало — `.mp4` не в regex). Фикс: `^~` на `/api/*` и `/_protected_media/` — НЕ убирать модификаторы при правках конфигов. **С 2026-08-10 второй инвариант тех же локаций** (`/api/media/` + `/_protected_media/` — заголовки финального ответа X-Accel берёт internal-локация): переиздают ПОЛНЫЙ security-набор с `X-Frame-Options SAMEORIGIN` + CSP `frame-ancestors 'self'` — server-level DENY блокировал same-origin iframe и PDF-уроки были пустыми; первый же `add_header` в локации сбрасывает родительский набор (HSTS живёт только в сниппете!), `sandbox` в CSP media-ответов не добавлять — ломает встроенный PDF-viewer Chrome.
- **Шрифты Unbounded/Onest** теперь self-hosted (`web/src/assets/fonts/`, субсеты latin+cyrillic) — CSP блокировал Google Fonts с 3.6.8, весь продукт рендерился системным шрифтом. Внешние `<link>` шрифтов в index.html запрещены CSP.
- **CSP-хэш inline-скрипта темы**: любая правка анти-FOUC скрипта в `web/index.html` требует пересчёта sha256 в `ops/nginx/hub-security-headers.conf` (+2 CSP в `/p/`-локациях) — команда в комментарии сниппета.
- **`SIGNARIS_HUB_PUBLIC_BASE_URL` обязателен на staging** — иначе публичные ссылки с прод-доменом (docs/DEPLOY.md).

Остаточные упрощения из фиксов:
- **Mention-имена на фронте** берутся из `/tenant/members` (limit 10) — при штате >10 часть чипов останется `@handle` (fallback предусмотрен). При росте tenant'а поднять лимит или отдельную ручку-словарь.
- **Timeline day-зум** подписывает каждый 2-й день (32px/день уже текста даты); label узкого бара (<120px) рисуется справа от бара.
- **CF-колонки и метки в List скрыты на <lg** — мобильный список показывает только название/приоритет/подзадачи/аватар/срок.
- **PDF в уроках рендерится pdf.js** (canvas, `web/src/components/learn/lesson/PdfViewer.tsx`, 2026-08-11) — iframe-подход умер на Android Chrome («контент заблокирован»: телефонный Chrome не рендерит PDF во встраиваниях), iOS показывал первую страницу. Ограничения v1: без текстового слоя (нет выделения/поиска по тексту); cmaps/standard_fonts/wasm НЕ хостим (JS-fallback'и pdfjs; при жалобах на выпавшие шрифты/картинки — скопировать в `web/public/pdfjs/` и передать trailing-slash URL'ы в getDocument); floor pdfjs v6 — Chrome 119+/Safari 17.4+ (ниже — fallback-карточка со ссылкой). Worker подключён `?worker&url` + `worker.format: 'es'` — НЕ менять на голый `?url`: `.mjs`-asset nginx 1.24 отдаёт `application/octet-stream`, а module-worker'ы жёстко требуют JS-MIME (падает только на проде). Чанки `PdfViewer-*.js` и `pdf.worker*.js` — в globIgnores PWA-precache.

## Миграция контента ServiceGuru → Hub (2026-08-16)

Разовый перенос учебных материалов UPPETIT: **18 курсов / 125 уроков / 57 тестов (269 вопросов) / 179 материалов библиотеки / 131 карточка ассортимента**, ~850 МБ медиа. Инструменты: `tools/import_lms/` (локальная сборка bundle из `LMS/`) + `app/jobs/import_lms_bundle.py` (запись на VPS без HTTP).

**Как повторить/докатить:** пересобрать bundle `python -m tools.import_lms.build_bundle` → rsync в `/opt/signaris-hub[-staging]/import-bundle/` (chown signaris) → `sudo -u signaris .venv/bin/python -m app.jobs.import_lms_bundle --bundle ./import-bundle --tenant-slug <slug> [--dry-run]`. Идемпотентность: курс пропускается, только если он **published** (публикация — последний шаг), draft-курс докатывается; материалы/карточки — по названию. **Смена названий в mapping ⇒ повторный прогон создаст дубли** (старые объекты по прежним именам не удаляются).

Инварианты и решения:
- `LMS/` и `import_bundle/` исключены из git И из rsync деплоя (`deploy/deploy.sh`) — иначе 850 МБ уезжают на VPS каждым деплоем.
- Правильный ответ теста в выгрузке помечен **жирным шрифтом ячейки** (`font.bold`, читать `read_only=False`); 28 вопросов мультивыбора; порог квиза `min(80, (n-1)/n*100)` — иначе тест из 2-3 вопросов требовал бы безошибочности.
- Картинки уроков привязываются к строкам **по порядку** (якоря дрейфуют), картинки вопросов — **по номеру строки**; 16 строк-картинок в выгрузке без файла (пропущены).
- Конвертер Quill→RichDoc (`quill_to_richdoc.py`) прогоняется через серверный `validate_lesson_content` ещё локально; `listItem` всегда оборачивает `paragraph` (иначе TipTap нормализует контент при первом открытии в редакторе).
- Уведомления при импорте НЕ шлются (иначе вал пушей); `audit.record` пишется на каждый объект — сотни строк в журнале действий, это ожидаемо.
- Потери выгрузки: 5 роликов «Загруженное видео» (presigned-ссылки протухли за 10 минут) — вместо них callout «📹 Видео будет добавлено позже»; тайминги вопросов (в Hub их нет); выравнивание текста (attrs параграфа запрещены валидатором); фото ассортимента (в выгрузке только тумбы ~2 КБ). 6 YouTube-роликов скачаны через yt-dlp с `player_client: android` (web отдаёт «not available» для unlisted) и захостены у себя.
- Дозагрузка видео через админку упрётся в nginx `client_max_body_size 25M` — импорт идёт мимо HTTP, но для ручной загрузки лимит придётся поднять.

## ОС 17.08 — множественные исполнители + папки проектов (2026-08-18)

Два фиче-реквеста тестировщика UPPETIT (багов в отчёте не было). Инварианты, которые легко сломать при следующей правке:

- **`task_assignees` — источник истины по исполнителям (0034).** `tasks.assignee_id` оставлен как deprecated-зеркало первого исполнителя (position=0) и удаляется отдельной ревизией **0035-drop** (пока не написана). Причина expand/contract: `deploy.sh` делает `rsync → pg_dump → pip install → alembic upgrade → systemctl restart`, то есть СТАРЫЙ процесс работает всю миграцию — `DROP COLUMN` уронил бы в `UndefinedColumn` любое чтение задач на всё окно `pip install`, и `systemctl restart` на предыдущий билд перестал бы быть рабочим откатом.
- **Единственный писатель зеркала — `app/services/task_assignees.py`.** На ревью грепать: `Task.assignee_id =` и `assignee_id=` в конструкторе `Task(` не должны встречаться нигде, кроме этого модуля (и тестовых фикстур, конструирующих `Task` напрямую — например `tests/integration/test_stats_search.py`). Присваивать ТОЛЬКО ORM-атрибутом: Core `update()` оставит объект в сессии протухшим, и сериализация в том же запросе вернёт старое значение.
- **`task_assignees` в списочных запросах — только `EXISTS` (фильтр) или отдельным батч-запросом (отображение).** Наивный JOIN размножит строку задачи по числу исполнителей: дубли карточек на доске, поехавший `ORDER BY …, Task.position`, съеденные `_GROUPED_LIMIT`/`_WORKLOAD_TOP`. Единственное исключение — `stats._workload`, где фан-аут НАМЕРЕННЫЙ (задача на двоих считается обоим), из-за чего сумма по строкам дашборда «Загрузка» БОЛЬШЕ числа задач, а бакет «без исполнителя» считается отдельным запросом и склеивается ПОСЛЕ `limit`.
- **Валидация всего списка исполнителей — ДО любых записей и ДО `_allocate_task_seq`** (тот держит row-lock проекта до конца транзакции). Иначе 404 на третьем исполнителе оставит первых двух записанными.
- **`set_task_assignees` звать строго ПОСЛЕ `db.flush()`** для новых задач — FK `task_assignees.task_id` требует, чтобы строка задачи уже была в Postgres (та же ловушка, что с `record_activity`).
- **PATCH `assignee_ids` — replace-семантика (last-writer-wins по всему набору).** Поэтому UI ходит в инкрементальные `POST /tasks/{id}/assignees` и `DELETE /tasks/{id}/assignees/{employee_id}`: с набором «двое правят одновременно» перестало быть экзотикой, а потеря добавленного была бы беззвучной. PATCH остаётся для легаси-`assignee_id` старых PWA-бандлов и bulk-замены. Следствие, о котором предупреждён тестировщик: старый бандл, приславший `assignee_id: null`, снимает ВСЕХ.
- **Activity `assigned` сохранил kind** (новый провалился бы в `default:` старых бандлов) и несёт и новый формат (`added`/`removed`/`*_names` — снапшот имён), и легаси-зеркала `old`/`new`. Рендер в `TaskThread` ветвится по `Array.isArray(p['added'])`.
- **Фронт читает исполнителей ТОЛЬКО через `taskAssignees()`** (`web/src/lib/taskAssignees.ts`): прямое `task.assignees.map()` падает на объекте из react-query-кэша, пережившего деплой, и на ответе откаченного бэка. Модуль отдельный от `lib/tasks.ts`, потому что тот тянет `api → auth → window`, а vitest в проекте бежит без jsdom.
- **`useUpdateTask.onMutate` кладёт в кэш ровно тело запроса** — для полей, которых в теле нет (`assignees` против `assignee_ids`), заведён люк `__optimistic`, ОБЯЗАТЕЛЬНО отрезаемый в `mutationFn`.
- **Папки проектов — общие для тенанта, ровно один уровень.** CRUD — гейт `can_manage_project_folders` (= `can_create_project`, hub admin|member); перенос проекта — `require_project_role(allow=("owner",))`, поэтому фронт гейтит контролы по уже существующему `can_manage` и своей копии правила не заводит. Удаление папки НИКОГДА не удаляет проекты (`ON DELETE SET NULL`).
- **`ProjectFolderListResponse` не отдаёт `project_count`** — он был бы tenant-wide и расходился бы с видимым пользователю списком, плюс утечка «есть проекты, которые тебе не показывают». Считает клиент.
- **FK `projects.folder_id` НЕ проверяет совпадение тенантов** (RI-триггеры Postgres обходят RLS). Единственная защита — `db.get(ProjectFolder, ...)` через tenant-scoped сессию перед присваиванием.
- **`useDraggable` без `transform` на узле не работает** — карточка не едет за курсором, её rect не смещается, collision detection не видит дропзону, дроп молча не срабатывает. Найдено браузерной самопроверкой; эталон — `CalendarTaskBar`.
- **Ловушка на ревью вёрстки:** `group-hover` требует класс `group` на ОБЩЕМ предке; кнопка «…» — сосед `<Link>`, а не его потомок. Плюс на тач-устройствах hover'а нет — контрол должен быть видим без него (`md:opacity-0 md:group-hover:opacity-100`).

---

## Баг-репорт 13.08 — таск-трекер: зависимости/тема/вложения + номера задач (2026-08-13)

Три бага тестировщика + расширения по решению пользователя (alembic 0032+0033):

- **`color-scheme` в `brand.css`** (dark/light по `data-theme`) — первопричина «белого-на-белом» в нативных попапах `<select>`: UA считал документ светлым. Чинит все ~44 селекта разом; побочно тёмными становятся скроллбары/date-пикеры (желаемо). Страховка `select option { background-color: rgb(var(--bg-alt)) }` — Firefox/Linux наследовал полупрозрачный `--glass`.
- **Номера задач «KEY-42»**: `tasks.seq` + счётчик `projects.next_task_seq` (0032, backfill по created_at,id). Выдача ТОЛЬКО через `tasks.py::_allocate_task_seq` (атомарный UPDATE…RETURNING, row-lock сериализует, дыры при rollback — норма). **`project_id` задачи иммутабелен** — появится перенос между проектами → перевыдавать seq. Фронт: `taskKey()` в `lib/tasks.ts`; `Task.seq` в TS optional (optimistic-объекты его не знают — бейдж скрыт до ответа).
- **Авто-членство viewer при назначении исполнителя** (`project_access.ensure_project_member`, вызовы в create/update task; backfill 0033 по незаархивированным задачам): deep-link из «Все задачи» больше не 404. ON CONFLICT DO NOTHING — роли не даунгрейдятся; unassign членство не удаляет; owner может удалить авто-viewer'а (вернётся при следующем назначении — осознанно).
- **Вложения**: строки «Все задачи»/главной кликабельны (deep-link в проект); `TaskAttachments`/`TaskDependencies` получают `canEdit` (у viewer'а дропзона/«Добавить» скрыты — раньше давали голый 403); **`ATTACHMENT_ACCEPT`+`attachmentTypeError` в `web/src/lib/attachments.ts` зеркалят серверный `ALLOWED_MIME` — менять ПАРОЙ**; +HEIC/HEIF (`resolve_mime` восстанавливает MIME из расширения ТОЛЬКО для .heic/.heif — octet-stream+.svg НЕ спасается, тест в test_attachment_mime.py). Инлайн-превью вложений нет нигде — появится, HEIC из него исключить.
- **Пикер зависимостей** — паттерн PeoplePicker (поиск в дропдауне, дебаунс 150мс), пункты с номером/статусом/секцией/метками, ≤50 видимых. Циклы по-прежнему ловятся только сервером (409-тост).

Backlog волны: поиск по номеру KEY-42 в Cmd+K (FTS), KEY-42 в push-заголовках, «viewer-исполнитель не может менять статус своей задачи» (продуктовый вопрос о роли assignee).

## ОС 12.08 — санитайзер rich-контента и авторский UX (2026-08-12)

Блок правок редактора уроков по второй волне ОС тестировщиков (нумерованный список 422, паста с форматированием, таблицы, размеры текста, публикация из редактора, удаление курса из списка, опрос из урока).

**ИНВАРИАНТ: клиентский санитайзер зеркалит серверный whitelist — менять ПАРОЙ.** `web/src/components/learn/rich/sanitizeRichDoc.ts` (`NODE_ATTRS`/`MARK_ATTRS`) — зеркало `app/services/rich_content.py`; правишь один — правь второй и оба набора тестов (`sanitizeRichDoc.test.ts` + `tests/unit/test_rich_content.py`) на ОДНИХ фикстурах реального вывода TipTap 3.28. Первопричина всего класса багов: TipTap сериализует ВСЕ schema-attrs включая дефолты (`orderedList.type: null`, `tableCell.align`), а fail-closed валидатор отвечал 422 на весь PATCH. Второй подвид того же класса (пойман браузерной проверкой на staging): parseHTML пасты даёт **пустые строки** — `<span style="color:…">` без font-size получает `fontSize: ''` → санитайзер дропает и null, и `''`; сервер трактует `''` как отсутствие (textStyle.color/fontSize, highlight.color). Санитайзер вызывается на выходе редактора (getJSON→sanitize→onChange), editor-state не мутируется (undo цел); lesson-ноды (`LESSON_NODE_TYPES`) проходят НЕТРОНУТЫМИ — иначе развернулись бы в параграфы и `checkQuestion.attrs.correct` потерялся бы.

Остаточные упрощения v1:
- **Таблицы без merge/split UI** (`resizable: false`, только +/− строк/колонок и шапка) — но рендер colspan/rowspan/align в `RichRenderer` есть (шаблоны с merge-ячейками не едут).
- **Word-списки `type='a'`** деградируют в цифровую нумерацию (клиент дропает `type`; сервер атрибут допускает, рендер игнорирует).
- **Опрос-черновик, встроенный автором в урок**, до публикации publisher'ом не открывается сотруднику — автору показывается тост-предупреждение; инлайн-статус опроса в рендере урока не делали.
- **fontSize** — только px из фиксированного набора 12..32 (сервер допускает `^\d{2}px$`, 10..48).

## Решённое в MVP

- Single-flight refresh — реализуется через `attachAxiosAuth` из `@signaris/auth-client/browser` (не пишем вручную).
- Rate-limit Redis + DB fallback — копия из `CentralAuthService/app/security/rate_limit.py`.
- iOS PWA-freeze таймеров в фоне — лечится через `visibilitychange`-trigger проверки SW в `UpdateBanner.tsx`.
