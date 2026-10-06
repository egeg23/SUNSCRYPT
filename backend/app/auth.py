"""Регистрация и вход (бриф, этап 2).

Доступ закрытый (решение владельца): аккаунт создаётся только по
приглашению, которое выдаёт владелец. Приглашённым почту подтверждать не
нужно — ссылку им дал владелец.

Почта + пароль (argon2), подтверждение почты, сброс пароля, TOTP-2FA
(обязательна перед добавлением ключей Bybit — зависимость require_2fa),
httpOnly-сессии, лимиты частоты, журнал входов.

Ответы не выдают, есть ли такая почта: регистрация и «забыли пароль»
отвечают одинаково.
"""

import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app import crypto, mailer
from app.config import get_settings
from app.db import get_session
from app.models import EmailToken, Invite, LoginEvent, Session, User
from app.ratelimit import enforce

router = APIRouter(prefix="/api/auth", tags=["auth"])

COOKIE = "sunscrypt_session"
TOTP_PURPOSE = "user.totp"
VERIFY_TTL = timedelta(hours=48)
RESET_TTL = timedelta(hours=1)
MIN_PASSWORD = 10

_ph = PasswordHasher()
# Хеш-приманка: на неизвестную почту тратим столько же времени, сколько на
# проверку пароля, чтобы по времени ответа нельзя было узнать, есть ли адрес.
_DUMMY_HASH = _ph.hash("sunscrypt-dummy-password")

Db = Annotated[AsyncSession, Depends(get_session)]


# ── Модели запросов ─────────────────────────────────────────────────────────
class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class Register(BaseModel):
    invite: str = Field(min_length=10, max_length=128)
    email: EmailStr
    password: str = Field(min_length=MIN_PASSWORD, max_length=256)


class TokenIn(BaseModel):
    token: str = Field(min_length=10, max_length=128)


class EmailIn(BaseModel):
    email: EmailStr


class ResetIn(BaseModel):
    token: str = Field(min_length=10, max_length=128)
    password: str = Field(min_length=MIN_PASSWORD, max_length=256)


class CodeIn(BaseModel):
    code: str = Field(pattern=r"^\d{6}$")


# ── Вспомогательное ─────────────────────────────────────────────────────────
def _now() -> datetime:
    return datetime.now(UTC)


def _norm(email: str) -> str:
    return email.strip().lower()


def _ip(request: Request) -> str | None:
    return request.headers.get("x-real-ip") or (request.client.host if request.client else None)


def _ua(request: Request) -> str | None:
    ua = request.headers.get("user-agent")
    return ua[:255] if ua else None


async def _log(
    db: AsyncSession,
    request: Request,
    *,
    email: str,
    event: str,
    success: bool,
    user_id: uuid.UUID | None = None,
    reason: str | None = None,
) -> None:
    db.add(
        LoginEvent(
            user_id=user_id,
            email=email,
            event=event,
            success=success,
            reason=reason,
            ip=_ip(request),
            user_agent=_ua(request),
        )
    )


async def _email_link(db: AsyncSession, user: User, purpose: str, ttl: timedelta) -> str:
    token = crypto.new_token()
    db.add(
        EmailToken(
            token_hash=crypto.token_hash(token),
            user_id=user.id,
            purpose=purpose,
            expires_at=_now() + ttl,
        )
    )
    path = "verify" if purpose == "verify" else "reset"
    return f"{get_settings().public_url}/{path}?token={token}"


async def _send_verify(db: AsyncSession, user: User) -> None:
    link = await _email_link(db, user, "verify", VERIFY_TTL)
    await mailer.send(
        db,
        user.email,
        "SUNSCRYPT: подтвердите почту",
        "Здравствуйте!\n\nЧтобы закончить регистрацию в SUNSCRYPT, откройте ссылку "
        f"(действует 48 часов):\n{link}\n\n"
        "Если вы не регистрировались — просто удалите это письмо.",
    )


async def _take_token(db: AsyncSession, token: str, purpose: str) -> EmailToken:
    row = await db.get(EmailToken, crypto.token_hash(token))
    if row is None or row.purpose != purpose or row.used_at or row.expires_at < _now():
        raise HTTPException(400, "Ссылка недействительна или устарела. Запросите новую.")
    row.used_at = _now()
    return row


