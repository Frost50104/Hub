# TECH_DEBT — Инциденты

Разборы инцидентов с первопричиной и инвариантами, которые из них выросли. Часть `docs/TECH_DEBT.md` (индекс); hot-инварианты — в `CLAUDE.md`.

## Инцидент 2026-08-01 — кросс-tenant RLS-утечка через пул соединений (ИСПРАВЛЕНО)

Пётр (tenant `signaris`) на проде видел проекты/задачи tenant'а `uppetit`: флаппинг 404/200 одного URL, сайдбар с чужими проектами, `/api/me` 500 (`InsufficientPrivilegeError` на INSERT `employee_profiles`).

**Корень:** `tenant_scoped_session` ставил GUC **session-level** один раз при открытии сессии, а `get_db` коммитит shadow-upsert'ы ДО yield → соединение возвращалось в пул (FIFO), и бизнес-запросы роутов исполнялись на другом соединении со stale-GUC чужого tenant'а (или `bypass_rls=on` от воркеров sid-sync/deletion-sync в том же пуле). Пока активен один tenant — не проявлялось; накануне последним в проде был UPPETIT → пул «покрашен» в чужой tenant.

**Фикс:** листенер `app/db.py::_apply_rls_on_begin` (`after_begin` + `SET LOCAL`, порт эталона `CentralAuthService/app/db.py` post-`3cfb256`) перепроставляет оба GUC на старте каждой транзакции. Сопутствующее: `bypass_session_factory()` для lib-воркера deletion-sync (сырая фабрика работала только благодаря утечке — иначе `mark_shadow_deleted` молча обновлял 0 строк); `public.py` stage 2 переведён с bypass на tenant-скоуп (`_mention_names` раскрывал имена/email чужих tenant'ов). Регресс — `tests/integration/test_rls_mid_session_commit.py` (фикстура `rls_enforced`: non-superuser роль, RLS реально enforced; до-фиксовый код валит 2 из 4 тестов).

**Тот же пре-фиксовый `db.py` несёт Listen** (`Listen/app/db.py` + pre-yield commit в `deps.py`; хуже — `device_auth.py` коммитит bypass-сессии → наследник получает полный bypass). Чинить отдельной сессией.
