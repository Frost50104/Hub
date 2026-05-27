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
else
  REMOTE_BASE="/opt/signaris-hub"
  SERVICE="signaris-hub"
  BUILD_CMD="npm run build"
  CHECK_URL="https://hub.signaris.ru/api/env"
fi

SSH_OPTS="-o StrictHostKeyChecking=no -o PubkeyAuthentication=no"
SSH_CMD="sshpass -e ssh $SSH_OPTS ${SERVER_USER}@${SERVER_HOST}"
RSYNC_CMD="sshpass -e rsync -az -e \"ssh $SSH_OPTS\""
export SSHPASS="$SERVER_PASS"

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
    "$PROJECT_DIR/" \
    "${SERVER_USER}@${SERVER_HOST}:${REMOTE_BASE}/"

  echo "==> Installing deps + running migrations..."
  $SSH_CMD "cd ${REMOTE_BASE} && \
    ./.venv/bin/pip install -e . \
      --extra-index-url https://auth.signaris.ru/pypi/simple/ \
      --quiet --upgrade && \
    ./.venv/bin/alembic upgrade head"

  echo "==> Restarting $SERVICE..."
  $SSH_CMD "systemctl restart $SERVICE && sleep 5 && systemctl is-active $SERVICE"
  echo "==> Backend deployed."
}

# ─── Deploy frontend ───────────────────────────────────────────────────────
deploy_frontend() {
  echo "==> Deploying frontend to $ENV..."

  eval $RSYNC_CMD \
    --exclude='node_modules' \
    --exclude='dist' \
    --exclude='.vite' \
    "$PROJECT_DIR/web/" \
    "${SERVER_USER}@${SERVER_HOST}:${REMOTE_BASE}/web_src/"

  $SSH_CMD "cd ${REMOTE_BASE}/web_src && \
    npm install --no-audit --no-fund && \
    $BUILD_CMD && \
    mkdir -p ${REMOTE_BASE}/web/dist && \
    rm -rf ${REMOTE_BASE}/web/dist/* && \
    cp -r dist/* ${REMOTE_BASE}/web/dist/"

  echo "==> Frontend deployed."
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
  curl -sS "$CHECK_URL" 2>/dev/null || echo "(could not reach $CHECK_URL)"
fi
