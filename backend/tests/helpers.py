"""Общее для живых тестов: владелец (из настроек тестов) и приглашения."""

import os
import re
import uuid

import pyotp

PASSWORD = "correct horse battery"
OWNER = (os.environ.get("OWNER_EMAIL", ""), os.environ.get("OWNER_PASSWORD", ""))


def token_of(link: str, kind: str) -> str:
    m = re.fullmatch(rf"https://sunscrypt\.test/{kind}\?token=(\S+)", link)
    assert m, link
    return m.group(1)


def fresh_email() -> str:
    return f"user-{uuid.uuid4().hex[:10]}@example.com"


_owner_cookies: dict[str, str] = {}


def owner_login(client) -> None:
    """Сессия владельца. Первый раз — вход и включение 2FA; дальше —
    сохранённая cookie (один код 2FA дважды сервер не примет)."""
    client.cookies.clear()
    if _owner_cookies:
        client.cookies.update(_owner_cookies)
        return
    r = client.post("/api/auth/login", json={"email": OWNER[0], "password": OWNER[1]})
    assert r.status_code == 200, r.text
    assert r.json()["mfa_required"] is False
    secret = client.post("/api/auth/2fa/setup").json()["secret"]
    assert (
        client.post("/api/auth/2fa/enable", json={"code": pyotp.TOTP(secret).now()}).status_code
        == 200
    )
    _owner_cookies.update(dict(client.cookies))


def invite(client) -> str:
    owner_login(client)
    link = client.post("/api/admin/invites", json={"note": "тест"}).json()["link"]
    client.cookies.clear()
    return token_of(link, "invite")


def user_with_2fa(client) -> str:
    """Новый пользователь по приглашению, с включённой 2FA; остаётся вошедшим."""
    tok = invite(client)
    email = fresh_email()
    r = client.post(
        "/api/auth/register", json={"invite": tok, "email": email, "password": PASSWORD}
    )
    assert r.status_code == 201, r.text
    secret = client.post("/api/auth/2fa/setup").json()["secret"]
    assert (
        client.post("/api/auth/2fa/enable", json={"code": pyotp.TOTP(secret).now()}).status_code
        == 200
    )
    return email
