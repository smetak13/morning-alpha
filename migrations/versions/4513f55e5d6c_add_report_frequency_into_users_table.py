"""add report_frequency into users table

Revision ID: 4513f55e5d6c
Revises: 05dadd787ff5
Create Date: 2026-07-04 08:32:15.843361
"""

from __future__ import annotations

from alembic import op


revision = '4513f55e5d6c'
down_revision = '05dadd787ff5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        alter table public.users
        add column report_frequency text not null default 'daily';

        alter table public.users
        add constraint users_report_frequency_check
        check (report_frequency in ('daily', 'weekly', 'monthly'));
        """
    )


def downgrade() -> None:
    op.execute(
        """
        alter table public.users
        drop constraint if exists users_report_frequency_check;

        alter table public.users
        drop column if exists report_frequency;
        """
    )
