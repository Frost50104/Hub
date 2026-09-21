#!/usr/bin/env bash
set -euo pipefail

# ─── Usage ──────────────────────────────────────────────────────────────────
# ./deploy/deploy.sh staging              # backend + frontend
# ./deploy/deploy.sh prod                 # backend + frontend
# ./deploy/deploy.sh staging backend      # backend only
# ./deploy/deploy.sh prod frontend        # frontend only
# ────────────────────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

if [[ ! -f "$SCRIPT_DIR/.env" ]]; then
  echo "ERROR: deploy/.env not found. Copy deploy/.env.example → deploy/.env and fill in credentials."
  exit 1
fi
source "$SCRIPT_DIR/.env"

ENV="${1:-}"
COMPONENT="${2:-all}"

if [[ "$ENV" != "staging" && "$ENV" != "prod" ]]; then
  echo "Usage: $0 <staging|prod> [backend|frontend]"
  exit 1
fi

if [[ "$ENV" == "staging" ]]; then
  REMOTE_BASE="/opt/signaris-hub-staging"
  SERVICE="signaris-hub-staging"
  BUILD_CMD="npm run build:staging"
  CHECK_URL="https://hub-staging.signaris.ru/api/env"
  DB_NAME="signaris_hub_staging_db"
else
  REMOTE_BASE="/opt/signaris-hub"
  SERVICE="signaris-hub"
  BUILD_CMD="npm run build"
  CHECK_URL="https://hub.signaris.ru/api/env"
  DB_NAME="signaris_hub_db"
fi

# SSH-ключ (deploy/.env: SSH_KEY=~/.ssh/signaris_hub_deploy) — основной путь.
# Fallback на sshpass остаётся для машин без установленного ключа.
SSH_KEY="${SSH_KEY:-}"
SSH_KEY_PATH="${SSH_KEY/#\~/$HOME}"
# Пути с пробелом в списке исключений пишутся как --exclude="'Имя с пробелом'":
# CLAUDE.md и SESSIONS.md исключены нарочно: они локально вне git и содержат
# реальные пароли, а на сервере лежали 644 — читаемые любым пользователем хоста.
# rsync зовётся через `eval`, и одинарные кавычки обязаны пережить первый
# разбор строки, иначе имя распадается на два аргумента (25.08).
# ─── Выбор маршрута ─────────────────────────────────────────────────────────
# Основной путь — прямой на публичный адрес. Из части сетей он закрыт
# (31.08 трафик умирал за stormwall.bix.bg при полностью живом сервере), и
# тогда деплой уходит на запасной адрес из SERVER_HOST_FALLBACK — тайнет-ноду
# `hub-vps`. Обход НЕ включается сам по себе: он стоит лишнего хопа и требует
# включённого Tailscale, поэтому применяется, только когда прямой не отвечает.
#
# Проба — сам ssh с `PreferredAuthentications=none`: живой сервер мгновенно
# отвечает «Permission denied», недоступный молчит до таймаута. Ни nc, ни
# timeout не годятся — на macOS первого нет в нужном виде, второго нет вовсе.
# `|| true` обязателен: в шапке стоит `set -o pipefail`, а ssh при отказе в
# доступе выходит с 255 — без него конвейер считался провальным ДАЖЕ когда
# сервер ответил, и проба всегда говорила «недоступен».
host_reachable() {
  { ssh -o ConnectTimeout=6 -o BatchMode=yes -o StrictHostKeyChecking=accept-new \
        -o PreferredAuthentications=none -o PubkeyAuthentication=no \
        "${SERVER_USER}@$1" true 2>&1 || true; } |
    grep -qiE 'permission denied|authentication'
}

