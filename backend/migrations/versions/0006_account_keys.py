"""Два ключа у кабинета: демо и реальный (этап 5). Ключи — в account_keys,
у кабинета остаётся активный счёт.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MOVED = (
    "api_key_enc",
    "api_secret_enc",
    "key_tail",
    "permissions",
    "ips",
    "warnings",
    "status_detail",
    "checked_at",
)


def upgrade() -> None:
    op.create_table(
        "account_keys",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "account_id",
            sa.Uuid(),
            sa.ForeignKey("exchange_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
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
        sa.Column("checked_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("account_id", "mode"),
    )
    op.create_index("ix_account_keys_account_id", "account_keys", ["account_id"])
    op.execute(
        "INSERT INTO account_keys (id, account_id, mode, api_key_enc, api_secret_enc, key_tail, "
        "permissions, ips, warnings, status, status_detail, equity_usd, checked_at, created_at) "
        "SELECT gen_random_uuid(), id, mode, api_key_enc, api_secret_enc, key_tail, permissions, "
        "ips, warnings, status, status_detail, equity_usd, checked_at, created_at "
        "FROM exchange_accounts"
    )
    for c in MOVED:
        op.drop_column("exchange_accounts", c)
    # Сделки и баланс — с отметкой счёта: статистика демо и реального раздельно.
    op.add_column("trades", sa.Column("mode", sa.String(8), server_default="demo", nullable=False))
    op.add_column(
        "equity_snapshots", sa.Column("mode", sa.String(8), server_default="demo", nullable=False)
    )
    op.drop_constraint("equity_snapshots_pkey", "equity_snapshots", type_="primary")
    op.create_primary_key("equity_snapshots_pkey", "equity_snapshots", ["account_id", "mode", "ts"])
    op.alter_column("equity_snapshots", "mode", server_default=None)


def downgrade() -> None:
    op.drop_constraint("equity_snapshots_pkey", "equity_snapshots", type_="primary")
    op.execute("DELETE FROM equity_snapshots WHERE mode <> 'demo'")
    op.create_primary_key("equity_snapshots_pkey", "equity_snapshots", ["account_id", "ts"])
    op.drop_column("equity_snapshots", "mode")
    op.drop_column("trades", "mode")
    acc = "exchange_accounts"
    op.add_column(acc, sa.Column("api_key_enc", sa.LargeBinary()))
    op.add_column(acc, sa.Column("api_secret_enc", sa.LargeBinary()))
    op.add_column(acc, sa.Column("key_tail", sa.String(4)))
    op.add_column(acc, sa.Column("permissions", sa.JSON()))
    op.add_column(acc, sa.Column("ips", sa.JSON()))
    op.add_column(acc, sa.Column("warnings", sa.JSON()))
    op.add_column(acc, sa.Column("status_detail", sa.String(255)))
    op.add_column(acc, sa.Column("checked_at", sa.DateTime(timezone=True)))
    op.execute(
        "UPDATE exchange_accounts a SET api_key_enc = k.api_key_enc, "
        "api_secret_enc = k.api_secret_enc, key_tail = k.key_tail, permissions = k.permissions, "
        "ips = k.ips, warnings = k.warnings, status_detail = k.status_detail, "
        "checked_at = k.checked_at FROM account_keys k "
        "WHERE k.account_id = a.id AND k.mode = a.mode"
    )
    op.execute("DELETE FROM exchange_accounts WHERE api_key_enc IS NULL")
    for c in ("api_key_enc", "api_secret_enc", "key_tail", "permissions", "ips", "warnings"):
        op.alter_column(acc, c, nullable=False)
    op.drop_table("account_keys")
