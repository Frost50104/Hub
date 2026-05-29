#!/usr/bin/env bash
set -euo pipefail

# One-time VPS provisioning for Signaris Hub.
# Run AS ROOT on 94.241.168.8 (Ubuntu 24.04 LTS). Idempotent.
#
# Prerequisites on local machine:
#   scp -r ops/ scripts/ deploy/bootstrap-vps.sh root@94.241.168.8:/tmp/hub-bootstrap/
#   ssh root@94.241.168.8 'bash /tmp/hub-bootstrap/bootstrap-vps.sh'

if [[ "$(id -u)" != "0" ]]; then
  echo "ERROR: run as root"
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "==> apt update + install packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
  postgresql-16 redis-server nginx \
  certbot python3-certbot-nginx \
  python3.12 python3.12-venv python3-pip \
  nodejs npm \
  sshpass rsync curl ca-certificates gnupg

echo "==> system user 'signaris'"
id signaris &>/dev/null || useradd -m -s /bin/bash signaris

echo "==> /opt directory tree"
for env_dir in /opt/signaris-hub /opt/signaris-hub-staging; do
  mkdir -p "$env_dir"
  mkdir -p "$env_dir/attachments"
  chown -R signaris:signaris "$env_dir"
  chmod 750 "$env_dir"
done

echo "==> backup + healthcheck infra (3.6.8)"
mkdir -p /opt/signaris-hub/backups/daily /opt/signaris-hub/backups/weekly
chown -R postgres:postgres /opt/signaris-hub/backups
chmod 750 /opt/signaris-hub/backups
mkdir -p /opt/signaris-hub/scripts
# scripts/ must be world-readable + executable so the postgres + root timers
# can run them out of the same place no matter who owns them.
install -m 755 -o root -g root "$REPO_ROOT/scripts/backup-pg.sh"      /opt/signaris-hub/scripts/backup-pg.sh
install -m 755 -o root -g root "$REPO_ROOT/scripts/backup-cleanup.sh" /opt/signaris-hub/scripts/backup-cleanup.sh
install -m 755 -o root -g root "$REPO_ROOT/scripts/healthcheck.sh"    /opt/signaris-hub/scripts/healthcheck.sh
mkdir -p /var/lib/signaris-hub
chmod 755 /var/lib/signaris-hub

echo "==> Python venvs (prod + staging)"
for env_dir in /opt/signaris-hub /opt/signaris-hub-staging; do
  if [[ ! -d "$env_dir/.venv" ]]; then
    sudo -u signaris python3.12 -m venv "$env_dir/.venv"
  fi
done

echo "==> Postgres roles + databases"
# App roles (non-superuser — RLS enforced)
for role in signaris_hub signaris_hub_staging; do
  sudo -u postgres psql -tc "SELECT 1 FROM pg_roles WHERE rolname='$role'" | grep -q 1 || \
    sudo -u postgres createuser "$role"
done
# Migration roles (SUPERUSER bypasses RLS)
for role in signaris_hub_migrate signaris_hub_staging_migrate; do
  sudo -u postgres psql -tc "SELECT 1 FROM pg_roles WHERE rolname='$role'" | grep -q 1 || \
    sudo -u postgres createuser --superuser "$role"
done
# Databases (owned by migrate role)
sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname='signaris_hub_db'" | grep -q 1 || \
  sudo -u postgres createdb -O signaris_hub_migrate signaris_hub_db
sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname='signaris_hub_staging_db'" | grep -q 1 || \
  sudo -u postgres createdb -O signaris_hub_staging_migrate signaris_hub_staging_db
# App-role grants. ALTER DEFAULT PRIVILEGES requires FOR ROLE <creator> —
# without it the default applies only to objects created by the *current*
# postgres user, NOT the migrate role that actually runs alembic upgrades.
sudo -u postgres psql -d signaris_hub_db -c "
    GRANT USAGE ON SCHEMA public TO signaris_hub;
    GRANT ALL ON ALL TABLES IN SCHEMA public TO signaris_hub;
    GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO signaris_hub;
    ALTER DEFAULT PRIVILEGES FOR ROLE signaris_hub_migrate IN SCHEMA public
        GRANT ALL ON TABLES TO signaris_hub;
    ALTER DEFAULT PRIVILEGES FOR ROLE signaris_hub_migrate IN SCHEMA public
        GRANT USAGE, SELECT ON SEQUENCES TO signaris_hub;
" >/dev/null
sudo -u postgres psql -d signaris_hub_staging_db -c "
    GRANT USAGE ON SCHEMA public TO signaris_hub_staging;
    GRANT ALL ON ALL TABLES IN SCHEMA public TO signaris_hub_staging;
    GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO signaris_hub_staging;
    ALTER DEFAULT PRIVILEGES FOR ROLE signaris_hub_staging_migrate IN SCHEMA public
        GRANT ALL ON TABLES TO signaris_hub_staging;
    ALTER DEFAULT PRIVILEGES FOR ROLE signaris_hub_staging_migrate IN SCHEMA public
        GRANT USAGE, SELECT ON SEQUENCES TO signaris_hub_staging;
" >/dev/null

cat <<'EOF'