if [[ -n "${SERVER_HOST_FALLBACK:-}" ]] && ! host_reachable "$SERVER_HOST"; then
  # Запасной адрес тоже проверяем: молча переехать на мёртвый — значит
  # обменять понятную ошибку «прямой путь закрыт» на невнятный таймаут rsync.
  if host_reachable "$SERVER_HOST_FALLBACK"; then
    echo "==> $SERVER_HOST не отвечает — уходим на запасной $SERVER_HOST_FALLBACK"
    SERVER_HOST="$SERVER_HOST_FALLBACK"
  else
    echo "==> ни $SERVER_HOST, ни запасной $SERVER_HOST_FALLBACK не отвечают."
    echo "    Включён ли Tailscale? Продолжаю прямым путём."
  fi
fi

# SSH_JUMP (deploy/.env, необязательный) — промежуточный узел для ssh и rsync.
# Третий эшелон: нужен, только если недоступны ОБА адреса. 25.08 маршрут до
# Timeweb оборвался на транзитном IX при живом сервере; до 31.08 это был
# единственный обход, и деплой висел на сервере чужого продукта.
# Пустой по умолчанию — поведение обычного деплоя не меняется.
SSH_JUMP_OPT=""
if [[ -n "${SSH_JUMP:-}" ]]; then
  SSH_JUMP_OPT="-J $SSH_JUMP"
  echo "==> SSH через промежуточный узел: $SSH_JUMP"
fi
if [[ -n "${SSH_KEY:-}" && -f "$SSH_KEY_PATH" ]]; then
  SSH_OPTS="-o StrictHostKeyChecking=accept-new $SSH_JUMP_OPT -i $SSH_KEY_PATH"
  SSH_CMD="ssh $SSH_OPTS ${SERVER_USER}@${SERVER_HOST}"
  RSYNC_CMD="rsync -az -e \"ssh $SSH_OPTS\""
else
  echo "WARN: SSH_KEY не настроен — используем sshpass (см. deploy/.env.example)."
  SSH_OPTS="-o StrictHostKeyChecking=accept-new $SSH_JUMP_OPT -o PubkeyAuthentication=no"
  SSH_CMD="sshpass -e ssh $SSH_OPTS ${SERVER_USER}@${SERVER_HOST}"
  RSYNC_CMD="sshpass -e rsync -az -e \"ssh $SSH_OPTS\""
  export SSHPASS="$SERVER_PASS"
fi

# ─── Version ────────────────────────────────────────────────────────────────
write_version() {
  cd "$PROJECT_DIR"
  local hash dirty=""
  hash=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
  if ! git diff --quiet 2>/dev/null || ! git diff --cached --quiet 2>/dev/null; then
    dirty="-dirty"
  fi
  local ts version
  ts=$(date +%Y%m%d-%H%M%S)
  version="${hash}${dirty}-${ts}"
  echo "$version" > "$PROJECT_DIR/VERSION"
  mkdir -p "$PROJECT_DIR/web/public"
  echo "{\"version\":\"${version}\"}" > "$PROJECT_DIR/web/public/version.json"
  echo "Version: $version"
}

