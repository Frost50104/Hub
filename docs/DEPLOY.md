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

1. Пишет `backend/VERSION` и `web/public/version.json` — git-hash + dirty-флаг + timestamp.
2. `rsync` (без `--delete`) в `/opt/signaris-hub[-staging]/`.
3. На VPS: `pip install` + `alembic upgrade head` (backend) и `npm install && npm run build[:staging]` (frontend).
4. `systemctl restart signaris-hub[-staging]` + smoke-check на `https://hub[-staging].signaris.ru/api/env`.

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

## DNS

A-записи:
- `hub.signaris.ru` → `94.241.168.8`
- `hub-staging.signaris.ru` → `94.241.168.8`

## CORS / SSO redirect whitelist (в env auth)

Добавляется в две фазы:

- **Hub-MVP.1 (staging):** в env `signaris-auth-staging`:
  - `SIGNARIS_AUTH_CORS_ORIGINS += https://hub-staging.signaris.ru`
  - `SIGNARIS_AUTH_SSO_REDIRECT_ORIGINS += https://hub-staging.signaris.ru`
  - `systemctl reload signaris-auth-staging`
- **Hub-MVP.6 (prod):** в env `signaris-auth.service`:
  - `SIGNARIS_AUTH_CORS_ORIGINS += https://hub.signaris.ru`
  - `SIGNARIS_AUTH_SSO_REDIRECT_ORIGINS += https://hub.signaris.ru`
  - `systemctl reload signaris-auth.service`

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
