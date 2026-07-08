"""add report_runs table

Revision ID: 0266b82d11f9
Revises: f325d7acdc37
Create Date: 2026-07-08 21:06:56.138693
"""

from __future__ import annotations

from alembic import op


revision = '0266b82d11f9'
down_revision = 'f325d7acdc37'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        create table public.report_runs (
            id uuid primary key default gen_random_uuid(),
            user_id uuid not null references public.users(id) on delete cascade,
            report_id uuid references public.reports(id) on delete set null,
            usage_id uuid references public.usages(id) on delete set null,
            recipient_email text not null,
            timezone text not null default 'Europe/Prague',
            report_scheduled_at time without time zone not null,
            report_frequency text not null default 'daily',
            scheduled_for timestamptz not null,
            date_arg text not null default 'latest',
            status text not null default 'queued',
            progress_step text,
            progress_pct integer not null default 0,
            request jsonb not null default '{}'::jsonb,
            result jsonb not null default '{}'::jsonb,
            usage jsonb not null default '{}'::jsonb,
            error text,
            created_at timestamptz not null default now(),
            started_at timestamptz,
            completed_at timestamptz,
            updated_at timestamptz not null default now(),
            constraint report_runs_report_frequency_check
                check (report_frequency in ('daily', 'weekly', 'monthly')),
            constraint report_runs_status_check
                check (status in ('queued', 'running', 'completed', 'failed', 'cancelled')),
            constraint report_runs_progress_pct_check
                check (progress_pct >= 0 and progress_pct <= 100)
        );

        create unique index report_runs_user_scheduled_frequency_key
        on public.report_runs (user_id, scheduled_for, report_frequency);

        create index report_runs_status_scheduled_for_idx
        on public.report_runs (status, scheduled_for, created_at);

        create index report_runs_user_id_created_at_idx
        on public.report_runs (user_id, created_at desc);
        """
    )


def downgrade() -> None:
    op.execute("drop table if exists public.report_runs;")
