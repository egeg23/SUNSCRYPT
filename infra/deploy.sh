#!/usr/bin/env bash
#
# Выкатка SUNSCRYPT на сервере. Запускается из GitHub Actions по SSH
# (.github/workflows/sunscrypt-deploy.yml) после каждого пуша в main
# репозитория egeg23/SUNSCRYPT; руками — `bash /opt/sunscrypt/infra/deploy.sh` от root.
#
# Сервер общий: на нём же devuz.studio, витрина globalex и другие проекты.
# Поэтому скрипт трогает только своё — проект Docker Compose «sunscrypt»,
# свой порт и свой сайт nginx — и ничего не чистит за пределами этого.
#
# Секреты приложения в git не попадают никогда: репозиторий публичный. Они
# живут в /opt/sunscrypt/.env (только root), создаются здесь один раз и
# дальше не перезаписываются.

set -euo pipefail
unset HTTPS_PROXY HTTP_PROXY ALL_PROXY https_proxy http_proxy all_proxy

APP_DIR="${APP_DIR:-/opt/sunscrypt}"
ENV_FILE="$APP_DIR/.env"
cd "$APP_DIR"

say() { printf '▸ %s\n' "$*"; }
die() { printf '✗ %s\n' "$*" >&2; exit 1; }
env_get() { grep -E "^$1=" "$ENV_FILE" | tail -1 | cut -d= -f2- || true; }

# ── 1. Секреты: один раз, на сервере ────────────────────────────────────────
if [ ! -f "$ENV_FILE" ]; then
  say "Первая выкатка: создаю $ENV_FILE с новыми секретами"
  umask 077
  {
    echo "# SUNSCRYPT — секреты сервера. В git не класть. Создан $(date -u +%F)."
    echo "POSTGRES_PASSWORD=$(openssl rand -hex 24)"
    echo "MASTER_KEY=$(openssl rand -base64 32)"
    echo "SESSION_SECRET=$(openssl rand -hex 32)"
  } > "$ENV_FILE"
fi
chmod 600 "$ENV_FILE"

# ── 1б. Секреты владельца из GitHub ──────────────────────────────────────────
# Владелец заводит их в Settings → Secrets → Actions с префиксом SUNSCRYPT_;
# выкатка передаёт их сюда в окружении и записывает в .env без префикса.
# Пустой — не трогаем (секрет не заведён или уже записан раньше). Значения
# не печатаются.
env_set() {
  local tmp; tmp="$(mktemp "$APP_DIR/.env.XXXXXX")"
  grep -vE "^$1=" "$ENV_FILE" > "$tmp" || true
  printf '%s=%s\n' "$1" "$2" >> "$tmp"
  chmod 600 "$tmp"; mv "$tmp" "$ENV_FILE"
}
# Выкатка кладёт их в .incoming (0600) отдельным коротким шагом: так они не
# висят в списке процессов сервера всю выкатку. Прочитали — удалили.
if [ -f "$APP_DIR/.incoming" ]; then
  # shellcheck disable=SC1091
  . "$APP_DIR/.incoming"
  rm -f "$APP_DIR/.incoming"
fi
for name in TELEGRAM_TOKEN BYBIT_DEMO_API_KEY BYBIT_DEMO_API_SECRET \
            SMTP_HOST SMTP_PORT SMTP_USER SMTP_PASSWORD SMTP_FROM \
            OWNER_EMAIL OWNER_PASSWORD WEIGHTS_IDS; do
  var="SUNSCRYPT_$name"
  if [ -n "${!var:-}" ]; then
    if [ "$(env_get "$name")" != "${!var}" ]; then
      env_set "$name" "${!var}"
      say "Секрет $name записан в .env"
    fi
  fi
done

# ── 2. Порт: свободный, запоминается ────────────────────────────────────────
port_busy() { ss -ltnH "sport = :$1" 2>/dev/null | grep -q .; }
if [ -z "$(env_get WEB_PORT)" ]; then
  for p in $(seq 3470 3499); do
    if ! port_busy "$p"; then echo "WEB_PORT=$p" >> "$ENV_FILE"; break; fi
  done
