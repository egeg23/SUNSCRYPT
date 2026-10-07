"""Баланс стратегии — только USDT счёта (app/bybit.usdt_equity).

Прежние снимки считались по всему счёту (с BTC, ETH, USDC по курсу) — в
одном графике с новыми они дали бы ложный обвал. Это история первых часов
демо-обкатки; сделки и сверка не затронуты.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-07
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DELETE FROM equity_snapshots")


def downgrade() -> None:
    pass
