# SUNSCRYPT

Сервис автоматической торговли USDT-перпетуалами Bybit: регистрация, подключение кабинета по API,
демо/реальный счёт, дашборд в реальном времени, Telegram-уведомления. Сигнал — дообученная модель Kronos,
исполнение — NautilusTrader 2.x. **Прибыль не гарантирована.**

## Состав

| папка | что |
|---|---|
| `backend/` | API на FastAPI: Postgres (SQLAlchemy + Alembic), Redis |
| `web/` | веб-интерфейс на Next.js 16 (React 19), сборка `standalone` |
| `engine/` | торговый движок: быстрый инференс Kronos, дообучение, стратегия и бэктест на NautilusTrader, проверка версий Nautilus |
| `infra/` | конфиг Caddy (HTTPS, маршрутизация `/api/*` → backend, остальное → web) |
| `brand/` | логотип, палитра, материалы Telegram-бота |
| `docs/` | план и заметки |

## Запуск на сервере

```bash
cp .env.example .env          # задать POSTGRES_PASSWORD, SUNS_SITE_ADDRESS
docker compose up -d --build
curl http://<ip>/api/health   # {"status":"ok",...}
```

`SUNS_SITE_ADDRESS=:80` — временный адрес по IP сервера. Для переноса на домен укажите `maximov-tech.ru`:
Caddy сам выпустит сертификат.

## Разработка

```bash
cd backend && uv sync && uv run pytest -q          # API
cd web && npm install && npm run dev                # веб, /api проксируется на localhost:8000
python engine/tools/check_nautilus.py --test        # проверка новой версии Nautilus перед обновлением
```

## Правила

- По умолчанию всё работает на демо-счёте. Реальная торговля выключена флагом `SUNS_LIVE_TRADING_ENABLED=false`.
- Ключи бирж хранятся только в зашифрованном виде; ключи с правом вывода отклоняются.
- Секреты — только в `.env` на сервере и в хранилище секретов, никогда в репозитории.
