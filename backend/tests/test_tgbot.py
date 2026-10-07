"""Telegram-бот (этап 9): привязка по коду, команды, уведомления о сделке и
тревоге. Telegram — поддельный (httpx MockTransport), база и Redis — живые."""

import asyncio
import json
import os

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import create_engine, text

from app import bybit, cache, tgbot
from tests import bybit_fake
from tests.conftest import live
from tests.helpers import owner_login, user_with_2fa

pytestmark = live

GOOD_KEY, GOOD_SECRET = "GOODk3yAbCdEf1234", "s3cr3tXyZ0987654321abc"


@pytest.fixture(autouse=True)
def fake_bybit(monkeypatch):
    monkeypatch.setattr(bybit, "transport", bybit_fake.transport)


class FakeTG:
    """Запоминает отправленные сообщения."""

    def __init__(self):
        self.sent: list[tuple[int, str]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content or b"{}")
            if request.url.path.endswith("/sendMessage"):
                self.sent.append((body["chat_id"], body["text"]))
            return httpx.Response(200, json={"ok": True, "result": []})

        self.tg = tgbot.TG("test-token", transport=httpx.MockTransport(handler))


def run(coro_fn, monkeypatch):
    """Каждый вызов — свой цикл событий и свой клиент Redis."""

    async def go():
        r = Redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
        monkeypatch.setattr(cache, "redis", r)
        try:
            return await coro_fn()
        finally:
            await r.aclose()

    return asyncio.run(go())


def msg(chat: int, text: str) -> dict:
    return {"update_id": 1, "message": {"chat": {"id": chat}, "text": text}}


def test_link_commands_and_notifications(client, monkeypatch):
    fake = FakeTG()
    chat = 700_001
    user_with_2fa(client)
    acc = client.post(
        "/api/accounts",
        json={"name": "Мой демо", "mode": "demo", "api_key": GOOD_KEY, "api_secret": GOOD_SECRET},
    ).json()

    # Без привязки — команды не работают.
    run(lambda: tgbot.handle_update(fake.tg, msg(chat, "/status")), monkeypatch)
    assert "не привязан" in fake.sent[-1][1]

    code = client.post("/api/auth/telegram/link").json()["code"]
    run(lambda: tgbot.handle_update(fake.tg, msg(chat, f"/start {code}")), monkeypatch)
    assert "привязан к" in fake.sent[-1][1]
    assert client.get("/api/auth/me").json()["telegram_linked"] is True
    # Код одноразовый.
    run(lambda: tgbot.handle_update(fake.tg, msg(chat + 1, f"/start {code}")), monkeypatch)
    assert "не подошёл" in fake.sent[-1][1]

    run(lambda: tgbot.handle_update(fake.tg, msg(chat, "/status")), monkeypatch)
    assert fake.sent[-1][0] == chat and "Мой демо" in fake.sent[-1][1]

    # Сделка — сразу в чат владельца кабинета.
    fill = {
        "type": "fill",
        "sym": "ADAUSDT",
        "side": "sell",
        "qty": "778",
        "price": "0.6312",
        "fee": "0.098",
        "fee_ccy": "USDT",
        "liquidity": "MAKER",
        "mode": "demo",
    }
    run(lambda: tgbot.notify_fill(fake.tg, f"live:{acc['id']}", fill), monkeypatch)
    assert fake.sent[-1] == (chat, tgbot.fmt_fill(fill, "Мой демо"))
    assert "Продажа 778 ADAUSDT" in fake.sent[-1][1]

    # Тревога по кабинету — владельцу кабинета, один раз.
    run(lambda: tgbot.send_alarms(fake.tg), monkeypatch)  # первый запуск: старое не шлём
    eng = create_engine(os.environ["DATABASE_URL"])
    with eng.begin() as c:
        c.execute(
            text("INSERT INTO engine_events (account_id, kind, message) VALUES (:a, 'alarm', :m)"),
            {"a": acc["id"], "m": "Исполнитель молчит"},
        )
    eng.dispose()
    assert run(lambda: tgbot.send_alarms(fake.tg), monkeypatch) == 1
    assert fake.sent[-1] == (chat, "⚠ Исполнитель молчит")
    assert run(lambda: tgbot.send_alarms(fake.tg), monkeypatch) == 0

    # /stop — аварийная остановка всех кабинетов пользователя.
    run(lambda: tgbot.handle_update(fake.tg, msg(chat, "/stop")), monkeypatch)
    assert "Аварийная остановка" in fake.sent[-1][1]
    assert next(a for a in client.get("/api/accounts").json() if a["id"] == acc["id"])["stopped"]

    # Не владелец не приглашает.
    run(lambda: tgbot.handle_update(fake.tg, msg(chat, "/invite друг")), monkeypatch)
    assert "Только для владельца" in fake.sent[-1][1]

    # Отвязка на сайте.
    assert client.delete("/api/auth/telegram").json()["ok"]
    assert client.get("/api/auth/me").json()["telegram_linked"] is False


