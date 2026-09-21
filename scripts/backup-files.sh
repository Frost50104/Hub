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

# ТОЛЬКО прод (15.09). Staging бэкапился здесь же с самого начала, и это стоило
# 3,8 ГБ из 5,3 ГБ всего дерева снапшотов — при том что offsite его никогда не
# возил и восстанавливать тестовый стенд из бэкапа никто не собирался. Замер
# 15.09: вложения прода 1,5 ГБ, вложения staging 3,7 ГБ, их снапшоты 3,8 ГБ.
# Место понадобилось под видео во вложениях (до 1 ГБ на файл), и первым делом
# освобождается то, что и так не нужно.
#
# Уже накопленные снапшоты staging эта правка НЕ удаляет — они снимаются
# разово, руками, при выкате (см. docs/DEPLOY.md).
for SRC in /opt/signaris-hub/attachments; do
  [[ -d "$SRC" ]] || continue
  ENV_NAME="$(basename "$(dirname "$SRC")")"   # signaris-hub
  DEST="$BACKUP_ROOT/$ENV_NAME/$STAMP"
  LATEST="$BACKUP_ROOT/$ENV_NAME/latest"
  mkdir -p "$DEST"
  # -H (21.09): шаблоны проектов (0060) копируют вложения ЖЁСТКОЙ ССЫЛКОЙ —
  # два пути на один inode. Без -H снимок получал бы на каждую копию отдельный
  # файл, и проект по шаблону с видео на гигабайт стоил бы гигабайт в каждом
  # новом снимке. `--link-dest` с -H совместим.
  if [[ -d "$LATEST" ]]; then
    rsync -aH --delete --link-dest="$(readlink -f "$LATEST")" "$SRC/" "$DEST/"
  else
    rsync -aH "$SRC/" "$DEST/"
  fi
  ln -sfn "$DEST" "$LATEST"
  echo "files backup ok: $DEST ($(du -sh "$DEST" | cut -f1))"
done

# Offsite (01.09) — только ПОСЛЕДНИЙ снапшот ПРОДА.
#
# Раньше здесь стояло `aws s3 sync "$BACKUP_ROOT"` по всему дереву снапшотов, и
# включать это было нельзя: hardlink'и в S3 не переживают, поэтому 14 копий по
# 1,5 ГБ уехали бы как ~21 ГБ вместо 1,5. Дедупликация живёт только на локальной
# ФС; в бакете нужен ровно один актуальный слепок.
#
# `latest` — симлинк, поэтому путь разрешаем сами: rclone по символическим
# ссылкам не ходит.
#
# `copy`, а не `sync`: см. объяснение в backup-pg.sh. Вложения почти не
# удаляются, так что осиротевшие объекты копятся медленно, а риск стереть
# offsite-копию вслед за локальной бедой снят полностью.
if [[ -n "${BACKUP_S3_REMOTE:-}" ]] && command -v rclone >/dev/null 2>&1; then
  PROD_LATEST="$(readlink -f "$BACKUP_ROOT/signaris-hub/latest" || true)"
  if [[ -d "$PROD_LATEST" ]]; then
    rclone copy "$PROD_LATEST" "$BACKUP_S3_REMOTE/attachments/" --quiet || \
      echo "(offsite files copy failed — snapshots are still on disk)" >&2
  else
    echo "(offsite skipped: $BACKUP_ROOT/signaris-hub/latest не разрешается)" >&2
  fi
fi
