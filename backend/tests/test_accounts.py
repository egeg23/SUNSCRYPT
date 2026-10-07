"""Этап 3 на живых PostgreSQL и Redis (Bybit — поддельный): демо-ключ
проходит, ключ с выводом отклоняется, ключ нигде не виден — ни в ответах,
ни в логах, ни открытым текстом в базе."""

import logging
import os

import pytest
from sqlalchemy import create_engine, text

from app import bybit
from app.auth import TERMS_VERSION
from tests import bybit_fake
from tests.conftest import live
from tests.helpers import user_with_2fa

pytestmark = live

GOOD_KEY, GOOD_SECRET = "GOODk3yAbCdEf1234", "s3cr3tXyZ0987654321abc"


@pytest.fixture(autouse=True)
def fake_bybit(monkeypatch):
    monkeypatch.setattr(bybit, "transport", bybit_fake.transport)


@pytest.fixture(scope="module")
def db():
    eng = create_engine(os.environ["DATABASE_URL"])
    yield eng
    eng.dispose()


def add(client, key=GOOD_KEY, secret=GOOD_SECRET, mode="demo", name="Демо"):
    return client.post(
        "/api/accounts", json={"name": name, "mode": mode, "api_key": key, "api_secret": secret}
    )


def test_demo_key_passes_and_never_leaks(client, db, caplog):
    user_with_2fa(client)
    caplog.set_level(logging.DEBUG)
    r = add(client)
    assert r.status_code == 201, r.text
    acc = r.json()
    assert acc["key_tail"] == GOOD_KEY[-4:] and acc["equity_usd"] == 10000.5
    assert acc["mode"] == "demo" and acc["status"] == "ok"

    listed = client.get("/api/accounts").text
    rechecked = client.post(f"/api/accounts/{acc['id']}/recheck").text
    for blob in (r.text, listed, rechecked, caplog.text):
        assert GOOD_KEY not in blob and GOOD_SECRET not in blob

    with db.connect() as c:
        row = c.execute(
            text("SELECT api_key_enc, api_secret_enc FROM account_keys WHERE account_id = :i"),
            {"i": acc["id"]},
        ).one()
    assert GOOD_KEY.encode() not in bytes(row[0]) and GOOD_SECRET.encode() not in bytes(row[1])


def test_withdraw_key_rejected(client):
    user_with_2fa(client)
    r = add(client, key="WITHDRAWk3y12345")
    assert r.status_code == 400
    assert any("переводы и вывод" in p for p in r.json()["detail"]["problems"])
    assert client.get("/api/accounts").json() == []


def test_real_key_as_demo_explained(client):
    user_with_2fa(client)
    r = add(client, key="REALk3y1234567890")
    assert r.status_code == 400
    assert "реального счёта" in r.json()["detail"]["problems"][0]


def test_validation_error_does_not_echo_secret(client):
    user_with_2fa(client)
    r = add(client, secret="bad secret with spaces!!")
    assert r.status_code == 422 and "bad secret" not in r.text


def test_requires_2fa(client):
    from tests.helpers import PASSWORD, fresh_email, invite

    tok = invite(client)
    client.post(
        "/api/auth/register",
        json={"invite": tok, "email": fresh_email(), "password": PASSWORD, "terms": TERMS_VERSION},
    )
    r = add(client)
    assert r.status_code == 403 and "2FA" in r.text


def test_stop_delete_and_isolation(client):
    user_with_2fa(client)
    acc = add(client).json()
    assert client.post(f"/api/accounts/{acc['id']}/stop", json={"stopped": True}).json()["stopped"]
    mine = dict(client.cookies)

    user_with_2fa(client)  # другой пользователь чужой кабинет не видит и не трогает
    assert client.get("/api/accounts").json() == []
    assert client.delete(f"/api/accounts/{acc['id']}").status_code == 404

    client.cookies.clear()
    client.cookies.update(mine)
    assert client.delete(f"/api/accounts/{acc['id']}").json() == {"ok": True}
    assert client.get("/api/accounts").json() == []


def test_invisible_chars_from_phone_are_cleaned(client):
    user_with_2fa(client)
    r = add(client, key="​" + GOOD_KEY + " \n", secret=GOOD_SECRET + "⁠")
    assert r.status_code == 201, r.text
    assert r.json()["key_tail"] == GOOD_KEY[-4:]


