"""Этап 3 на живых PostgreSQL и Redis (Bybit — поддельный): демо-ключ
проходит, ключ с выводом отклоняется, ключ нигде не виден — ни в ответах,
ни в логах, ни открытым текстом в базе."""

import logging
import os

import pytest
from sqlalchemy import create_engine, text

from app import bybit
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
            text("SELECT api_key_enc, api_secret_enc FROM exchange_accounts WHERE id = :i"),
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
        "/api/auth/register", json={"invite": tok, "email": fresh_email(), "password": PASSWORD}
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
