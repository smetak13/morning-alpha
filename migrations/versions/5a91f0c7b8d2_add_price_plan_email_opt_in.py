"""add price plan email opt in

Revision ID: 5a91f0c7b8d2
Revises: 3f9a6b2c1d0e
Create Date: 2026-07-20 00:00:00.000000
"""

from __future__ import annotations

from alembic import op


revision = '5a91f0c7b8d2'
down_revision = '3f9a6b2c1d0e'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        alter table public.price_plans
        add column email_on_trigger boolean not null default false;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        alter table public.price_plans
        drop column if exists email_on_trigger;
        """
    )
