#!/usr/bin/env bash
#
# Выкатка SUNSCRYPT на сервере. Запускается из GitHub Actions по SSH
# (.github/workflows/sunscrypt-deploy.yml) после каждого пуша в ветку
# sunscrypt; руками — `bash /opt/sunscrypt/infra/deploy.sh` от root.
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

# ── 4. Сборка и запуск ──────────────────────────────────────────────────────
export GIT_COMMIT
GIT_COMMIT="$(git rev-parse --short HEAD 2>/dev/null || echo dev)"
COMPOSE=(docker compose -p sunscrypt --env-file "$ENV_FILE" -f infra/docker-compose.yml)
say "Собираю и запускаю (порт $WEB_PORT)"
"${COMPOSE[@]}" up -d --build --remove-orphans

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

# ── 7. Демо-ключ Bybit владельца: работает ли и какие у него права ──────────
# Ключ и подпись в лог не попадают: только права, IP-привязка и баланс демо.
# Ключ с правом вывода/переводов — громкое предупреждение (бриф, правило 3).
if [ -n "$(env_get BYBIT_DEMO_API_KEY)" ] && command -v python3 >/dev/null 2>&1; then
  BYBIT_KEY="$(env_get BYBIT_DEMO_API_KEY)" BYBIT_SECRET="$(env_get BYBIT_DEMO_API_SECRET)" \
  python3 - <<'PY' || echo "⚠ проверка демо-ключа Bybit не прошла" >&2
import hashlib, hmac, json, os, time, urllib.request

key, secret = os.environ["BYBIT_KEY"].strip(), os.environ["BYBIT_SECRET"].strip()

def get(path, query="", host="api-demo.bybit.com"):
    ts, rw = str(int(time.time() * 1000)), "5000"
    sign = hmac.new(secret.encode(), (ts + key + rw + query).encode(), hashlib.sha256).hexdigest()
    req = urllib.request.Request(
        f"https://{host}{path}" + (f"?{query}" if query else ""),
        headers={"X-BAPI-API-KEY": key, "X-BAPI-TIMESTAMP": ts, "X-BAPI-RECV-WINDOW": rw,
                 "X-BAPI-SIGN": sign},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)

info = get("/v5/user/query-api")
if info.get("retCode") != 0:
    print(f"▸ Демо-ключ Bybit: ошибка {info.get('retCode')} — {info.get('retMsg')}")
    # Частая ошибка — ключ создан на основном счёте, а не в Demo Trading.
    # Спрашиваем только сведения о ключе (чтение), ордеров нет.
    main = get("/v5/user/query-api", host="api.bybit.com")
    if main.get("retCode") == 0:
        print("⚠ Это ключ ОСНОВНОГО (реального) счёта, не демо. Для демо нужен ключ, "
              "созданный в режиме Demo Trading. Реальный ключ сервис сейчас не использует.")
        r = main["result"]
        perms = {k: v for k, v in (r.get("permissions") or {}).items() if v}
        print(f"▸ Права этого ключа: {perms}; IP-привязка: {r.get('ips')}")
    else:
        print(f"▸ На основном счёте ключ тоже не принят: {main.get('retMsg')} — "
              "вероятно, ключ или секрет скопированы с ошибкой")
    raise SystemExit(0)
res = info["result"]
perms = {k: v for k, v in (res.get("permissions") or {}).items() if v}
danger = {k: v for k, v in perms.items() if k in ("Wallet", "Exchange") or "Withdraw" in str(v)}
print(f"▸ Демо-ключ Bybit работает. Права: {perms}")
print(f"▸ Только чтение: {res.get('readOnly') == 1}; IP-привязка: {res.get('ips')}; "
      f"единый счёт (UTA): {res.get('uta')}")
if danger:
    print(f"⚠ У ключа есть права на вывод/переводы: {danger} — такой ключ сервис отклонит")
bal = get("/v5/account/wallet-balance", "accountType=UNIFIED")
if bal.get("retCode") == 0 and bal["result"]["list"]:
    print(f"▸ Демо-баланс: {float(bal['result']['list'][0]['totalEquity'] or 0):,.2f} USD")
else:
    print(f"▸ Демо-баланс: не прочитан ({bal.get('retMsg')})")
PY
fi

SCHEME=http
grep -q ssl_certificate "$SITE" && SCHEME=https
say "Готово: $SCHEME://$PUBLIC_HOST (коммит $(git rev-parse --short HEAD))"