fi
WEB_PORT="$(env_get WEB_PORT)"
[ -n "$WEB_PORT" ] || die "Нет свободного порта в 3470–3499"

# ── 3. Временный адрес: sunscrypt.<ip>.sslip.io ─────────────────────────────
# Бриф: «сейчас — не на поддомене, временный хост, потом перенос на
# maximov-tech.ru». sslip.io отвечает адресом, зашитым в имя, — домен не
# нужен, а сертификат Let's Encrypt на такое имя выдаётся. Переезд на домен —
# PUBLIC_HOST в .env и повторная выкатка.
if [ -z "$(env_get SERVER_IP)" ]; then
  IP="$(curl -fsS --max-time 10 https://api.ipify.org || hostname -I | awk '{print $1}')"
  [ -n "$IP" ] && echo "SERVER_IP=$IP" >> "$ENV_FILE"
fi
if [ -z "$(env_get PUBLIC_HOST)" ]; then
  IP="$(curl -fsS --max-time 10 https://api.ipify.org || hostname -I | awk '{print $1}')"
  [ -n "$IP" ] || die "Не узнал внешний адрес сервера"
  echo "PUBLIC_HOST=sunscrypt.${IP//./-}.sslip.io" >> "$ENV_FILE"
fi
PUBLIC_HOST="$(env_get PUBLIC_HOST)"

# ── 3б. Веса модели Kronos ──────────────────────────────────────────────────
# Не в git. Скачиваем один раз; не вышло — выкатка идёт дальше: сайту веса
# не нужны, нужны движку.
MODELS_DIR="$APP_DIR/models"
W_NAME="$(sed -n 's/^name=//p' infra/model-weights.txt)"
W_SHA="$(sed -n 's/^sha256=//p' infra/model-weights.txt)"
W_IDS="$(env_get WEIGHTS_IDS)"
if [ -f "$MODELS_DIR/$W_NAME/.sha256" ] && [ "$(cat "$MODELS_DIR/$W_NAME/.sha256")" = "$W_SHA" ]; then
  say "Веса $W_NAME на месте"
elif [ -z "$W_IDS" ]; then
  echo "⚠ веса $W_NAME не скачаны: нет секрета SUNSCRYPT_WEIGHTS_IDS" >&2
