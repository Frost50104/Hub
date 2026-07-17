#!/usr/bin/env bash
# Инкрементальный снапшот файлового хранилища (task-вложения + learn-материалы
# библиотеки) — Ф1: LMS-контент не может существовать в одном экземпляре.
#
# rsync --link-dest: неизменённые файлы становятся hardlink'ами на прошлый
# снапшот — каждый день выглядит как полная копия, диск растёт только на
# дельту. Retention 14 дней — backup-cleanup.sh.
#
# Layout:
#   /opt/signaris-hub/backups/files/<env>/<YYYY-MM-DD>/  ← снапшоты
#   /opt/signaris-hub/backups/files/<env>/latest         ← симлинк
#
# Запуск root'ом (systemd: signaris-hub-backup-files.timer, 00:15 UTC) —
# attachments принадлежат signaris, postgres их не прочитал бы.
set -euo pipefail

BACKUP_ROOT="/opt/signaris-hub/backups/files"
STAMP="$(date +%F)"

for SRC in /opt/signaris-hub/attachments /opt/signaris-hub-staging/attachments; do
  [[ -d "$SRC" ]] || continue
  ENV_NAME="$(basename "$(dirname "$SRC")")"   # signaris-hub | signaris-hub-staging
  DEST="$BACKUP_ROOT/$ENV_NAME/$STAMP"
  LATEST="$BACKUP_ROOT/$ENV_NAME/latest"
  mkdir -p "$DEST"
  if [[ -d "$LATEST" ]]; then
    rsync -a --delete --link-dest="$(readlink -f "$LATEST")" "$SRC/" "$DEST/"
  else
    rsync -a "$SRC/" "$DEST/"
  fi
  ln -sfn "$DEST" "$LATEST"
  echo "files backup ok: $DEST ($(du -sh "$DEST" | cut -f1))"
done

# Optional offsite — как у pg-бэкапа, не блокируем job при недоступном S3.
if [[ -n "${BACKUP_S3_BUCKET:-}" ]] && command -v aws >/dev/null 2>&1; then
  aws s3 sync "$BACKUP_ROOT" "s3://$BACKUP_S3_BUCKET/files/" --quiet || \
    echo "(offsite files sync failed — snapshots are still on disk)" >&2
fi
