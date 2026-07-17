#!/usr/bin/env bash
# Retention sweep:
#   daily/  — keep last 14 days
#   weekly/ — keep last 6 weeks (~42 days)
set -euo pipefail

BACKUP_ROOT="/opt/signaris-hub/backups"

if [[ -d "$BACKUP_ROOT/daily" ]]; then
  find "$BACKUP_ROOT/daily" -maxdepth 1 -name 'db-*.sql.gz' -type f -mtime +14 -delete
fi
if [[ -d "$BACKUP_ROOT/weekly" ]]; then
  find "$BACKUP_ROOT/weekly" -maxdepth 1 -name 'db-*.sql.gz' -type f -mtime +42 -delete
fi

# Файловые снапшоты (backup-files.sh) — 14 дней. Hardlink-дедупликация:
# удаление старого снапшота освобождает только уникальные для него файлы.
if [[ -d "$BACKUP_ROOT/files" ]]; then
  find "$BACKUP_ROOT/files" -mindepth 2 -maxdepth 2 -type d -name '20*' -mtime +14 \
    -exec rm -rf {} + 2>/dev/null || true
fi

echo "cleanup ok"
