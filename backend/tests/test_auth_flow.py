"""Сквозной цикл этапа 2 на настоящих PostgreSQL и Redis.

Доступ закрытый: владелец создаётся из настроек, включает 2FA, выдаёт
приглашение; приглашённый регистрируется по ссылке, входит, включает 2FA;
сброс пароля — по ссылке от владельца. Плюс отказы: без приглашения, чужой
источник, неверный пароль, лимиты, раздел владельца без прав."""

import os
import time

import pyotp
import pytest
from sqlalchemy import create_engine, text

from tests.conftest import live
from tests.helpers import OWNER, PASSWORD, fresh_email, invite, owner_login, token_of

pytestmark = live


@pytest.fixture(scope="module")
def db():
    url = os.environ.get(
        "DATABASE_URL", "postgresql+psycopg://sunscrypt:sunscrypt@localhost:5432/sunscrypt"
    )
    eng = create_engine(url)
    yield eng
    eng.dispose()


def test_owner_is_bootstrapped_admin(client):
    owner_login(client)
    me = client.get("/api/auth/me").json()
    assert me["is_admin"] is True and me["totp_enabled"] is True
    assert any(u["email"] == OWNER[0] for u in client.get("/api/admin/users").json())


def test_register_requires_invite(client):
    r = client.post(
        "/api/auth/register",
        json={"invite": "x" * 20, "email": fresh_email(), "password": PASSWORD},
    )
    assert r.status_code == 400


def test_full_cycle(client, db):
    tok = invite(client)
    email = fresh_email()

    # Регистрация по приглашению — сразу вход; приглашение одноразовое.
    r = client.post(
        "/api/auth/register", json={"invite": tok, "email": email.upper(), "password": PASSWORD}
    )
    assert r.status_code == 201, r.text
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "secure" in cookie and "samesite=lax" in cookie
    me = client.get("/api/auth/me").json()
    assert me["email"] == email and me["totp_enabled"] is False and me["is_admin"] is False
    r = client.post(
        "/api/auth/register", json={"invite": tok, "email": fresh_email(), "password": PASSWORD}
    )
    assert r.status_code == 400

    # Не владелец — раздел владельца закрыт (сначала по 2FA, потом по роли).
    assert client.post("/api/admin/invites", json={}).status_code == 403

    # Включение 2FA; секрет в базе только шифрованный.
    secret = client.post("/api/auth/2fa/setup").json()["secret"]
    with db.connect() as c:
        enc = c.execute(
            text("SELECT totp_secret_enc FROM users WHERE email = :e"), {"e": email}
        ).scalar_one()
    assert secret.encode() not in bytes(enc)
    assert client.post("/api/auth/2fa/enable", json={"code": "000000"}).status_code == 400
    code = pyotp.TOTP(secret).now()
    assert client.post("/api/auth/2fa/enable", json={"code": code}).status_code == 200
    assert client.post("/api/admin/invites", json={}).status_code == 403

    # Выход → вход требует код; тот же код повторно не принимается.
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/auth/me").status_code == 401
    r = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert r.json()["mfa_required"] is True
    assert client.get("/api/auth/logins").status_code == 401
    assert client.post("/api/auth/2fa/verify", json={"code": code}).status_code == 401
    nxt = pyotp.TOTP(secret).at(time.time() + 30)
    assert client.post("/api/auth/2fa/verify", json={"code": nxt}).status_code == 200

    # Журнал входов: есть и неудачные попытки.
    kinds = {(e["event"], e["success"]) for e in client.get("/api/auth/logins").json()}
    assert ("login", True) in kinds and ("2fa", False) in kinds

    # Сброс пароля по ссылке от владельца: сессии закрываются.
    owner_login(client)
    users = client.get("/api/admin/users").json()
    uid = next(u["id"] for u in users if u["email"] == email)
    link = client.post(f"/api/admin/users/{uid}/reset-link").json()["link"]
    client.cookies.clear()
    new_password = "another long password"
    r = client.post(
        "/api/auth/password/reset",
        json={"token": token_of(link, "reset"), "password": new_password},
    )
    assert r.status_code == 200
    r = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 401
    r = client.post("/api/auth/login", json={"email": email, "password": new_password})
    assert r.status_code == 200 and r.json()["mfa_required"] is True


def test_short_password_rejected(client):
    r = client.post(
        "/api/auth/register", json={"invite": "x" * 20, "email": fresh_email(), "password": "short"}
    )
    assert r.status_code == 422


def test_foreign_origin_rejected(client):
    r = client.post(
        "/api/auth/login",
        json={"email": OWNER[0], "password": OWNER[1]},
        headers={"origin": "https://evil.example"},
    )
    assert r.status_code == 403


def test_login_rate_limited(client):
    email = fresh_email()
    codes = [
        client.post(
            "/api/auth/login", json={"email": email, "password": "wrong-password"}
        ).status_code
        for _ in range(9)
    ]
    assert codes[:8] == [401] * 8 and codes[8] == 429


def test_admin_needs_login(client):
    client.cookies.clear()
    assert client.get("/api/admin/users").status_code == 401
