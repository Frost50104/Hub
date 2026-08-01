# Push notifications

## VAPID

- Генерируется один раз через `scripts/generate_vapid.py`.
- **Public key** — в env как `SIGNARIS_HUB_VAPID_PUBLIC_KEY`, отдаётся фронту через `GET /api/env` → `VITE_VAPID_PUBLIC_KEY` (через build) или env-fetch.
- **Private key** — файл `/opt/signaris-hub/vapid_private.pem` (mode 600 root:signaris). В env только путь `SIGNARIS_HUB_VAPID_PRIVATE_KEY_PATH`. **В коде не хранится никогда.**
- `vapid_subject` = `mailto:ops@signaris.ru`.
- **Ключ единый для prod + staging** (как у Desk). Раздельные ключи — будущая работа, см. `docs/TECH_DEBT.md`.

## Подписка

1. При первом логине в PWA — **не auto-prompt**. Кнопка «Включить уведомления» в Settings или баннер `PushPermissionPrompt` после логина (только при `Notification.permission === 'default'`).
2. `usePush().subscribe()` — `Notification.requestPermission()` → `pushManager.subscribe({userVisibleOnly: true, applicationServerKey: <vapid_public_key>})`.
3. `POST /api/push/subscribe` — `{endpoint, keys: {p256dh, auth}}`. Backend делает UPSERT по `endpoint` (`ON CONFLICT (endpoint) DO UPDATE SET employee_id=EXCLUDED.employee_id, last_seen_at=NOW()`).

## Триггеры: task-домен (6 kinds)

| kind | Когда | Кому |
|---|---|---|
| `task.assigned_to_me` | `PATCH /api/tasks/{id}` меняет `assignee_id` на меня | новому assignee |
| `task.mentioned` | в комментарии есть `@me` | упомянутому |
| `task.commented_on_watched` | новый коммент на наблюдаемой задаче | всем watchers кроме автора |
| `task.status_changed_on_watched` | PATCH меняет `status` | всем watchers кроме автора |
| `task.due_soon` | `status != 'done'` и `due_at` в течение 24ч | assignee + watchers |
| `task.overdue` | `status != 'done'` и `due_at < NOW()` | assignee + watchers |

## Триггеры: learn-домен (14 kinds)

Источник истины полного списка — `app/services/notification_prefs.py::NOTIFICATION_KINDS` (фронт-словарь `web/src/lib/notifications.ts` синхронен).

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

## Пользовательские настройки

`GET/PUT /api/notifications/preferences` — per-kind, per-channel: `prefs: { [kind]: {push: boolean, in_app: boolean} }`. По умолчанию оба канала включены. Legacy-формат `{[kind]: boolean}` (до 3.6.7) принимается на чтении через `normalize_prefs()` — оба канала следуют булю; новые записи сохраняются строго в новом формате (без миграции). Dispatcher проверяет `should_send_push` / `should_send_inapp` раздельно.

## Cron / systemd timers

- `signaris-hub[-staging]-due-soon.timer` — hourly, `python -m app.jobs.due_soon`.
- `signaris-hub[-staging]-overdue.timer` — daily 09:00 MSK, `app.jobs.overdue`.
- `signaris-hub[-staging]-course-due-soon.timer` — daily 06:15 UTC, `app.jobs.course_due_soon`.
- `signaris-hub[-staging]-review-due.timer` — daily 06:30 UTC, `app.jobs.review_due`.
- `signaris-hub[-staging]-inactivity.timer` — daily 07:00 UTC, `app.jobs.inactivity`.
- `signaris-hub[-staging]-automations.timer` — hourly :20, `app.jobs.automations_run`.

Анти-дубль: каждый запуск `due_soon` проверяет `NOT EXISTS (SELECT 1 FROM notifications WHERE kind='task.due_soon' AND payload->>'task_id' = tasks.id::text AND created_at > NOW() - INTERVAL '23 hours')`. Воркеры крутят `tenant_scoped_session(None, bypass_rls=True)` (системные).

## Доставка

Разделение ответственности (после 3.6.7):

- **`app/services/notification_dispatcher.py::dispatch`** — единая точка: загружает prefs один раз, раздельно проверяет `should_send_inapp` (→ INSERT в `notifications`) и `should_send_push` (→ планирует push). Кастомные callers `queue_notification` / `schedule_push` prefs НЕ проверяют — это ответственность вызывающего.
- **`app/services/push_sender.py::send_to_employee(employee_id, payload)`** — только транспорт: читает `push_subscriptions` юзера, параллельно шлёт `pywebpush(..., vapid_claims={"sub": settings.vapid_subject})`, на `410 Gone`/`404` удаляет подписку из БД. Prefs не читает, in-app записей не создаёт.

## In-app Inbox

- `GET /api/notifications?unread_only=&limit=&before=` — keyset-пагинация.
- `POST /api/notifications/{id}/read` + `POST /api/notifications/read-all`.
- `GET /api/notifications/unread-count` — бейдж «Входящие» (Sidebar на десктопе, нижний tab bar на мобиле).

## iOS особенности

- Push работает **только в installed PWA** (стандартное ограничение Apple, с iOS 16.4).
- `IOSInstallBanner.tsx` показывает инструкцию «Добавьте на главный экран» при детекте `iphone|ipad|ipod` + `!window.navigator.standalone`.
- `sessionStorage` флаг `ios-banner-dismissed` — чтобы баннер не появлялся в той же сессии после отмены.
