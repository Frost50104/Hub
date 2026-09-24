# Push notifications

## VAPID

- Генерируется один раз через `scripts/generate_vapid.py`.
- **Public key** — в env как `SIGNARIS_HUB_VAPID_PUBLIC_KEY`, отдаётся фронту через `GET /api/env` → `VITE_VAPID_PUBLIC_KEY` (через build) или env-fetch.
- **Private key** — файл `/opt/signaris-hub/vapid_private.pem` (mode 600 root:signaris). В env только путь `SIGNARIS_HUB_VAPID_PRIVATE_KEY_PATH`. **В коде не хранится никогда.**
- `vapid_subject` = `mailto:ops@signaris.ru`.
- **Ключ единый для prod + staging** (как у Desk). Раздельные ключи — будущая работа, см. `docs/TECH_DEBT.md`.
- **В `pywebpush` ключ уходит ОБЪЕКТОМ `Vapid`** (`push_sender.load_vapid()`), не текстом и не путём. Библиотека разбирает аргумент так: объект `Vapid01` — как есть, путь — через `Vapid.from_file` (понимает PEM), **любая другая строка — через `Vapid.from_string`, а он PEM с заголовками не понимает** и падает с «ASN.1 parsing error». Именно на этом push не доставлялся 29.07–26.08 (`docs/tech-debt/incidents.md`). Путь тоже сработал бы, но заставлял бы читать файл на каждую отправку.
- **Существование файла проверяется ДО вызова библиотеки:** `Vapid.from_file` при отсутствии файла молча генерирует НОВУЮ пару и пишет её на диск — публичный ключ в env остаётся прежним, и все подписки превращаются в мусор. Пропавший ключ обязан быть громкой ошибкой.
- **Приватный ключ сверяется с `vapid_public_key`** из env: не совпали — пуш выключается с `vapid.public_key_mismatch`, потому что браузер такую подпись не примет.
- Состояние ключа наружу: `GET /api/health/push` → `{"vapid": "ok"|"absent"|"invalid"|"mismatch"}`. Дёргает `scripts/healthcheck.sh` каждые 5 минут, при не-`ok` шлёт в Telegram. Числа подписок в ручке нет и быть не может: она анонимная, а `push_subscriptions` под RLS.
- Успех отправки логируется (`push.sent`) наравне с отказом: пустой журнал не должен читаться как «всё хорошо».
- Таймаут транспорта — 10 с. Без него `requests` внутри `asyncio.to_thread` держал бы поток общего executor'а (там же чистятся блобы вложений).

## Подписка

1. При первом логине в PWA — **не auto-prompt**. Кнопка «Включить уведомления» в Settings или баннер `PushPermissionPrompt` после логина (только при `Notification.permission === 'default'`).
2. `usePush().subscribe()` — `Notification.requestPermission()` → `pushManager.subscribe({userVisibleOnly: true, applicationServerKey: <vapid_public_key>})`.
3. `POST /api/push/subscribe` — `{endpoint, keys: {p256dh, auth}}`. Backend делает UPSERT по `endpoint` (`ON CONFLICT (endpoint) DO UPDATE SET employee_id=EXCLUDED.employee_id, last_seen_at=NOW()`).
4. **Тихая переподписка при запуске приложения** — `usePushAutoRefresh` в `Shell` (корневой лэйаут!), правила в `web/src/lib/pushRefresh.ts`. Восстанавливает подписку, которую отозвал iOS, и продлевает `last_seen_at`. Живёт НЕ в `usePush`: тот монтируется только в `PushPermissionPrompt` (главная трекера) и в настройках — PWA, открытая на «Обучении» или по ссылке из пуша, его бы не смонтировала. Три условия: разрешение `granted`, отметка `hub:push-opted-in` (её снимает «Отписаться» — иначе тихая логика вернула бы то, что человек выключил) и не чаще раза в 12 ч.
5. **Гейт свежести** (`settings.push_freshness_days`, 30): шлём только по подпискам, подтверждённым за этот срок. Пара «гейт + продление» неразделима — гейт без продления просто выключает пуши. Разово продлить существующие подписки: `app/jobs/touch_push_subscriptions.py` (только `bypass_session_factory()` — таблица под RLS, а джоба кросс-тенантная).
6. **Самопроверка** — `POST /api/push/test` (rate-limit 10/час) и кнопка «Проверить» в «Настройки → Уведомления». Текст ответа собирает `push_sender.describe_push_result`: «не настроено на сервере», «устройство не подписано», «подписка давно не подтверждалась», «устройство больше не принимает» — пять разных бед выглядят для человека одинаково, и каждая обязана назвать себя.
7. **Общее устройство: подписка следует за вошедшим (09.09).** Выход (`lib/session.ts`) отзывает строку на сервере — `DELETE /api/push/subscribe?endpoint=…` ГОЛЫМ `fetch` с токеном из `authClient.getAccessToken()` (через axios нельзя: интерцептор `attachAxiosAuth` на 401 делает `startLogin()`, и «Выйти» с протухшей сессией возвращало бы человека внутрь приложения), `keepalive: true`, таймаут 2 с, ошибки глотаются. **Браузерная подписка при выходе НЕ отменяется и `hub:push-opted-in` не снимается** — иначе вернувшемуся пришлось бы включать уведомления заново; снимается только привязка к человеку. Отзыв из браузера best-effort (вкладку закрыли, сеть отвалилась), поэтому вторая линия — на входе: `hub:push-owner` хранит, на кого endpoint привязан на сервере, и `shouldSyncPush` при `owner !== employeeId` **обходит 12-часовой троттл**, перевешивая endpoint на нового вошедшего за секунды вместо полусуток. Осознанное следствие: на устройстве с ранее выданным разрешением следующий вошедший получает свои пуши молча — разрешение принадлежит браузеру, а не аккаунту.

