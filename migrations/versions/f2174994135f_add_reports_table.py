"""add reports table

Revision ID: f2174994135f
Revises: 2b163ea94a43
Create Date: 2026-06-09 09:24:18.974624
"""

from __future__ import annotations

from alembic import op


revision = 'f2174994135f'
down_revision = '2b163ea94a43'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        create table public.reports (
            id uuid primary key default gen_random_uuid(),
            user_id uuid not null references public.users(id) on delete cascade,
            usage_id uuid references public.usages(id) on delete set null,
            html text not null,
            report_date date not null,
            created_at timestamptz not null default now()
        );

        create index reports_user_id_report_date_idx
        on public.reports (user_id, report_date desc, created_at desc);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        drop table if exists public.reports;
        """
    )
