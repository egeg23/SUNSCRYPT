"""Фандинг (этап 6): учитывается в статистике отдельно от комиссий.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "funding",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "account_id",
            sa.Uuid(),
            sa.ForeignKey("exchange_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("mode", sa.String(8), nullable=False),
        sa.Column("exec_id", sa.String(80), nullable=False),
        sa.Column("sym", sa.String(20), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("account_id", "exec_id"),
    )
    op.create_index("ix_funding_account_id", "funding", ["account_id"])


def downgrade() -> None:
    op.drop_table("funding")
