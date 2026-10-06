import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
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


class ExchangeAccount(Base):
    """Кабинет Bybit пользователя. Ключ и секрет — только шифрованно
    (AES-GCM, мастер-ключ); в интерфейс не возвращаются — видны лишь
    последние 4 символа ключа."""

    __tablename__ = "exchange_accounts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(60))
    mode: Mapped[str] = mapped_column(String(8))  # demo | real
    api_key_enc: Mapped[bytes] = mapped_column(LargeBinary)
    api_secret_enc: Mapped[bytes] = mapped_column(LargeBinary)
    key_tail: Mapped[str] = mapped_column(String(4))
    permissions: Mapped[dict] = mapped_column(JSON, default=dict)
    ips: Mapped[list] = mapped_column(JSON, default=list)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), default="ok")  # ok | error
    status_detail: Mapped[str | None] = mapped_column(String(255))
    equity_usd: Mapped[float | None] = mapped_column(Float)
    # Аварийная остановка кабинета (бриф, правило 4); используется движком.
    stopped: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Торговля: включает пользователь; по умолчанию выключена.
    trading_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    leverage: Mapped[float] = mapped_column(Float, default=1.0, server_default="1")
    # Капитал под стратегию, USD; пусто — min(баланс, 1000).
    capital_usd: Mapped[float | None] = mapped_column(Float)
    daily_loss_pct: Mapped[float] = mapped_column(Float, default=5.0, server_default="5")
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now_col()


class Trade(Base):
    """Журнал исполнений кабинета: от движка и из сверки с Bybit."""

    __tablename__ = "trades"
    __table_args__ = (UniqueConstraint("account_id", "trade_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exchange_accounts.id", ondelete="CASCADE"), index=True
    )
    trade_id: Mapped[str] = mapped_column(String(80))  # execId Bybit
    order_id: Mapped[str | None] = mapped_column(String(80))
    sym: Mapped[str] = mapped_column(String(20))
    side: Mapped[str] = mapped_column(String(4))
    qty: Mapped[float] = mapped_column(Float)
    price: Mapped[float] = mapped_column(Float)
    fee: Mapped[float] = mapped_column(Float, default=0)
    fee_ccy: Mapped[str | None] = mapped_column(String(10))
    liquidity: Mapped[str | None] = mapped_column(String(10))
    source: Mapped[str] = mapped_column(String(10), default="engine")  # engine | reconcile
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class EquitySnapshot(Base):
    __tablename__ = "equity_snapshots"

    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exchange_accounts.id", ondelete="CASCADE"), primary_key=True
    )
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    equity_usd: Mapped[float] = mapped_column(Float)


class EngineEvent(Base):
    """Журнал движка: запуски, остановки, сбои, сверки."""

    __tablename__ = "engine_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("exchange_accounts.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(32))
    message: Mapped[str] = mapped_column(String(500))
    ts: Mapped[datetime] = _now_col(index=True)
