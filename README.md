# Signaris Hub

Корпоративный таск-трекер уровня Asana — седьмой продукт экосистемы [Signaris](https://signaris.ru).

- **Прод:** [hub.signaris.ru](https://hub.signaris.ru)
- **Staging:** [hub-staging.signaris.ru](https://hub-staging.signaris.ru)
- **Авторизация:** через центральный identity provider [auth.signaris.ru](https://auth.signaris.ru) — никакого собственного логина/пароля/MFA.
- **Phase:** 3.6 в роадмапе Signaris (см. `CentralAuthService/docs/PHASES_ROADMAP.md`).

## Стек

- **Backend:** Python 3.12, FastAPI async, SQLAlchemy 2, PostgreSQL 16 (RLS), Redis 7, Alembic, `signaris-auth-client[fastapi,sqlalchemy]>=0.4.0`, pywebpush
- **Frontend:** React 18, TypeScript strict, Vite + vite-plugin-pwa, Tailwind, TanStack Query v5, zustand, @dnd-kit/core, @sentry/react
- **Infra:** Ubuntu 24.04, nginx + uvicorn + systemd, Let's Encrypt

## Структура

```
Hub/
├── app/            # FastAPI backend
├── migrations/     # Alembic
├── tests/          # pytest (unit + integration с testcontainers)
├── web/            # React 18 TSX PWA
├── deploy/         # deploy.sh + bootstrap-vps.sh
├── ops/            # systemd units + nginx configs
└── docs/           # ARCHITECTURE / DEPLOY / ROADMAP / PUSH / TECH_DEBT
```

## Документация

- `docs/ARCHITECTURE.md` — сущности, RLS, auth-flow, push-flow
- `docs/DEPLOY.md` — два окружения (staging + prod), bootstrap нового VPS, systemd, nginx
- `docs/ROADMAP.md` — фазы Hub-MVP.1..6
- `docs/PUSH.md` — Web Push, VAPID, триггеры, in-app Inbox
- `docs/TECH_DEBT.md` — открытые вопросы и упрощения

## Разработка

```bash
# Backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]" --extra-index-url https://auth.signaris.ru/pypi/simple/
alembic upgrade head
uvicorn app.main:app --reload --port 5060

# Frontend
cd web && npm install && npm run dev
```

Pre-commit чеклист: `pytest && ruff check && cd web && npm run typecheck && npm run build`.

## Деплой

```bash
./deploy/deploy.sh staging              # backend + frontend на staging
./deploy/deploy.sh prod                 # backend + frontend на prod
./deploy/deploy.sh staging backend      # только backend
./deploy/deploy.sh prod frontend        # только frontend
```

См. `docs/DEPLOY.md`.