## Триггеры: task-домен (7 kinds)

| kind | Когда | Кому |
|---|---|---|
| `task.assigned_to_me` | меня добавили в исполнители (`POST /tasks/{id}/assignees` или `PATCH assignee_ids`; исполнители — `task_assignees`) | новому исполнителю |
| `task.mentioned` | в комментарии есть `@me` | упомянутому |
| `task.commented_on_watched` | новый коммент на наблюдаемой задаче | всем watchers кроме автора |
| `task.status_changed_on_watched` | смена этапа/статуса (`stage_id` → `set_stage`, зеркало `status`; в тексте — имя этапа) | всем watchers кроме автора |
| `task.due_soon` | `status != 'done'` и `due_at` в течение 24ч | assignee + watchers |
| `task.overdue` | `status != 'done'` и `due_at < NOW()` | assignee + watchers |
| `task.reminder` | личное напоминание «ко времени» (0062): разовое или правило от срока/старта; воркер в lifespan, раз в 20 с | только тому, кто поставил |

## Триггеры: learn-домен (16 kinds)

Источник истины полного списка — `app/services/notification_prefs.py::NOTIFICATION_KINDS` (фронт-словарь `web/src/lib/notificationKinds.ts`, реэкспорт через `notifications.ts`, синхронен — менять парой).

| kind | Когда | Кому |
|---|---|---|
| `library.ack_required` | публикация материала с обязательным ознакомлением / вступление в аудиторию | членам аудитории без ack |
| `content.review_due` | подошёл срок проверки актуальности материала (cron) | владельцу материала |
| `news.published` | публикация новости (батч) | аудитории новости |
| `news.ack_required` | новость с обязательным ознакомлением | аудитории без ack |
| `survey.assigned` | публикация опроса (батч) | аудитории опроса |
| `course.assigned` | назначение курса (manual/automation/self + mandatory-hook) | назначенному |
| `course.due_soon` | дедлайн назначенного курса близко (cron daily 06:15) | назначенному |
| `quiz.review_needed` | попытка с open-вопросами ушла на проверку | проверяющим (publisher+) |
| `quiz.reviewed` | HR финализировал проверку попытки | автору попытки |
| `profile.inactivity` | правило неактивности: warn перед авто-архивом (cron daily 07:00) | сотруднику + руководителю |
| `shift.new` | опубликована смена на бирже (батч по должности) | подходящим по должности |
| `shift.application` | новый отклик на смену | менеджеру смены |
| `shift.result` | назначение/отмена по смене | участникам |
| `assessment.assigned` | запуск кампании аттестации (батч) | аудитории кампании |
| `race.started` | «Гусиная гонка»: заезд стартовал (часовая джоба, не раньше 09:00 MSK; дедуп `races.started_notified_at`) | людям (не кассам) включённых точек |
| `race.record` | закрытый день дал новый максимум заезда у точки (оценивается ночным закрытием, шлётся часовой джобой по одному дню на точку; дедуп `race_snapshots.record_notified_at`) | людям этой точки |

## Пользовательские настройки

`GET/PUT /api/notifications/preferences` — per-kind, per-channel: `prefs: { [kind]: {push: boolean, in_app: boolean} }`. По умолчанию оба канала включены. Legacy-формат `{[kind]: boolean}` (до 3.6.7) принимается на чтении через `normalize_prefs()` — оба канала следуют булю; новые записи сохраняются строго в новом формате (без миграции). Dispatcher проверяет `should_send_push` / `should_send_inapp` раздельно.

## Cron / systemd timers

