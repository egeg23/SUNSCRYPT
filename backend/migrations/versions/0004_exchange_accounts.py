"""Кабинеты Bybit: ключи шифрованно, права и IP — для показа и проверки.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "exchange_accounts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("name", sa.String(60), nullable=False),
        sa.Column("mode", sa.String(8), nullable=False),
        sa.Column("api_key_enc", sa.LargeBinary(), nullable=False),
        sa.Column("api_secret_enc", sa.LargeBinary(), nullable=False),
        sa.Column("key_tail", sa.String(4), nullable=False),
        sa.Column("permissions", sa.JSON(), nullable=False),
        sa.Column("ips", sa.JSON(), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("status_detail", sa.String(255)),
        sa.Column("equity_usd", sa.Float()),
        sa.Column("stopped", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_exchange_accounts_user_id", "exchange_accounts", ["user_id"])


def downgrade() -> None:
    op.drop_table("exchange_accounts")
