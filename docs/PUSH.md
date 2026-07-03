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

## Триггеры (MVP)

| kind | Когда | Кому |
|---|---|---|
| `task.assigned_to_me` | `PATCH /api/tasks/{id}` меняет `assignee_id` на меня | новому assignee |
| `task.mentioned` | в комментарии есть `@me` | упомянутому |
| `task.commented_on_watched` | новый коммент на наблюдаемой задаче | всем watchers кроме автора |
| `task.status_changed_on_watched` | PATCH меняет `status` | всем watchers кроме автора |
| `task.due_soon` | `status != 'done'` и `due_at` в течение 24ч | assignee + watchers |
| `task.overdue` | `status != 'done'` и `due_at < NOW()` | assignee + watchers |

## Пользовательские настройки

`GET/PUT /api/notifications/preferences` — `prefs: { [kind]: boolean }`. По умолчанию все триггеры включены. Воркер пушей перед отправкой смотрит `notification_preferences.prefs[kind]` — если `false`, пропускает (но всё равно создаёт запись в `notifications` для in-app Inbox).

## Cron / systemd timers

- `signaris-hub-due-soon.timer` — `OnCalendar=hourly`. Запускает `python -m app.jobs.due_soon`.
- `signaris-hub-overdue.timer` — `OnCalendar=*-*-* 09:00:00`. Запускает `python -m app.jobs.overdue`.

Анти-дубль: каждый запуск `due_soon` проверяет `NOT EXISTS (SELECT 1 FROM notifications WHERE kind='task.due_soon' AND payload->>'task_id' = tasks.id::text AND created_at > NOW() - INTERVAL '23 hours')`. Воркеры крутят `tenant_scoped_session(None, bypass_rls=True)` (системные).

## Доставка

`app/services/push_sender.py::send_to_employee(employee_id, payload)`:

1. Читает `notification_preferences.prefs[kind]` — если `false`, skip.
2. Читает все `push_subscriptions` юзера.
3. Параллельно `pywebpush(subscription_info=..., data=json.dumps(payload), vapid_private_key=..., vapid_claims={"sub": settings.vapid_subject})`.
4. На `410 Gone` или `404` — удалить подписку из БД (стандартная санитизация).
5. Параллельно `INSERT` в `notifications` (in-app Inbox).

## In-app Inbox

- `GET /api/notifications?unread_only=&limit=&before=` — keyset-пагинация.
- `POST /api/notifications/{id}/read` + `POST /api/notifications/read-all`.
- `GET /api/notifications/unread-count` — бейдж «Входящие» (Sidebar на десктопе, нижний tab bar на мобиле).

## iOS особенности

- Push работает **только в installed PWA** (стандартное ограничение Apple, с iOS 16.4).
- `IOSInstallBanner.tsx` показывает инструкцию «Добавьте на главный экран» при детекте `iphone|ipad|ipod` + `!window.navigator.standalone`.
- `sessionStorage` флаг `ios-banner-dismissed` — чтобы баннер не появлялся в той же сессии после отмены.
