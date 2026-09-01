#!/usr/bin/env bash
# Зашифрованный архив того, чего НЕТ в git и что существует ТОЛЬКО на сервере.
#
# Дампы БД и вложения бэкапятся давно, а вот способность их ЗАПУСТИТЬ — нет:
# 31.08 обнаружилось, что `vapid_private.pem`, оба `.env` и креды healthcheck
# не попадают ни в один бэкап. VAPID здесь опаснее прочего: `Vapid.from_file`
# при отсутствии файла МОЛЧА генерирует новую пару, и восстановленный сервер
# начинает подписывать чужим ключом — пуши перестают доходить без ошибок.
# Ровно это уже стоило месяца тишины 29.07–26.08.
#
# nginx-конфиги, systemd-юниты и скрипты сюда НЕ кладём: они в git (`ops/`,
# `scripts/`) и разворачиваются `bootstrap-vps.sh`. Копия завела бы второй
# источник истины, который однажды разойдётся с репозиторием.
#
# Шифруем не от компрометации сервера (там оригиналы лежат рядом открытым
# текстом), а ради НОВОЙ экспозиции — копии в S3-бакете: `.env` содержит пароли
# БД, service-key, ключи DeepSeek и iiko.
#
# ВАЖНО: пароль обязан быть продублирован в CLAUDE.md → СЕКРЕТЫ. Он лежит на
# том же сервере, который мы и теряем в сценарии, ради которого всё это; без
# копии вне сервера архив нечем открыть ровно тогда, когда он нужен.
set -euo pipefail

BACKUP_ROOT="/opt/signaris-hub/backups"
OUT_DIR="$BACKUP_ROOT/secrets"
PASS_FILE="/etc/default/signaris-hub-backup"
STAMP="$(date +%F)"
OUT="$OUT_DIR/secrets-$STAMP.tar.gz.gpg"

if [[ ! -f "$PASS_FILE" ]]; then
  echo "нет $PASS_FILE — некуда взять BACKUP_SECRETS_PASSPHRASE" >&2
  exit 1
fi
# shellcheck disable=SC1090
set -a; . "$PASS_FILE"; set +a
: "${BACKUP_SECRETS_PASSPHRASE:?BACKUP_SECRETS_PASSPHRASE не задан в $PASS_FILE}"

CANDIDATES=(
  /opt/signaris-hub/.env
  /opt/signaris-hub-staging/.env
  /opt/signaris-hub/vapid_private.pem
)
# /etc/default/signaris-hub-* — healthcheck (токен Telegram) и backup (пароль от
# этого самого архива плюс креды S3). Пароль внутри архива, которым он же
# зашифрован, — не дыра: без копии из CLAUDE.md открыть всё равно нечем.
while IFS= read -r f; do CANDIDATES+=("$f"); done \
  < <(find /etc/default -maxdepth 1 -name 'signaris-hub-*' -type f | sort)

# Отсутствующий путь — предупреждение, а не падение: состав файлов на staging и
# на будущих хостах может отличаться, и потерять ВЕСЬ архив из-за одного
# ненайденного файла хуже, чем собрать его без него.
ITEMS=()
for f in "${CANDIDATES[@]}"; do
  if [[ -f "$f" ]]; then
    ITEMS+=("${f#/}")          # tar -C / хочет относительные пути
  else
    echo "предупреждение: нет $f — пропускаю" >&2
  fi
done
if [[ ${#ITEMS[@]} -eq 0 ]]; then
  echo "нечего архивировать — ни одного файла из списка не найдено" >&2
  exit 1
fi

mkdir -p "$OUT_DIR"
chmod 700 "$OUT_DIR"

# Пароль идёт через fd 3, а не через файл и не аргументом: аргумент виден в
# `ps`, временный файл переживает падение скрипта.
tar -czf - -C / "${ITEMS[@]}" |
  gpg --batch --yes --symmetric --cipher-algo AES256 --passphrase-fd 3 \
      -o "$OUT.tmp" 3<<<"$BACKUP_SECRETS_PASSPHRASE"
mv -f "$OUT.tmp" "$OUT"
chown root:root "$OUT"
chmod 600 "$OUT"

# Offsite — тем же правилом, что дампы: только пополняем. Архив крошечный
# (единицы килобайт), поэтому в бакете он копится без ротации: это и есть
# история ключей, а вернуть VAPID суточной давности иногда нужнее свежего.
if [[ -n "${BACKUP_S3_REMOTE:-}" ]] && command -v rclone >/dev/null 2>&1; then
  rclone copy "$OUT" "$BACKUP_S3_REMOTE/secrets/" --quiet || \
    echo "(offsite secrets copy failed — архив остался на диске)" >&2
fi

echo "secrets backup ok: $OUT ($(du -h "$OUT" | cut -f1), файлов: ${#ITEMS[@]})"
