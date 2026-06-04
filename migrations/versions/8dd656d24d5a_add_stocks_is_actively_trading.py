"""add stocks.is_actively_trading

Revision ID: 8dd656d24d5a
Revises: e1da450ab6ba
Create Date: 2026-06-04 17:40:51.731448
"""

from __future__ import annotations

from alembic import op


revision = '8dd656d24d5a'
down_revision = 'e1da450ab6ba'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        alter table public.stocks
        add column is_actively_trading boolean not null default true;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        alter table public.stocks
        drop column if exists is_actively_trading;
        """
    )
