"""Движок: настройки торговли кабинета, журнал сделок, снимки баланса,
события движка.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACC = "exchange_accounts"


def upgrade() -> None:
    op.add_column(
        ACC, sa.Column("trading_enabled", sa.Boolean(), server_default="false", nullable=False)
    )
    op.add_column(ACC, sa.Column("leverage", sa.Float(), server_default="1", nullable=False))
    op.add_column(ACC, sa.Column("capital_usd", sa.Float()))
    op.add_column(ACC, sa.Column("daily_loss_pct", sa.Float(), server_default="5", nullable=False))

    def fk():
        return sa.ForeignKey("exchange_accounts.id", ondelete="CASCADE")

    op.create_table(
        "trades",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.Uuid(), fk(), nullable=False),
        sa.Column("trade_id", sa.String(80), nullable=False),
        sa.Column("order_id", sa.String(80)),
        sa.Column("sym", sa.String(20), nullable=False),
        sa.Column("side", sa.String(4), nullable=False),
        sa.Column("qty", sa.Float(), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("fee", sa.Float(), nullable=False),
        sa.Column("fee_ccy", sa.String(10)),
        sa.Column("liquidity", sa.String(10)),
        sa.Column("source", sa.String(10), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("account_id", "trade_id"),
    )
    op.create_index("ix_trades_account_id", "trades", ["account_id"])
    op.create_index("ix_trades_ts", "trades", ["ts"])
    op.create_table(
        "equity_snapshots",
        sa.Column("account_id", sa.Uuid(), fk(), primary_key=True),
        sa.Column("ts", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("equity_usd", sa.Float(), nullable=False),
    )
    op.create_table(
        "engine_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("account_id", sa.Uuid(), fk()),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("message", sa.String(500), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_engine_events_account_id", "engine_events", ["account_id"])
    op.create_index("ix_engine_events_ts", "engine_events", ["ts"])


def downgrade() -> None:
    for t in ("engine_events", "equity_snapshots", "trades"):
        op.drop_table(t)
    for c in ("daily_loss_pct", "capital_usd", "leverage", "trading_enabled"):
        op.drop_column(ACC, c)