# ─── Deploy backend ────────────────────────────────────────────────────────
deploy_backend() {
  echo "==> Deploying backend to $ENV..."

  # NEVER use --delete (it would wipe .env, .venv, vapid_private.pem, attachments)
  eval $RSYNC_CMD \
    --exclude='.env' \
    --exclude='.venv' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.ruff_cache' \
    --exclude='.pytest_cache' \
    --exclude='.git' \
    --exclude='.idea' \
    --exclude='node_modules' \
    --exclude='web' \
    --exclude='docs' \
    --exclude='deploy' \
    --exclude='attachments' \
    --exclude='uploads' \
    --exclude='LMS' \
    --exclude='import_bundle' \
    --exclude='weeek-bundle' \
    --exclude='.weeek-cache' \
    --exclude='redesign' \
    --exclude='CLAUDE.md' \
    --exclude='SESSIONS.md' \
    --exclude="'Hub Instructions'" \
    "$PROJECT_DIR/" \
    "${SERVER_USER}@${SERVER_HOST}:${REMOTE_BASE}/"

  # Быстрый дамп перед миграциями: суточный таймер не спасает от
  # «мигрировали в обед». Держим последние 5 снапшотов на env.
  echo "==> Pre-migration DB snapshot ($DB_NAME)..."
  $SSH_CMD "mkdir -p /opt/signaris-hub/backups/pre-migrate && \
    sudo -u postgres pg_dump -Fc $DB_NAME \
      -f /tmp/pre-migrate-$DB_NAME.dump && \
    mv /tmp/pre-migrate-$DB_NAME.dump \
      /opt/signaris-hub/backups/pre-migrate/db-$DB_NAME-\$(date +%Y%m%d-%H%M%S).dump && \
    ls -t /opt/signaris-hub/backups/pre-migrate/db-$DB_NAME-*.dump 2>/dev/null | \
      tail -n +6 | xargs -r rm -f"

  echo "==> Installing deps + running migrations..."
  $SSH_CMD "cd ${REMOTE_BASE} && \
    ./.venv/bin/pip install -e '.[sentry,stt]' \
      --extra-index-url https://auth.signaris.ru/pypi/simple/ \
      --quiet --upgrade && \
    ./.venv/bin/alembic upgrade head"

  echo "==> Restarting $SERVICE..."
  $SSH_CMD "systemctl restart $SERVICE && sleep 5 && systemctl is-active $SERVICE"

  # Extraction-воркер — отдельный процесс с тем же кодом: без рестарта
  # остаётся на старой версии (Ф6+; if — на случай env без сервиса).
  echo "==> Restarting ${SERVICE}-extraction (if enabled)..."
  $SSH_CMD "if systemctl list-unit-files ${SERVICE}-extraction.service --no-legend | grep -q .; then \
    systemctl restart ${SERVICE}-extraction && sleep 2 && systemctl is-active ${SERVICE}-extraction; fi"
  echo "==> Backend deployed."
}

# Сколько дней держим хэшированные чанки прошлых сборок. Окно жизни вкладки в
# PWA — недели (`registerType: 'prompt'`), поэтому месяц с запасом. Цена
# измерена: весь dist — 4,5 МБ, на диске 25 ГБ свободно и стоит алерт на 8 ГБ.
DIST_KEEP_DAYS=${DIST_KEEP_DAYS:-30}