- `signaris-hub[-staging]-due-soon.timer` — hourly, `python -m app.jobs.due_soon`.
- `signaris-hub[-staging]-overdue.timer` — daily 09:00 MSK, `app.jobs.overdue`.
- `signaris-hub[-staging]-course-due-soon.timer` — daily 06:15 UTC, `app.jobs.course_due_soon`.
- `signaris-hub[-staging]-review-due.timer` — daily 06:30 UTC, `app.jobs.review_due`.
- `signaris-hub[-staging]-inactivity.timer` — daily 07:00 UTC, `app.jobs.inactivity`.
- `signaris-hub[-staging]-automations.timer` — hourly :20, `app.jobs.automations_run`.
- `signaris-hub[-staging]-race-sync.timer` — hourly :40, `app.jobs.race_sync` (дотяжка iiko + пуши гонки); `race-close.timer` — 00:45 UTC, `app.jobs.race_close` (без пушей).
- **Личные напоминания (0062) — НЕ таймер, а воркер в lifespan** (`app/services/task_reminders.py::start_worker` под `supervise("task-reminders")`, опрос `SIGNARIS_HUB_TASK_REMINDERS_POLL_SEC`=20). Дубль сторожит сама строка (разовое удаляется, правило засыпает с `fired_anchor_at`), а не таблица `notifications` — поэтому «только пуш» (in_app выключен) не повторяется, в отличие от `due_soon`. Пуши — после commit, фоном по тенантам (семафор 2). Подсказка в карточке «придёт только во «Входящие»» считается из `delivery` ручки `GET /tasks/{id}/reminders` (свежие подписки + prefs вида + `vapid_status`). В открытом приложении пришедшее напоминание показывает тост (`useReminderToasts`).

**Пуши из джоб и commit.** `notify_many` планирует push ДО commit'а вызывающего; там, где в той же транзакции ставятся метки дедупа (гонка), порядок другой — `queue_many` → commit → `schedule_push_batch`, иначе откат вернул бы метки и через час рассылка повторилась бы. Каждая джоба в конце зовёт `notify_batch.drain(timeout_sec=120)`: без него `asyncio.run` отменяет незавершённые фоновые задачи и хвост рассылки теряется молча; параллельность отправки — `PUSH_CONCURRENCY=4` сессии.

Анти-дубль: каждый запуск `due_soon` проверяет `NOT EXISTS (SELECT 1 FROM notifications WHERE kind='task.due_soon' AND payload->>'task_id' = tasks.id::text AND created_at > NOW() - INTERVAL '23 hours')`. Воркеры крутят `tenant_scoped_session(None, bypass_rls=True)` (системные).

## Доставка

Разделение ответственности (после 3.6.7):

- **`app/services/notification_dispatcher.py::dispatch`** — единая точка: загружает prefs один раз, раздельно проверяет `should_send_inapp` (→ INSERT в `notifications`) и `should_send_push` (→ планирует push). Кастомные callers `queue_notification` / `schedule_push` prefs НЕ проверяют — это ответственность вызывающего.
- **`app/services/push_sender.py::send_to_employee(employee_id, payload)`** — только транспорт: читает `push_subscriptions` юзера, параллельно шлёт `pywebpush(..., vapid_claims={"sub": settings.vapid_subject})`, на `410 Gone`/`404` удаляет подписку из БД. Prefs не читает, in-app записей не создаёт.

## In-app Inbox

- `GET /api/notifications?unread_only=&limit=&before=` — keyset-пагинация.
- `POST /api/notifications/{id}/read` + `POST /api/notifications/read-all`.
- `GET /api/notifications/unread-count` — бейдж «Входящие» (Sidebar на десктопе, нижний tab bar на мобиле).
- **Экран открывается на «Непрочитанных»** (31.08, решение владельца): «Входящие» — список дел, а не архив, и у активного сотрудника прочитанное измеряется сотнями. `unreadOnly` — локальный `useState`, живёт до ухода со страницы: это дефолт, а не сохранённая настройка.
- **Чипы «Все / Непрочитанные» есть на ОБЕИХ раскладках.** На телефоне их прежде не было (так был нарисован макет), и пока список открывался на «Все», это ничего не стоило; с новым дефолтом их отсутствие означало бы, что прочитанное с телефона недостижимо вовсе. Компонент один — `InboxFilters` в `pages/InboxPage.tsx`.
- Тексты счётчика и пустого состояния — чистые `lib/inboxView.ts` (`inboxCounter`, `inboxEmpty`), там же тест. Оба на прежней ветке врали: «Здесь пока тихо» человеку с двумя сотнями прочитанных, а счётчик — числом из длины СПИСКА, которая упирается в лимит ручки (50): у сотрудника со 160 непрочитанными подпись говорила «50». Число берётся из `useUnreadCount()` — того же источника, что бейдж сайдбара (ключ общий, лишнего запроса нет; `useMarkRead`/`useMarkAllRead` инвалидируют весь префикс `['notifications']`). Дроби «N из M» больше нет: общего счётчика уведомлений сервер не отдаёт, а M было числом загруженных.

## iOS особенности

- Push работает **только в installed PWA** (стандартное ограничение Apple, с iOS 16.4).
- `IOSInstallBanner.tsx` показывает инструкцию «Добавьте на главный экран» при детекте `iphone|ipad|ipod` + `!window.navigator.standalone`.
- `sessionStorage` флаг `ios-banner-dismissed` — чтобы баннер не появлялся в той же сессии после отмены.