def test_owner_demo_account_from_secrets(client, db, monkeypatch):
    import asyncio

    from app import accounts
    from app.config import get_settings
    from app.db import SessionLocal
    from tests.helpers import OWNER, owner_login

    owner_login(client)  # владелец существует и вошёл
    monkeypatch.setenv("BYBIT_DEMO_API_KEY", "GOODowner0001")
    monkeypatch.setenv("BYBIT_DEMO_API_SECRET", "ownerSecret12345")
    get_settings.cache_clear()
    try:

        async def run():
            async with SessionLocal() as s:
                await accounts.ensure_owner_demo(s)
                await accounts.ensure_owner_demo(s)  # второй раз — не дублирует

        asyncio.run(run())
    finally:
        get_settings.cache_clear()
    owner_login(client)
    mine = [a for a in client.get("/api/accounts").json() if a["key_tail"] == "0001"]
    assert len(mine) == 1 and mine[0]["trading_enabled"] and mine[0]["mode"] == "demo"
    assert OWNER[0]


def _real_flag(db, on: bool):
    with db.begin() as c:
        c.execute(
            text("UPDATE system_flags SET value = :v WHERE key = 'real_trading_enabled'"), {"v": on}
        )


def test_switch_to_real_needs_owner_flag_2fa_risk_and_limits(client, db):
    import time

    import pyotp

    from tests.helpers import PASSWORD, fresh_email, invite

    # Пользователь со своей 2FA (секрет нужен для свежих кодов).
    tok = invite(client)
    email = fresh_email()
    client.post(
        "/api/auth/register",
        json={"invite": tok, "email": email, "password": PASSWORD, "terms": TERMS_VERSION},
    )
    secret = client.post("/api/auth/2fa/setup").json()["secret"]
    client.post("/api/auth/2fa/enable", json={"code": pyotp.TOTP(secret).now()})

    acc = add(client).json()
    assert acc["mode"] == "demo" and acc["keys"]["real"] is None
    # Реальный ключ — отдельно; ключ демо-счёта на «реальный» не подходит.
    r = client.post(
        f"/api/accounts/{acc['id']}/keys",
        json={"mode": "real", "api_key": "REALk3y1234567", "api_secret": GOOD_SECRET},
    )
    assert r.status_code == 200, r.text
    assert r.json()["keys"]["real"]["key_tail"] == "4567" and r.json()["mode"] == "demo"

    url = f"/api/accounts/{acc['id']}/mode"
    full = {"mode": "real", "confirm_risk": True, "capital_usd": 500, "daily_loss_pct": 3}
    _real_flag(db, False)
    r = client.post(url, json={**full, "code": pyotp.TOTP(secret).at(time.time() + 30)})
    assert r.status_code == 400 and "выключена владельцем" in r.text

    _real_flag(db, True)
    try:
        assert (
            "риски" in client.post(url, json={**full, "confirm_risk": False, "code": "123456"}).text
        )
        assert (
            "лимит"
            in client.post(url, json={"mode": "real", "confirm_risk": True, "code": "123456"}).text
        )
        assert "Неверный код" in client.post(url, json={**full, "code": "000000"}).text
        r = client.post(url, json={**full, "code": pyotp.TOTP(secret).at(time.time() + 30)})
        assert r.status_code == 200, r.text
        assert r.json()["mode"] == "real" and r.json()["capital_usd"] == 500
        # Обратно на демо — без кода.
        assert client.post(url, json={"mode": "demo"}).json()["mode"] == "demo"
    finally:
        _real_flag(db, False)
    with db.connect() as c:
        msgs = [
            m
            for (m,) in c.execute(
                text(
                    "SELECT message FROM engine_events "
                    "WHERE account_id = :a AND kind = 'mode' ORDER BY id"
                ),
                {"a": acc["id"]},
            )
        ]
    assert msgs[0].startswith("Счёт: демо → реальный") and msgs[1].startswith(
        "Счёт: реальный → демо"
    )


def test_real_trading_switch_is_owner_only(client):
    user_with_2fa(client)
    assert (
        client.post("/api/admin/real-trading", json={"enabled": True, "code": "123456"}).status_code
        == 403
    )
