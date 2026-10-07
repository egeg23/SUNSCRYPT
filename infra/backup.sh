#!/usr/bin/env bash
#
# Резервная копия базы SUNSCRYPT: pg_dump из контейнера postgres проекта
# «sunscrypt» в /opt/sunscrypt/backups (только root), 14 последних дней.
# Запускается cron'ом (/etc/cron.d/sunscrypt, ставит infra/deploy.sh) и
# перед каждой выкаткой (миграции базы).
#
# Ключи Bybit в базе зашифрованы MASTER_KEY из /opt/sunscrypt/.env: копия
# без .env бесполезна, копия с .env — секрет. Обе лежат только у root.

set -euo pipefail
APP_DIR="${APP_DIR:-/opt/sunscrypt}"
DIR="$APP_DIR/backups"
KEEP_DAYS="${KEEP_DAYS:-14}"
cd "$APP_DIR"

C=(docker compose -p sunscrypt --env-file "$APP_DIR/.env" -f infra/docker-compose.yml)
umask 077
mkdir -p "$DIR"
chmod 700 "$DIR"

f="$DIR/sunscrypt-$(date -u +%Y%m%d-%H%M).dump"
"${C[@]}" exec -T postgres pg_dump -U sunscrypt -d sunscrypt -Fc > "$f.part"
# Копия читается — значит, из неё можно восстановиться.
n="$("${C[@]}" exec -T postgres pg_restore --list < "$f.part" | grep -c 'TABLE DATA' || true)"
[ "$n" -gt 0 ] || { rm -f "$f.part"; echo "✗ копия базы не читается" >&2; exit 1; }
mv "$f.part" "$f"
cp "$APP_DIR/.env" "$DIR/env.latest"

find "$DIR" -name 'sunscrypt-*.dump' -mtime +"$KEEP_DAYS" -delete
echo "▸ Копия базы: $(basename "$f"), $(du -h "$f" | cut -f1), таблиц с данными $n; копий всего $(find "$DIR" -name 'sunscrypt-*.dump' | wc -l)"

# Восстановление (вручную, с остановленным движком):
#   docker compose -p sunscrypt ... stop orchestrator signals backend
#   docker compose -p sunscrypt ... exec -T postgres \
#     pg_restore -U sunscrypt -d sunscrypt --clean --if-exists < backups/<файл>.dump
#   docker compose -p sunscrypt ... up -d