WARNING: set Postgres passwords manually (one-time):
  sudo -u postgres psql -c "ALTER ROLE signaris_hub WITH LOGIN PASSWORD '<from-CLAUDE.md>';"
  sudo -u postgres psql -c "ALTER ROLE signaris_hub_migrate WITH LOGIN PASSWORD '<from-CLAUDE.md>';"
  sudo -u postgres psql -c "ALTER ROLE signaris_hub_staging WITH LOGIN PASSWORD '<from-CLAUDE.md>';"
  sudo -u postgres psql -c "ALTER ROLE signaris_hub_staging_migrate WITH LOGIN PASSWORD '<from-CLAUDE.md>';"

Save passwords into local Hub/CLAUDE.md → СЕКРЕТЫ AND into:
  /opt/signaris-hub/.env             → SIGNARIS_HUB_DATABASE_URL, SIGNARIS_HUB_DATABASE_MIGRATION_URL
  /opt/signaris-hub-staging/.env     → same for _staging
EOF

echo "==> Redis: databases >= 6 (auth=3, hub-prod=4, hub-staging=5)"
sed -i 's/^# databases .*/databases 16/' /etc/redis/redis.conf || true
sed -i 's/^databases .*/databases 16/' /etc/redis/redis.conf || true
systemctl restart redis-server

echo "==> VAPID keypair (one-time, single key shared across prod + staging as on Desk)"
if [[ ! -f /opt/signaris-hub/vapid_private.pem ]]; then
  if [[ -f "$REPO_ROOT/scripts/generate_vapid.py" ]]; then
    /opt/signaris-hub/.venv/bin/pip install --quiet cryptography
    /opt/signaris-hub/.venv/bin/python "$REPO_ROOT/scripts/generate_vapid.py" \
      --out /opt/signaris-hub/vapid_private.pem
  else
    echo "scripts/generate_vapid.py missing — run it manually after first deploy."
  fi
fi
if [[ -f /opt/signaris-hub/vapid_private.pem ]]; then
  chmod 640 /opt/signaris-hub/vapid_private.pem
  chown root:signaris /opt/signaris-hub/vapid_private.pem
fi

echo "==> systemd units"
if [[ -d "$REPO_ROOT/ops/systemd" ]]; then
  cp "$REPO_ROOT/ops/systemd/"*.service /etc/systemd/system/
  cp "$REPO_ROOT/ops/systemd/"*.timer /etc/systemd/system/
  systemctl daemon-reload
  systemctl enable signaris-hub signaris-hub-staging
  systemctl enable signaris-hub-due-soon.timer signaris-hub-overdue.timer
  # 3.6.8: backup + healthcheck timers.
  systemctl enable --now signaris-hub-backup.timer signaris-hub-backup-cleanup.timer
  systemctl enable --now signaris-hub-healthcheck.timer
fi

echo "==> nginx site configs"
if [[ -d "$REPO_ROOT/ops/nginx" ]]; then
  cp "$REPO_ROOT/ops/nginx/"*.conf /etc/nginx/sites-available/
  ln -sf /etc/nginx/sites-available/hub.signaris.ru.conf         /etc/nginx/sites-enabled/
  ln -sf /etc/nginx/sites-available/hub-staging.signaris.ru.conf /etc/nginx/sites-enabled/
  rm -f /etc/nginx/sites-enabled/default
  nginx -t && systemctl reload nginx
fi

echo "==> certbot (Let's Encrypt) — requires DNS A-records pointing at this VPS"
certbot --nginx \
  -d hub.signaris.ru -d hub-staging.signaris.ru \
  --non-interactive --agree-tos --email ops@signaris.ru \
  --keep-until-expiring || \
  echo "(certbot failed — confirm DNS is set and rerun: certbot --nginx -d hub.signaris.ru -d hub-staging.signaris.ru)"

cat <<'EOF'

=== Bootstrap complete. Next steps ===
  1. Set Postgres passwords (commands above) and put them in:
       /opt/signaris-hub/.env
       /opt/signaris-hub-staging/.env
  2. Populate both .env files (see ../deploy/.env.example for keys):
       SIGNARIS_HUB_DATABASE_URL=postgresql+asyncpg://signaris_hub:<pw>@127.0.0.1/signaris_hub_db
       SIGNARIS_HUB_DATABASE_MIGRATION_URL=postgresql+asyncpg://signaris_hub_migrate:<pw>@127.0.0.1/signaris_hub_db
       SIGNARIS_HUB_REDIS_URL=redis://127.0.0.1:6379/4    # 5 for staging
       SIGNARIS_HUB_VAPID_PUBLIC_KEY=<from generate_vapid.py output>
       SIGNARIS_HUB_VAPID_PRIVATE_KEY_PATH=/opt/signaris-hub/vapid_private.pem
       SIGNARIS_HUB_ENVIRONMENT=prod   # 'staging' for staging .env
       SIGNARIS_HUB_PORT=5059          # 5060 for staging
       # SIGNARIS_HUB_SIGNARIS_SERVICE_KEY=<filled in Hub-MVP.6>
  3. (Optional, 3.6.8) Offsite backup — create /etc/default/signaris-hub-backup:
       BACKUP_S3_BUCKET=signaris-hub-backups
       AWS_ACCESS_KEY_ID=...
       AWS_SECRET_ACCESS_KEY=...
       AWS_DEFAULT_REGION=eu-central-1
     (Requires `apt install awscli`. Skip the file → backups stay local-only.)
  4. (Optional) Alert email recipient — /etc/default/signaris-hub-healthcheck:
       HEALTHCHECK_ALERT_EMAIL=ops@signaris.ru
     `mail` command must be installed (`apt install mailutils`) for emails.
  5. From your laptop:
       ./deploy/deploy.sh staging
       ./deploy/deploy.sh prod
EOF
