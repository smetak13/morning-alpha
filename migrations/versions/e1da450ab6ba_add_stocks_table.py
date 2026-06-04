"""add stocks table

Revision ID: e1da450ab6ba
Revises: 294bbf59c16a
Create Date: 2026-06-04 17:28:37.453283
"""

from __future__ import annotations

from alembic import op


revision = 'e1da450ab6ba'
down_revision = '294bbf59c16a'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        create function public.stocks_set_updated_at()
        returns trigger
        language plpgsql
        as $$
        begin
            new.updated_at = now();
            return new;
        end;
        $$;

        create table public.stocks (
            id uuid primary key default gen_random_uuid(),
            symbol text not null unique,
            company_name text not null,
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now()
        );

        create trigger stocks_set_updated_at
        before update on public.stocks
        for each row
        execute function public.stocks_set_updated_at();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        drop trigger if exists stocks_set_updated_at on public.stocks;
        drop table if exists public.stocks;
        drop function if exists public.stocks_set_updated_at();
        """
    )
