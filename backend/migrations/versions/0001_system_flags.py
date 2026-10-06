"""Глобальные выключатели: реальная торговля (выкл.) и аварийная остановка.

Revision ID: 0001
Revises:
Create Date: 2026-10-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    flags = op.create_table(
        "system_flags",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("value", sa.Boolean(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    # Бриф, правило 1: реальные ордера — только после явного решения
    # владельца. Стартуем с выключенной реальной торговлей.
    op.bulk_insert(
        flags,
        [
            {"key": "real_trading_enabled", "value": False},
            {"key": "global_stop", "value": False},
        ],
    )


def downgrade() -> None:
    op.drop_table("system_flags")
