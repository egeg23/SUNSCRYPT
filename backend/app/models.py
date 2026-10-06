import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    LargeBinary,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _now_col(**kw):
    return mapped_column(DateTime(timezone=True), server_default=func.now(), **kw)


class SystemFlag(Base):
    """Глобальные выключатели. real_trading_enabled — реальная торговля
    (по умолчанию выключена), global_stop — аварийная остановка всех
    кабинетов."""

    __tablename__ = "system_flags"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[bool] = mapped_column(Boolean, nullable=False)
    updated_at: Mapped[datetime] = _now_col(onupdate=func.now())


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Секрет TOTP — только шифрованно (AES-GCM, мастер-ключ). Пока 2FA не
    # подтверждена кодом, totp_enabled_at пуст.
    totp_secret_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    totp_enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Последний принятый шаг TOTP: один код нельзя использовать дважды.
    totp_last_step: Mapped[int | None] = mapped_column(BigInteger)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = _now_col()


class Session(Base):
    """Сессия входа. В cookie — случайный токен, в базе — только его хеш."""

    __tablename__ = "sessions"

    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    mfa_passed: Mapped[bool] = mapped_column(Boolean, default=False)
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = _now_col()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class EmailToken(Base):
    """Ссылки из писем: подтверждение почты и сброс пароля."""

    __tablename__ = "email_tokens"

    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    purpose: Mapped[str] = mapped_column(String(16))  # verify | reset
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now_col()


class LoginEvent(Base):
    """Журнал входов: и удачных, и нет."""

    __tablename__ = "login_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    email: Mapped[str] = mapped_column(String(254))
    event: Mapped[str] = mapped_column(String(32))  # login, 2fa, logout, reset…
    success: Mapped[bool] = mapped_column(Boolean)
    reason: Mapped[str | None] = mapped_column(String(64))
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = _now_col(index=True)


class OutboxEmail(Base):
    """Исходящие письма. Отправляются по SMTP, если он настроен; иначе
    остаются здесь (и в тестах читаются отсюда)."""

    __tablename__ = "outbox_emails"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    to: Mapped[str] = mapped_column(String(254))
    subject: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = _now_col()


class Invite(Base):
    """Приглашение: доступ закрытый, аккаунт создаётся только по ссылке,
    которую выдаёт владелец (позже — через Telegram-бота)."""

    __tablename__ = "invites"

    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32), primary_key=True)
    note: Mapped[str | None] = mapped_column(String(120))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    used_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = _now_col()