else
  say "Скачиваю веса $W_NAME"
  tmp="$(mktemp -d)"; n=0; ok=1
  for id in ${W_IDS//,/ }; do
    curl -fsSL --max-time 600 -o "$tmp/part.$n" \
      "https://drive.usercontent.google.com/download?id=$id&export=download&confirm=t" || { ok=""; break; }
    n=$((n + 1))
  done
  parts() { for i in $(seq 0 $((n - 1))); do cat "$tmp/part.$i"; done; }
  if [ -n "$ok" ] && [ "$(parts | sha256sum | cut -d' ' -f1)" = "$W_SHA" ]; then
    mkdir -p "$MODELS_DIR"
    rm -rf "${MODELS_DIR:?}/$W_NAME"
    parts | tar xz -C "$MODELS_DIR"
    echo "$W_SHA" > "$MODELS_DIR/$W_NAME/.sha256"
    say "Веса $W_NAME: sha256 сошёлся, распакованы ($(du -sh "$MODELS_DIR/$W_NAME" | cut -f1))"
  else
    echo "⚠ веса $W_NAME не скачались или sha256 не сошёлся" >&2
  fi
  rm -rf "$tmp"
fi

# Веса читает движок от непривилегированного пользователя (в архиве файл —
# только для root). Кэш HuggingFace (токенизатор Kronos) он же пишет.
[ -d "$MODELS_DIR/$W_NAME" ] && chmod -R a+rX "$MODELS_DIR/$W_NAME"
mkdir -p "$MODELS_DIR/hf" "$MODELS_DIR/registry" && chown 10001 "$MODELS_DIR/hf" "$MODELS_DIR/registry"
export MODELS_DIR

# ── 4. Сборка и запуск ──────────────────────────────────────────────────────
export GIT_COMMIT
GIT_COMMIT="$(git rev-parse --short HEAD 2>/dev/null || echo dev)"
COMPOSE=(docker compose -p sunscrypt --env-file "$ENV_FILE" -f infra/docker-compose.yml)
# Перед выкаткой (в ней могут быть миграции) — копия базы, если она уже есть.
if [ -n "$("${COMPOSE[@]}" ps -q postgres 2>/dev/null)" ]; then
  bash infra/backup.sh || echo "⚠ копия базы перед выкаткой не снята" >&2
fi
say "Собираю и запускаю (порт $WEB_PORT)"
"${COMPOSE[@]}" up -d --build --remove-orphans
# Конфиг шлюза подключён файлом: контейнер его сам не перечитывает.
"${COMPOSE[@]}" exec -T gateway sh -c 'nginx -t -q && nginx -s reload' \
  || echo "⚠ шлюз не перечитал конфиг" >&2

say "Жду ответа приложения"
ok=""
for _ in $(seq 1 60); do
  if curl -fsS -o /dev/null --max-time 5 "http://127.0.0.1:$WEB_PORT/"; then ok=1; break; fi
  sleep 2
done
if [ -z "$ok" ]; then
  "${COMPOSE[@]}" ps >&2 || true
  "${COMPOSE[@]}" logs --tail 80 >&2 || true
  die "Приложение не ответило на 127.0.0.1:$WEB_PORT"
fi
say "Проверяю API, базу и Redis"
health=""
for _ in $(seq 1 30); do
  if health="$(curl -fsS --max-time 5 "http://127.0.0.1:$WEB_PORT/api/health")"; then break; fi
  health=""; sleep 2
done
if [ -z "$health" ]; then
  "${COMPOSE[@]}" ps >&2 || true
  "${COMPOSE[@]}" logs --tail 80 backend >&2 || true
  die "API не ответил: /api/health"
fi
say "API: $health"
say "Память контейнеров: $(docker stats --no-stream --format '{{.Name}} {{.MemUsage}}' $("${COMPOSE[@]}" ps -q) | tr '\n' ';')"

# ── 5. nginx и сертификат ───────────────────────────────────────────────────
SITE=/etc/nginx/sites-available/sunscrypt
LINK=/etc/nginx/sites-enabled/sunscrypt
if [ -f "$SITE" ]; then
  # certbot уже дописал в файл сертификат — меняем только адрес и порт.
  cp "$SITE" "$SITE.bak"
  sed -i -E "s#proxy_pass http://127\.0\.0\.1:[0-9]+;#proxy_pass http://127.0.0.1:$WEB_PORT;#g; s#server_name [^;]+;#server_name $PUBLIC_HOST;#g" "$SITE"
else
  sed -e "s#__HOST__#$PUBLIC_HOST#g" -e "s#__PORT__#$WEB_PORT#g" infra/nginx.conf.template > "$SITE"
fi
ln -sf "$SITE" "$LINK"
if nginx -t 2>/dev/null; then
  systemctl reload nginx
else
  nginx -t || true
  [ -f "$SITE.bak" ] && mv "$SITE.bak" "$SITE" || rm -f "$SITE" "$LINK"
  die "nginx -t не прошёл — конфиг SUNSCRYPT откатан, остальные сайты не тронуты"
fi

if ! grep -q ssl_certificate "$SITE"; then
  if command -v certbot >/dev/null 2>&1; then
    say "Получаю сертификат для $PUBLIC_HOST"
    certbot --nginx -d "$PUBLIC_HOST" --non-interactive --agree-tos \
      --register-unsafely-without-email --redirect \
      || echo "⚠ сертификат не получен — сайт пока работает по http" >&2
  else
    echo "⚠ certbot не установлен — сайт работает по http" >&2
  fi
fi

# ── 6. Что за сервер и пускает ли Bybit ─────────────────────────────────────
# Для того, кто строит дальше: сколько ресурсов на общем сервере и открыт ли
# отсюда Bybit (из облачных контейнеров он закрыт гео-блоком, бриф, раздел 4).
say "Сервер: $(nproc) CPU, память $(free -h | awk '/^Mem:/{print $2" всего, "$7" свободно"}'), диск $(df -h "$APP_DIR" | awk 'NR==2{print $4" свободно"}')"
for url in https://api.bybit.com/v5/market/time https://api-demo.bybit.com/v5/market/time https://stream.bybit.com/v5/public/linear; do
  code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 "$url" 2>/dev/null || echo "нет ответа")"
  say "Bybit $url → $code"
