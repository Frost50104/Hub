# Tech debt

Открытые вопросы, упрощения и known-issues. Заполняется по мере накопления.

## Открытое

- **Множественные uvicorn-воркеры опрашивают deletion-sync N раз.** В MVP крутим `--workers 1`. При масштабировании — Redis leader-election (см. `INTEGRATION.md` шаг 14, шаблон `try_acquire_lock`).
- **VAPID-ключ единый для prod+staging.** Удобно (как у Desk), но если staging-баг утечёт public key, теоретически prod-подписки можно подделать. Низкая вероятность. Раздельные ключи — future work.
- **LexoRank-style `tasks.position NUMERIC`** может «насыщаться» при многих DnD-миграциях карточек. При дельте <0.001 — фоновый rebalance колонки в PATCH-хендлере (реализуется в MVP.3).
- **Подзадачи только 1 уровень** (`parent_task_id` CHECK depth=1). Глубже потребует tree-CTE в запросах и отдельной миграции.
- **Email-коллизии между tenant'ами в `shadow_users`** — для пустого старта Hub проблемы нет; если когда-то будем мигрировать данные, нужен pre-migration report (см. `INTEGRATION.md` шаг 12).

## Упрощения MVP

- Поиск без DSL-фильтров (только базовый title-like).
- Кастом-статусы / кастом-поля задач — отсутствуют.
- Гости (внешние пользователи) и публичные ссылки — отсутствуют.
- Time tracking — отсутствует.
- Calendar / Timeline / Gantt — отсутствуют.

## Решённое в MVP

- Single-flight refresh — реализуется через `attachAxiosAuth` из `@signaris/auth-client/browser` (не пишем вручную).
- Rate-limit Redis + DB fallback — копия из `CentralAuthService/app/security/rate_limit.py`.
- iOS PWA-freeze таймеров в фоне — лечится через `visibilitychange`-trigger проверки SW в `UpdateBanner.tsx`.
