"""add report_scheduled_at column

Revision ID: c2fcdcdb5746
Revises: 9072e9b091bc
Create Date: 2026-06-08 16:20:16.434696
"""

from __future__ import annotations

from alembic import op


revision = 'c2fcdcdb5746'
down_revision = '9072e9b091bc'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        alter table public.users
        add column report_scheduled_at time without time zone not null default time '08:00';

        alter table public.users
        drop column if exists onboarding_completed_at;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        alter table public.users
        add column onboarding_completed_at timestamptz;

        alter table public.users
        drop column if exists report_scheduled_at;
        """
    )