def check_totp(user: User, code: str) -> bool:
    """Проверка кода с окном ±30 с и защитой от повторного использования."""
    if not user.totp_secret_enc:
        return False
    secret = crypto.decrypt(user.totp_secret_enc, TOTP_PURPOSE).decode()
    totp = pyotp.TOTP(secret)
    now_step = int(time.time()) // 30
    for step in (now_step - 1, now_step, now_step + 1):
        if user.totp_last_step is not None and step <= user.totp_last_step:
            continue
        if pyotp.utils.strings_equal(totp.at(step * 30), code):
            user.totp_last_step = step
            return True
    return False


async def _start_session(
    db: AsyncSession, request: Request, response: Response, user: User, mfa: bool
) -> None:
    token = crypto.new_token()
    days = get_settings().session_days
    db.add(
        Session(
            token_hash=crypto.token_hash(token),
            user_id=user.id,
            mfa_passed=mfa,
            ip=_ip(request),
            user_agent=_ua(request),
            expires_at=_now() + timedelta(days=days),
        )
    )
    response.set_cookie(
        COOKIE,
        token,
        max_age=days * 86400,
        httponly=True,
        secure=get_settings().cookie_secure,
        samesite="lax",
        path="/",
    )


# ── Зависимости для других модулей ──────────────────────────────────────────
class Current:
    def __init__(self, user: User, session: Session):
        self.user = user
        self.session = session


async def current(request: Request, db: Db) -> Current:
    """Вошедший пользователь (2FA может быть ещё не пройдена)."""
    token = request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(401, "Нужно войти")
    sess = await db.get(Session, crypto.token_hash(token))
    if sess is None or sess.expires_at < _now():
        raise HTTPException(401, "Сессия истекла — войдите снова")
    user = await db.get(User, sess.user_id)
    if user is None:
        raise HTTPException(401, "Нужно войти")
    return Current(user, sess)


async def require_login(cur: Annotated[Current, Depends(current)]) -> Current:
    """Вход завершён: если 2FA включена — код введён."""
    if cur.user.totp_enabled_at and not cur.session.mfa_passed:
        raise HTTPException(401, "Введите код из приложения 2FA")
    return cur


async def require_2fa(cur: Annotated[Current, Depends(require_login)]) -> Current:
    """Для опасных действий (ключи Bybit, реальный счёт): 2FA обязательна."""
    if not cur.user.totp_enabled_at:
        raise HTTPException(403, "Сначала включите двухфакторную защиту (2FA)")
    return cur


CurrentAny = Annotated[Current, Depends(current)]
CurrentUser = Annotated[Current, Depends(require_login)]


# ── Регистрация и почта ─────────────────────────────────────────────────────
@router.post("/register", status_code=201)
async def register(body: Register, request: Request, response: Response, db: Db) -> dict:
    """Регистрация по приглашению; сразу входит в аккаунт."""
    await enforce(f"register:ip:{_ip(request)}", 10, 3600)
    inv = await db.get(Invite, crypto.token_hash(body.invite))
    if inv is None or inv.used_at or inv.expires_at < _now():
        raise HTTPException(400, "Приглашение недействительно или устарело. Попросите новое.")
    email = _norm(body.email)
    if await db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(409, "Такая почта уже зарегистрирована — войдите")
    user = User(email=email, password_hash=_ph.hash(body.password), email_verified_at=_now())
    db.add(user)
    await db.flush()
    inv.used_at, inv.used_by = _now(), user.id
    await _start_session(db, request, response, user, mfa=True)
    await _log(db, request, email=email, event="register", success=True, user_id=user.id)
    await db.commit()
    return {"ok": True}


async def new_invite(db: AsyncSession, by: User, note: str | None, days: int = 7) -> str:
    token = crypto.new_token()
    db.add(
        Invite(
            token_hash=crypto.token_hash(token),
            note=note,
            created_by=by.id,
            expires_at=_now() + timedelta(days=days),
        )
    )
    return f"{get_settings().public_url}/invite?token={token}"


