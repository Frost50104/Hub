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

# Offsite (01.09): rclone-назначение целиком в BACKUP_S3_REMOTE, например
# `twc:signaris-hub-backups`. Креды — в /root/.config/rclone/rclone.conf (600).
#
# `aws` заменён на `rclone`: awscli в Ubuntu 24.04 отсутствует как пакет, а
# вендорный установщик тянет ~250 МБ ради одной команды.
#
# STAGING НЕ ВЕЗЁМ: он воспроизводим, его дамп — вторая копия тех же
# персональных данных, а снапшот вложений там 3,7 ГБ против 1,5 ГБ у прода и
# стал бы основным объёмом в бакете.
#
# `copy`, а не `sync`: назначение должно только пополняться. Синхронизация
# отражала бы локальную ротацию в бакет, и любая беда с локальным каталогом
# (пустой том, ошибка в ретенции) стёрла бы offsite-копию — ровно то, ради
# чего она existует. Побочный эффект приятный: в бакете история длиннее
# локальных 14 дней, а стоит она 6 МБ в сутки.
#
# Ошибка S3 не роняет ночную джобу: дамп уже лежит на диске.
if [[ -n "${BACKUP_S3_REMOTE:-}" && "$DB" != *staging* ]] && command -v rclone >/dev/null 2>&1; then
  rclone copy "$DAILY_FILE" "$BACKUP_S3_REMOTE/db/" --quiet || \
    echo "(offsite copy failed — backup is still on disk)" >&2
fi

# Show size for logs.
SIZE=$(du -h "$DAILY_FILE" | cut -f1)
echo "backup ok: $DAILY_FILE ($SIZE)"