# ─── Deploy frontend ───────────────────────────────────────────────────────
# Сборка фронта на VPS требует ~1 ГБ, а машина всего 1,9 ГБ и на ней живёт
deploy_frontend() {
  echo "==> Building frontend locally for $ENV ($BUILD_CMD)..."
  # Сборка — ЛОКАЛЬНО. На VPS (2 ГБ, без swap) `vite build` растёт до ~1 ГБ RSS
  # и с ростом бандла стал падать по OOM даже при остановленном STT
  # (2026-08-21: «Killed» на шаге gzip при ~970 МБ). Сервер получает готовый
  # dist; node на нём больше не нужен. version.json уже лежит в web/public.
  (
    cd "$PROJECT_DIR/web" && \
    npm install --no-audit --no-fund && \
    $BUILD_CMD && \
    test -f dist/index.html && \
    test -f dist/sw.js
  ) || {
    echo "ERROR: локальная сборка фронта не удалась — на сервере остался ПРЕЖНИЙ dist." >&2
    exit 1
  }

  # HTML в прекеше воркера = сломанный баннер обновления (ОС 21.09): воркер
  # отвечает на навигацию к `/` своей копией index.html, и «Обновить» под ним
  # перезагружает ту же старую оболочку по кругу. Проверяем ИТОГОВЫЙ sw.js, а
  # не конфиг: так ловится и чужая правка globPatterns, и смена плагина.
  # Ищем ключ манифеста (`"url":"index.html"` или `url:"index.html"`), а не
  # голую строку — `directoryIndex:"index.html"` сидит в рантайме Workbox всегда.
  if grep -Eq '"?url"?:"index\.html"' "$PROJECT_DIR/web/dist/sw.js"; then
    echo "ERROR: index.html попал в прекеш воркера (web/dist/sw.js) — баннер обновления перестанет уходить. См. globPatterns в web/vite.config.ts." >&2
    exit 1
  fi

  echo "==> Uploading dist to $ENV..."
  # БЕЗ --delete, и это не оплошность (ОС 16.09: «работа не сохраняется, даже
  # если не нажимали кнопку обновить»).
  #
  # `--delete` сносил старые хэшированные чанки в момент выката. Открытая
  # вкладка продолжает их просить, получает 404, Vite шлёт `vite:preloadError`,
  # и `lib/preloadRecovery.ts` перезагружает страницу — вместе с несохранённой
  # работой. Бьёт это прицельно по редакторам: в `vite.config.ts` тяжёлые
  # чанки (RichEditor, CourseBuilderPage, LearnEmployeesPage, LearnOrgPage,
  # LearnAssessmentsPage) НАМЕРЕННО исключены из precache, то есть грузятся из
  # сети ровно в момент открытия экрана.
  #
  # Файлы с постоянными именами (index.html, sw.js, version.json,
  # manifest.webmanifest) перезаписываются и без --delete. Следствие, о
  # котором надо помнить: файл, ИСЧЕЗНУВШИЙ из сборки, остаётся лежать —
  # переименуем когда-нибудь sw.js, старый придётся снять руками.
  $SSH_CMD "mkdir -p ${REMOTE_BASE}/web/dist"
  eval $RSYNC_CMD \
    "$PROJECT_DIR/web/dist/" \
    "${SERVER_USER}@${SERVER_HOST}:${REMOTE_BASE}/web/dist/"

  # Чистка по ВОЗРАСТУ, а не по «нет в текущей сборке»: второе — ровно то
  # поведение, от которого мы ушли. Безопасно потому, что `vite build`
  # переписывает весь dist каждой сборкой (замер: все файлы пишутся за
  # полторы секунды), а rsync с -a переносит свежий mtime на сервер — под
  # удаление попадает только то, чего не было в сборках месяц.
  $SSH_CMD "find ${REMOTE_BASE}/web/dist/assets -type f -mtime +${DIST_KEEP_DAYS} -delete 2>/dev/null || true"
  echo "==> Frontend deployed (старые чанки живут ${DIST_KEEP_DAYS} дней)."
}

# ─── Main ───────────────────────────────────────────────────────────────────
echo "=== Deploying Signaris Hub to $ENV ($COMPONENT) ==="
write_version

if [[ "$COMPONENT" == "all" || "$COMPONENT" == "backend" ]]; then
  deploy_backend
fi
if [[ "$COMPONENT" == "all" || "$COMPONENT" == "frontend" ]]; then
  deploy_frontend
fi

echo ""
echo "=== Done! Verify at: $CHECK_URL ==="
if command -v curl &>/dev/null; then
  echo "Version on server:"
  # Сначала обычным путём. Если он закрыт блокировкой — повторяем через
  # --resolve на тот адрес, по которому только что прошёл деплой: имя, SNI и
  # сертификат остаются настоящими (никакого --insecure), меняется только куда
  # открыть сокет. Молча краснеющая проверка хуже отсутствующей — к ней
  # привыкают и перестают читать.
  CHECK_DOMAIN="${CHECK_URL#https://}"
  CHECK_DOMAIN="${CHECK_DOMAIN%%/*}"
  if ! curl -sS --max-time 15 "$CHECK_URL" 2>/dev/null; then
    echo "(прямой путь до $CHECK_DOMAIN закрыт — повторяю через $SERVER_HOST)"
    curl -sS --max-time 15 --resolve "$CHECK_DOMAIN:443:$SERVER_HOST" "$CHECK_URL" 2>/dev/null ||
      echo "(не достучались ни прямым путём, ни через $SERVER_HOST)"
    echo ""
    echo "ВНИМАНИЕ: проверка прошла в обход блокировки и публичный маршрут НЕ"
    echo "проверяет. Она отвечает «сервер и приложение живы», а не «сайт"
    echo "доступен снаружи»."
  fi
fi
