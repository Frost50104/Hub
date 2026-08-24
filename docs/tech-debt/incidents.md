# TECH_DEBT — Инциденты

Разборы инцидентов с первопричиной и инвариантами, которые из них выросли. Часть `docs/TECH_DEBT.md` (индекс); hot-инварианты — в `CLAUDE.md`.

## Инцидент 2026-08-24 — истёкшие TLS-сертификаты обоих env (ИСПРАВЛЕНО)

Прод и staging перестали открываться: браузер показывал «Network Error» на каждом запросе, PWA рисовала оболочку из кэша SW, но `/api/*` не отвечал. В логах nginx от IP пользователя не было НИ ОДНОГО запроса — TLS-хендшейк падал до записи в access-лог.

**Корень:** сертификаты Let's Encrypt обоих доменов истекли 2026-08-24 в 12:00 UTC. Автопродление падало минимум с 23.08: в `/etc/letsencrypt/renewal/*.conf` стоял `authenticator = standalone`, а standalone-плагину нужен порт 80, занятый nginx («Could not bind TCP port 80»). Certbot-таймер отрабатывал и молча возвращал ошибку.

**Почему заметили поздно:** healthcheck сработал штатно (`curl -fs` не проходит проверку сертификата) — 18 падений подряд и Telegram-алерт в 12:10 UTC, но на него не отреагировали. Деплой 0042 в 13:24 к поломке отношения не имел: он лишь совпал по времени, и предеплойные проверки шли `curl --insecure` с самого сервера — именно поэтому не поймали протухший сертификат.

**Фикс:** продление переведено на `webroot` (`/var/www/certbot`), в оба site-конфига добавлена локация `^~ /.well-known/acme-challenge/`. Важная деталь nginx: `return 301` **на уровне server** отрабатывает в rewrite-фазе ДО выбора локации и перебивал challenge — редирект перенесён в `location /`. Добавлен deploy-hook `/etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh` (без reload новый сертификат лежит на диске, а nginx держит в памяти старый). `certbot renew --dry-run` проходит.

**Инвариант:** предеплойная и постдеплойная проверка прода делается СНАРУЖИ и с валидацией TLS (`curl https://hub.signaris.ru/api/env` без `--insecure`), а не только `curl http://127.0.0.1:5059` с сервера — локальная проба зелёная и при мёртвом сертификате.

**Сопутствующая ошибка агента (устранена):** бэкап конфигов делался двумя `cp -a` в ОДИН каталог — `/etc/nginx/sites-enabled/*.conf` (симлинки в `sites-available`) и `/etc/letsencrypt/renewal/*.conf` совпадают по базовым именам, поэтому второй `cp` записался через симлинк и затёр оба конфига nginx их renewal-тёзками. Восстановлено из `ops/nginx/*.conf` (репозиторий — источник истины, md5 совпал с копиями в `/tmp` от 20.08). **Правило: копии разных путей — в разные подкаталоги, и `cp --no-dereference` при работе с symlink-деревьями.**

## Инцидент 2026-08-01 — кросс-tenant RLS-утечка через пул соединений (ИСПРАВЛЕНО)

Пётр (tenant `signaris`) на проде видел проекты/задачи tenant'а `uppetit`: флаппинг 404/200 одного URL, сайдбар с чужими проектами, `/api/me` 500 (`InsufficientPrivilegeError` на INSERT `employee_profiles`).

**Корень:** `tenant_scoped_session` ставил GUC **session-level** один раз при открытии сессии, а `get_db` коммитит shadow-upsert'ы ДО yield → соединение возвращалось в пул (FIFO), и бизнес-запросы роутов исполнялись на другом соединении со stale-GUC чужого tenant'а (или `bypass_rls=on` от воркеров sid-sync/deletion-sync в том же пуле). Пока активен один tenant — не проявлялось; накануне последним в проде был UPPETIT → пул «покрашен» в чужой tenant.

**Фикс:** листенер `app/db.py::_apply_rls_on_begin` (`after_begin` + `SET LOCAL`, порт эталона `CentralAuthService/app/db.py` post-`3cfb256`) перепроставляет оба GUC на старте каждой транзакции. Сопутствующее: `bypass_session_factory()` для lib-воркера deletion-sync (сырая фабрика работала только благодаря утечке — иначе `mark_shadow_deleted` молча обновлял 0 строк); `public.py` stage 2 переведён с bypass на tenant-скоуп (`_mention_names` раскрывал имена/email чужих tenant'ов). Регресс — `tests/integration/test_rls_mid_session_commit.py` (фикстура `rls_enforced`: non-superuser роль, RLS реально enforced; до-фиксовый код валит 2 из 4 тестов).

**Тот же пре-фиксовый `db.py` несёт Listen** (`Listen/app/db.py` + pre-yield commit в `deps.py`; хуже — `device_auth.py` коммитит bypass-сессии → наследник получает полный bypass). Чинить отдельной сессией.