async def new_reset_link(db: AsyncSession, user: User) -> str:
    """Ссылка сброса пароля, которую владелец передаёт сам (почты нет)."""
    return await _email_link(db, user, "reset", RESET_TTL)


async def ensure_owner(db: AsyncSession) -> None:
    """Создаёт владельца из настроек, если его ещё нет."""
    s = get_settings()
    if not (s.owner_email and s.owner_password):
        return
    email = _norm(s.owner_email)
    user = await db.scalar(select(User).where(User.email == email))
    if user is None:
        db.add(
            User(
                email=email,
                password_hash=_ph.hash(s.owner_password.get_secret_value()),
                email_verified_at=_now(),
                is_admin=True,
            )
        )
    elif not user.is_admin:
        user.is_admin = True
    await db.commit()


@router.post("/verify")
async def verify_email(body: TokenIn, db: Db) -> dict:
    row = await _take_token(db, body.token, "verify")
    user = await db.get(User, row.user_id)
    if user and not user.email_verified_at:
        user.email_verified_at = _now()
    await db.commit()
    return {"ok": True}


@router.post("/verify/resend")
async def resend_verify(body: EmailIn, request: Request, db: Db) -> dict:
    email = _norm(body.email)
    await enforce(f"resend:ip:{_ip(request)}", 10, 3600)
    await enforce(f"resend:email:{email}", 3, 3600)
    user = await db.scalar(select(User).where(User.email == email))
    if user and not user.email_verified_at:
        await _send_verify(db, user)
        await db.commit()
    return {"ok": True}


# ── Вход и выход ────────────────────────────────────────────────────────────
@router.post("/login")
async def login(body: Credentials, request: Request, response: Response, db: Db) -> dict:
    email = _norm(body.email)
    await enforce(f"login:ip:{_ip(request)}", 20, 900)
    await enforce(f"login:email:{email}", 8, 900)
    user = await db.scalar(select(User).where(User.email == email))
    try:
        _ph.verify(user.password_hash if user else _DUMMY_HASH, body.password)
        ok = user is not None
    except (VerificationError, InvalidHashError):
        ok = False
    if not ok:
        await _log(
            db,
            request,
            email=email,
            event="login",
            success=False,
            user_id=user.id if user else None,
            reason="bad_password" if user else "no_user",
        )
        await db.commit()
        raise HTTPException(401, "Неверная почта или пароль")
    assert user is not None
    if not user.email_verified_at:
        await _log(
            db,
            request,
            email=email,
            event="login",
            success=False,
            user_id=user.id,
            reason="email_not_verified",
        )
        await db.commit()
        raise HTTPException(403, "Подтвердите почту: ссылка в письме после регистрации")
    if _ph.check_needs_rehash(user.password_hash):
        user.password_hash = _ph.hash(body.password)
    mfa_required = user.totp_enabled_at is not None
    await _start_session(db, request, response, user, mfa=not mfa_required)
    await _log(db, request, email=email, event="login", success=True, user_id=user.id)
    await db.commit()
    return {"ok": True, "mfa_required": mfa_required}


@router.post("/2fa/verify")
async def verify_2fa(body: CodeIn, cur: CurrentAny, request: Request, db: Db) -> dict:
    await enforce(f"2fa:user:{cur.user.id}", 8, 900)
    if not cur.user.totp_enabled_at:
        raise HTTPException(400, "2FA не включена")
    ok = check_totp(cur.user, body.code)
    await _log(
        db,
        request,
        email=cur.user.email,
        event="2fa",
        success=ok,
        user_id=cur.user.id,
        reason=None if ok else "bad_code",
    )
    if ok:
        cur.session.mfa_passed = True
    await db.commit()
    if not ok:
        raise HTTPException(401, "Неверный код")
    return {"ok": True}


@router.post("/logout")
async def logout(request: Request, response: Response, db: Db) -> dict:
    token = request.cookies.get(COOKIE)
    if token:
        await db.execute(delete(Session).where(Session.token_hash == crypto.token_hash(token)))
        await db.commit()
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
async def me(cur: CurrentAny) -> dict:
    u = cur.user
    return {
        "email": u.email,
        "totp_enabled": u.totp_enabled_at is not None,
        "mfa_passed": cur.session.mfa_passed,
        "is_admin": u.is_admin,
    }