done
# Telegram из России бывает недоступен: 401/404 без токена — значит, связь есть.
code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 https://api.telegram.org/bot0/getMe 2>/dev/null || echo "нет ответа")"
say "Telegram api.telegram.org → $code"

# ── 6б. Движок ──────────────────────────────────────────────────────────────
for svc in signals orchestrator bot; do
  st="$("${COMPOSE[@]}" ps --format '{{.State}}' "$svc" 2>/dev/null || echo "нет")"
  say "Движок: $svc — $st"
done

# ── 6в. Расписание: наблюдение и копии базы ───────────────────────────────
# Свой файл в /etc/cron.d — чужие расписания не трогаем. Вывод — в журнал
# системы с меткой sunscrypt (journalctl -t sunscrypt).
cat > /etc/cron.d/sunscrypt <<CRON
# SUNSCRYPT — ставит infra/deploy.sh, правки руками затрутся.
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
*/5 * * * * root cd $APP_DIR && docker compose -p sunscrypt --env-file $ENV_FILE -f infra/docker-compose.yml exec -T backend python -m app.watch 2>&1 | logger -t sunscrypt
41 3 * * * root bash $APP_DIR/infra/backup.sh 2>&1 | logger -t sunscrypt
23 4 * * * root cd $APP_DIR && MODELS_DIR=$MODELS_DIR docker compose -p sunscrypt --env-file $ENV_FILE -f infra/docker-compose.yml run --rm -T trainer python -m sunscrypt_engine.models_job drift 2>&1 | logger -t sunscrypt
13 1 * * 0 root cd $APP_DIR && MODELS_DIR=$MODELS_DIR docker compose -p sunscrypt --env-file $ENV_FILE -f infra/docker-compose.yml run --rm -T trainer python -m sunscrypt_engine.models_job retrain 2>&1 | logger -t sunscrypt
CRON
chmod 644 /etc/cron.d/sunscrypt
"${COMPOSE[@]}" exec -T backend python -m app.watch | sed 's/^/▸ /' || true
"${COMPOSE[@]}" run --rm -T trainer python -m sunscrypt_engine.models_job drift 2>/dev/null \
  | tail -1 | sed 's/^/▸ Модель: /' || true
say "Копий базы: $(find "$APP_DIR/backups" -name 'sunscrypt-*.dump' 2>/dev/null | wc -l)"

# ── 7. Мастер-ключ и демо-ключ Bybit владельца ──────────────────────────────
# Перешифровка секретов текущим MASTER_KEY (нужна только после его смены).
"${COMPOSE[@]}" exec -T backend python -m app.rotate | sed 's/^/▸ Секреты в базе: /' || true
# Демо-ключ владельца проверяется тем же кодом, что и ключи пользователей
# (app/bybit.py). Ключ передаётся через stdin, в лог — только итог.
if [ -n "$(env_get BYBIT_DEMO_API_KEY)" ]; then
  printf '%s\n%s\n' "$(env_get BYBIT_DEMO_API_KEY)" "$(env_get BYBIT_DEMO_API_SECRET)" \
    | "${COMPOSE[@]}" exec -T backend python -m app.selfcheck \
    || echo "⚠ проверка демо-ключа Bybit не прошла" >&2
fi

SCHEME=http
grep -q ssl_certificate "$SITE" && SCHEME=https
say "Готово: $SCHEME://$PUBLIC_HOST (коммит $(git rev-parse --short HEAD))"
