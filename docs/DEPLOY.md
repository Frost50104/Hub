# Deploy

## Окружения

| | staging | prod |
|---|---|---|
| Домен | `hub-staging.signaris.ru` | `hub.signaris.ru` |
| systemd | `signaris-hub-staging.service` | `signaris-hub.service` |
| `/opt` путь | `/opt/signaris-hub-staging/` | `/opt/signaris-hub/` |
| Postgres DB | `signaris_hub_staging_db` | `signaris_hub_db` |
| Redis DB | 5 | 4 |
| Backend port | 5060 | 5059 |
| Build команда | `npm run build:staging` | `npm run build` |

**VPS:** оба окружения на одном новом VPS `94.241.168.8` (Ubuntu 24.04 LTS). Авторизация — root по паролю (пароль в локальном `Hub/CLAUDE.md` → СЕКРЕТЫ).

**VAPID-ключ:** единый для двух env, лежит в `/opt/signaris-hub/vapid_private.pem` (mode 600 root:signaris).

## deploy.sh

Форк из `AXO_bot_web/deploy/deploy.sh`. Использование:

```bash
./deploy/deploy.sh staging              # backend + frontend
./deploy/deploy.sh prod                 # backend + frontend
./deploy/deploy.sh staging backend      # только backend
./deploy/deploy.sh prod frontend        # только frontend
```

Что делает:

1. Пишет корневой `VERSION` и `web/public/version.json` — git-hash + dirty-флаг + timestamp.
2. `rsync` (без `--delete`) в `/opt/signaris-hub[-staging]/`.
3. На VPS: `pip install` + `alembic upgrade head` (backend) и `npm install && npm run build[:staging]` (frontend).
4. `systemctl restart signaris-hub[-staging]` + smoke-check на `https://hub[-staging].signaris.ru/api/env`.

## Rollback

Релизного каталога нет (rsync поверх `/opt/...`), откат = redeploy предыдущего git-состояния + при необходимости откат БД.

1. **Код (backend + frontend):**
   ```bash
   git stash                      # если есть незакоммиченное
   git checkout <прошлый-hash>    # хеш из version.json до деплоя
   ./deploy/deploy.sh prod
   git checkout main && git stash pop
   ```
   `alembic upgrade head` на старом коде — no-op (лишние ревизии БД он не откатит, аддитивные миграции старому коду не мешают).

2. **Миграция, которую нужно откатить** (деструктивная/сломанная):
   ```bash
   ssh root@94.241.168.8
   cd /opt/signaris-hub && ./.venv/bin/alembic downgrade <prev_rev>
   ```

3. **Данные испорчены** — restore из pre-migration снапшота (deploy.sh снимает его перед каждым `alembic upgrade`, хранятся последние 5 в `/opt/signaris-hub/backups/pre-migrate/`):
   ```bash
   systemctl stop signaris-hub
   sudo -u postgres pg_restore --clean --if-exists -d signaris_hub_db \
     /opt/signaris-hub/backups/pre-migrate/db-signaris_hub_db-<ts>.dump
   systemctl start signaris-hub
   ```
   Суточные дампы — в `/opt/signaris-hub/backups/daily/` (plain SQL.gz: `zcat ... | sudo -u postgres psql -d <db>`).

После любого отката: `curl https://hub.signaris.ru/api/env` + smoke по основным страницам; фронт может требовать hard-refresh из-за PWA-кэша (баннер обновления).

## Bootstrap нового VPS

Один раз при provision'е `94.241.168.8`:

```bash
./deploy/bootstrap-vps.sh
```

Что делает (idempotent):

1. `apt install postgresql-16 redis-server nginx certbot python3.12 python3.12-venv nodejs npm`
2. `useradd signaris`, создание `/opt/signaris-hub[-staging]/`
3. Генерация VAPID-пары → `/opt/signaris-hub/vapid_private.pem` (mode 600 root:signaris)
4. `createdb signaris_hub_db signaris_hub_staging_db`, `createuser signaris_hub` (non-superuser, пароль в `/opt/signaris-hub/.env`)
5. Redis: `bind 127.0.0.1`, `databases >= 6` (auth=3, hub-prod=4, hub-staging=5)
6. Копирование systemd-юнитов из `ops/systemd/` + `systemctl enable`
7. Копирование nginx-конфигов из `ops/nginx/`
8. `certbot --nginx -d hub.signaris.ru -d hub-staging.signaris.ru`

## Healthcheck-алерты

`signaris-hub-healthcheck.timer` каждые 5 минут запускает `scripts/healthcheck.sh` (деплоится bootstrap-скриптом в `/opt/signaris-hub/scripts/`). Скрипт curl-ит `/api/env` обоих окружений и на 2 consecutive failures шлёт алерт (edge-trigger, recovery-сообщение при восстановлении).

Каналы (оба опциональны, настраиваются в `/etc/default/signaris-hub-healthcheck` на VPS — файл НЕ в git):

```bash
# email — требует установленного mail(1)/MTA на VPS
HEALTHCHECK_ALERT_EMAIL=ops@signaris.ru
# Telegram — бот от @BotFather; без обеих переменных канал молча выключен
TELEGRAM_BOT_TOKEN=123456:ABC-...
TELEGRAM_CHAT_ID=-100123456789
```

После правки env-файла ничего перезапускать не нужно (oneshot-сервис читает его при каждом запуске). Проверка: временно вписать несуществующий URL в `HEALTHCHECK_URLS` → через ~10 минут придёт DOWN-сообщение, после удаления — OK-сообщение.

## DNS

A-записи:
- `hub.signaris.ru` → `94.241.168.8`
- `hub-staging.signaris.ru` → `94.241.168.8`

## CORS / SSO redirect whitelist (в env auth)

`signaris-auth` развёрнут в **единственном экземпляре** на VPS `194.87.215.15` (`auth.signaris.ru`) — отдельного staging-instance нет. Staging-домены продуктов добавляются в env того же сервиса. Env-файл на хосте auth: `/etc/signaris-auth/signaris-auth.env`. После правки — `systemctl restart signaris-auth` (не `reload` — в unit нет `ExecReload`, и `EnvironmentFile` читается только при старте процесса).

Добавляется в две фазы:

- **Hub-MVP.1 (staging):** `SIGNARIS_AUTH_CORS_ORIGINS += https://hub-staging.signaris.ru` + `SIGNARIS_AUTH_SSO_REDIRECT_ORIGINS += https://hub-staging.signaris.ru` → `systemctl restart signaris-auth`.
- **Hub-MVP.6 (prod):** то же для `https://hub.signaris.ru` → `systemctl restart signaris-auth`.

## Активация hub в auth (после Hub-MVP.6)

В `CentralAuthService/app/constants/products.py`:
```python
INTEGRATED_PRODUCTS: frozenset[str] = frozenset({"net", "sonar", "hub"})
```

Затем через UI auth.signaris.ru:
1. UPPETIT-tenant → `purchased_products += ["hub"]`
2. Владелец UPPETIT → RoleEditor → выдать `hub:admin`
3. Получить service-key для deletion-sync → `SIGNARIS_HUB_SIGNARIS_SERVICE_KEY` в `/opt/signaris-hub/.env`
4. `systemctl restart signaris-hub`
