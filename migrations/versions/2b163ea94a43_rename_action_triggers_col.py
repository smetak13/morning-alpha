"""rename action_triggers col

Revision ID: 2b163ea94a43
Revises: cb5122291e7d
Create Date: 2026-06-09 08:48:32.583211
"""

from __future__ import annotations

from alembic import op


revision = '2b163ea94a43'
down_revision = 'cb5122291e7d'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        alter table public.watchlist_items
        rename column action_triggers to entry_conditions;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        alter table public.watchlist_items
        rename column entry_conditions to action_triggers;
        """
    )
