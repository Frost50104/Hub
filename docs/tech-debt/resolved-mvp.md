# TECH_DEBT — Решённое в MVP

Исторический список закрытых упрощений MVP. Часть `docs/TECH_DEBT.md` (индекс); hot-инварианты — в `CLAUDE.md`.

## Решённое в MVP

- Single-flight refresh — реализуется через `attachAxiosAuth` из `@signaris/auth-client/browser` (не пишем вручную).
- Rate-limit Redis + DB fallback — копия из `CentralAuthService/app/security/rate_limit.py`.
- iOS PWA-freeze таймеров в фоне — лечится через `visibilitychange`-trigger проверки SW в `UpdateBanner.tsx`.
