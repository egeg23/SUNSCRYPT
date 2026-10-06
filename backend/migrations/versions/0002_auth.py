"""Пользователи, сессии, ссылки из писем, журнал входов, исходящие письма.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _created():
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("email_verified_at", sa.DateTime(timezone=True)),
        sa.Column("totp_secret_enc", sa.LargeBinary()),
        sa.Column("totp_enabled_at", sa.DateTime(timezone=True)),
        sa.Column("totp_last_step", sa.BigInteger()),
        sa.Column("is_admin", sa.Boolean(), server_default="false", nullable=False),
        _created(),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "sessions",
        sa.Column("token_hash", sa.LargeBinary(32), primary_key=True),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("mfa_passed", sa.Boolean(), nullable=False),
        sa.Column("ip", sa.String(64)),
        sa.Column("user_agent", sa.String(255)),
        _created(),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])

    op.create_table(
        "email_tokens",
        sa.Column("token_hash", sa.LargeBinary(32), primary_key=True),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("purpose", sa.String(16), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        _created(),
    )

    op.create_table(
        "login_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("event", sa.String(32), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.String(64)),
        sa.Column("ip", sa.String(64)),
        sa.Column("user_agent", sa.String(255)),
        _created(),
    )
    op.create_index("ix_login_events_user_id", "login_events", ["user_id"])
    op.create_index("ix_login_events_created_at", "login_events", ["created_at"])

    op.create_table(
        "outbox_emails",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("to", sa.String(254), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("error", sa.String(255)),
        _created(),
    )


def downgrade() -> None:
    for t in ("outbox_emails", "login_events", "email_tokens", "sessions", "users"):
        op.drop_table(t)
