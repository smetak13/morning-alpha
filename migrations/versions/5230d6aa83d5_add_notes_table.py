"""add notes table

Revision ID: 5230d6aa83d5
Revises: f2174994135f
Create Date: 2026-06-09 11:28:42.134267
"""

from __future__ import annotations

from alembic import op


revision = '5230d6aa83d5'
down_revision = 'f2174994135f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        create function public.notes_set_updated_at()
        returns trigger
        language plpgsql
        as $$
        begin
            new.updated_at = now();
            return new;
        end;
        $$;

        create table public.notes (
            id uuid primary key default gen_random_uuid(),
            user_id uuid not null references public.users(id) on delete cascade,
            stock_id uuid not null references public.stocks(id) on delete restrict,
            report_id uuid references public.reports(id) on delete cascade,
            body text not null,
            is_resolved boolean not null default false,
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now()
        );

        create trigger notes_set_updated_at
        before update on public.notes
        for each row
        execute function public.notes_set_updated_at();

        create index notes_user_id_created_at_idx
        on public.notes (user_id, created_at desc);

        create index notes_user_id_stock_id_created_at_idx
        on public.notes (user_id, stock_id, created_at desc);

        create index notes_user_id_report_id_created_at_idx
        on public.notes (user_id, report_id, created_at desc);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        drop trigger if exists notes_set_updated_at on public.notes;
        drop table if exists public.notes;
        drop function if exists public.notes_set_updated_at();
        """
    )