@router.get("/logins")
async def logins(cur: CurrentUser, db: Db) -> list[dict]:
    rows = await db.scalars(
        select(LoginEvent)
        .where(LoginEvent.user_id == cur.user.id)
        .order_by(LoginEvent.created_at.desc())
        .limit(50)
    )
    return [
        {
            "at": r.created_at.isoformat(),
            "event": r.event,
            "success": r.success,
            "reason": r.reason,
            "ip": r.ip,
            "user_agent": r.user_agent,
        }
        for r in rows
    ]


# ── 2FA: включение ──────────────────────────────────────────────────────────
@router.post("/2fa/setup")
async def setup_2fa(cur: CurrentUser, db: Db) -> dict:
    """Новый секрет TOTP (ещё не включён — до ввода кода)."""
    if cur.user.totp_enabled_at:
        raise HTTPException(409, "2FA уже включена")
    secret = pyotp.random_base32()
    cur.user.totp_secret_enc = crypto.encrypt(secret.encode(), TOTP_PURPOSE)
    cur.user.totp_last_step = None
    await db.commit()
    uri = pyotp.TOTP(secret).provisioning_uri(name=cur.user.email, issuer_name="SUNSCRYPT")
    return {"secret": secret, "otpauth_uri": uri}


@router.post("/2fa/enable")
async def enable_2fa(body: CodeIn, cur: CurrentUser, request: Request, db: Db) -> dict:
    await enforce(f"2fa:user:{cur.user.id}", 8, 900)
    if cur.user.totp_enabled_at:
        raise HTTPException(409, "2FA уже включена")
    if not check_totp(cur.user, body.code):
        await db.commit()
        raise HTTPException(400, "Неверный код — проверьте время на телефоне и попробуйте снова")
    cur.user.totp_enabled_at = _now()
    cur.session.mfa_passed = True
    # Остальные сессии этого пользователя должны пройти 2FA заново.
    await db.execute(
        update(Session)
        .where(Session.user_id == cur.user.id, Session.token_hash != cur.session.token_hash)
        .values(mfa_passed=False)
    )
    await _log(
        db, request, email=cur.user.email, event="2fa_enabled", success=True, user_id=cur.user.id
    )
    await db.commit()
    return {"ok": True}


# ── Сброс пароля ────────────────────────────────────────────────────────────
@router.post("/password/forgot")
async def forgot(body: EmailIn, request: Request, db: Db) -> dict:
    email = _norm(body.email)
    await enforce(f"forgot:ip:{_ip(request)}", 10, 3600)
    await enforce(f"forgot:email:{email}", 3, 3600)
    user = await db.scalar(select(User).where(User.email == email))
    if user:
        link = await _email_link(db, user, "reset", RESET_TTL)
        await mailer.send(
            db,
            user.email,
            "SUNSCRYPT: сброс пароля",
            f"Чтобы задать новый пароль, откройте ссылку (действует 1 час):\n{link}\n\n"
            "Если вы не просили сброс — ничего не делайте, пароль останется прежним.",
        )
        await _log(db, request, email=email, event="reset_requested", success=True, user_id=user.id)
        await db.commit()
    return {"ok": True, "message": "Если такая почта есть, мы отправили на неё ссылку."}


@router.post("/password/reset")
async def reset(body: ResetIn, request: Request, db: Db) -> dict:
    await enforce(f"reset:ip:{_ip(request)}", 10, 3600)
    row = await _take_token(db, body.token, "reset")
    user = await db.get(User, row.user_id)
    if user is None:
        raise HTTPException(400, "Ссылка недействительна")
    user.password_hash = _ph.hash(body.password)
    # Ссылка пришла на почту — значит, почта подтверждена.
    user.email_verified_at = user.email_verified_at or _now()
    await db.execute(delete(Session).where(Session.user_id == user.id))
    await _log(db, request, email=user.email, event="password_reset", success=True, user_id=user.id)
    await db.commit()
    return {"ok": True}
