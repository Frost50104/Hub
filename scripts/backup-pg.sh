#!/usr/bin/env bash
# pg_dump → gzip → /opt/signaris-hub/backups/db-<name>-<date>.sql.gz
#
# Run under user `postgres` (peer auth, no password needed) — systemd unit
# sets that via `User=postgres`. Argument: database name.
#
# Layout:
#   /opt/signaris-hub/backups/
#     ├── daily/   ← retention 14 (signaris-hub-backup-cleanup.timer)
#     └── weekly/  ← retention 6  (Sunday copy, see weekly-rotate)
#
# Sunday's daily backup is also hardlinked into weekly/.
set -euo pipefail

DB="${1:?usage: $0 <database-name>}"
BACKUP_ROOT="/opt/signaris-hub/backups"
DAILY_DIR="$BACKUP_ROOT/daily"
WEEKLY_DIR="$BACKUP_ROOT/weekly"

mkdir -p "$DAILY_DIR" "$WEEKLY_DIR"

STAMP="$(date +%F)"          # 2026-05-29
DAILY_FILE="$DAILY_DIR/db-$DB-$STAMP.sql.gz"

# pg_dump custom format is best for restore (parallel restore + selective
# tables), but for the offsite story plain SQL is easier to inspect. We use
# custom (`-Fc`) — restore via `pg_restore`, not `psql`.
pg_dump -Fc "$DB" | gzip -9 > "$DAILY_FILE.tmp"
mv -f "$DAILY_FILE.tmp" "$DAILY_FILE"

# Sunday → also a weekly snapshot (hardlink, no extra disk).
if [[ "$(date +%u)" == "7" ]]; then
  ln -f "$DAILY_FILE" "$WEEKLY_DIR/db-$DB-$STAMP.sql.gz"
fi

# Optional offsite — if BACKUP_S3_BUCKET set and aws CLI present, copy.
# Не блокируем daily-job если aws не отвечает.
if [[ -n "${BACKUP_S3_BUCKET:-}" ]] && command -v aws >/dev/null 2>&1; then
  aws s3 cp "$DAILY_FILE" "s3://$BACKUP_S3_BUCKET/$DB/" --quiet || \
    echo "(offsite s3 copy failed — backup is still on disk)" >&2
fi

# Show size for logs.
SIZE=$(du -h "$DAILY_FILE" | cut -f1)
echo "backup ok: $DAILY_FILE ($SIZE)"