def test_owner_invites_from_telegram(client, monkeypatch):
    fake = FakeTG()
    chat = 700_100
    owner_login(client)
    code = client.post("/api/auth/telegram/link").json()["code"]
    run(lambda: tgbot.handle_update(fake.tg, msg(chat, f"/start {code}")), monkeypatch)
    run(lambda: tgbot.handle_update(fake.tg, msg(chat, "/invite для Ивана")), monkeypatch)
    assert "/invite?token=" in fake.sent[-1][1]
    invites = client.get("/api/admin/invites").json()
    assert any(i["note"] == "для Ивана" for i in invites)


def test_fill_message_shows_result_and_day_total():
    base = {"sym": "ADAUSDT", "price": "0.6500", "fee_ccy": "USDT", "mode": "demo", "day_fills": 7}
    close = {
        **base,
        "side": "sell",
        "qty": "778",
        "fee": "0.10",
        "pos_before": 778.0,
        "pos_after": 0.0,
        "closed_qty": 778.0,
        "entry_px": 0.63,
        "pnl": 15.56,
        "net": 15.46,
        "day_net": 42.3,
    }
    text = tgbot.fmt_fill(close, "Мой демо", day_open=-3.5)
    assert text.splitlines() == [
        "🟢 Прибыль +15.46 USD · Мой демо (демо)",
        "Продажа 778 ADAUSDT по 0.6500 — закрыт лонг (вход 0.63)",
        "Результат +15.56 USD, комиссия 0.10 → +15.46 USD",
        "Итог дня по сделкам: +42.30 USD (7 сделок)",
        "С учётом открытых позиций: −3.50 USD",
    ]
    loss = {**close, "pos_after": -100.0, "pnl": -5.0, "net": -5.1, "day_fills": 1, "day_net": -5.1}
    text = tgbot.fmt_fill(loss, "Мой демо")
    assert text.startswith("🔴 Убыток −5.10 USD")
    assert "закрыт лонг, открыт шорт" in text and "(1 сделка)" in text
    opened = {
        **base,
        "side": "buy",
        "qty": "1000",
        "fee": "0.13",
        "pos_before": 0.0,
        "pos_after": 1000.0,
        "closed_qty": 0.0,
        "entry_px": None,
        "pnl": 0.0,
        "net": -0.13,
        "day_net": -0.13,
        "day_fills": 2,
    }
    text = tgbot.fmt_fill(opened, "Мой демо")
    assert text.splitlines()[:3] == [
        "⚪ Открыт лонг · Мой демо (демо)",
        "Покупка 1000 ADAUSDT по 0.6500 (≈ 650 USD)",
        "Комиссия −0.13 USD; прибыль или убыток — при закрытии",
    ]
    assert "(2 сделки)" in text
