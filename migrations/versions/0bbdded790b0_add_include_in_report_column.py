"""add include_in_report column

Revision ID: 0bbdded790b0
Revises: c2fcdcdb5746
Create Date: 2026-06-08 22:13:18.628757
"""

from __future__ import annotations

from alembic import op


revision = '0bbdded790b0'
down_revision = 'c2fcdcdb5746'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        alter table public.portfolio_items
        add column include_in_report boolean not null default true;

        alter table public.watchlist_items
        add column include_in_report boolean not null default true;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        alter table public.watchlist_items
        drop column if exists include_in_report;

        alter table public.portfolio_items
        drop column if exists include_in_report;
        """
    )
