# SUNSCRYPT

Сервис автоматической торговли перпетуалами на Bybit: сигнал модели Kronos →
исполнение NautilusTrader → Bybit, дашборд в реальном времени, Telegram-бот.
Сейчас — только демо-счёт.

- Контекст и план — [`docs/BRIEF.md`](docs/BRIEF.md).
- Правила для разработки — [`CLAUDE.md`](CLAUDE.md).
- Выкатка: каждый пуш в `main` →
  [`.github/workflows/sunscrypt-deploy.yml`](.github/workflows/sunscrypt-deploy.yml)
  (линтеры, тесты, сборка образов → выкатка) → наш сервер →
  [`infra/deploy.sh`](infra/deploy.sh).

## Устройство

| папка | что |
|---|---|
| `backend/` | API на FastAPI (Python 3.13), PostgreSQL через SQLAlchemy, миграции Alembic, Redis |
| `web/` | сайт на Next.js + TypeScript; бренд — `/brand`, файлы — `web/public/brand` |
| `engine/` | Kronos + NautilusTrader (переносится из исследования) |
| `infra/` | Docker Compose (проект `sunscrypt`): gateway (nginx) → web и backend, PostgreSQL, Redis |

Снаружи: хостовый nginx с сертификатом → `127.0.0.1:WEB_PORT` → gateway;
`/api/*` — backend, остальное — сайт.

## Локально

```bash
cd backend && python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/ruff check . && .venv/bin/pytest -q          # живые тесты: SUNSCRYPT_TEST_LIVE=1
cd ../web && npm ci && npm run lint && npm run typecheck && npm run dev
# весь стек:
printf 'POSTGRES_PASSWORD=local\nWEB_PORT=3471\n' > /tmp/s.env
docker compose -p sunscrypt --env-file /tmp/s.env -f infra/docker-compose.yml up -d --build
```

Прибыль не гарантирована. Торговля криптовалютными деривативами связана с
высоким риском потери средств.
