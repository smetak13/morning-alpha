"""add portfolio_items table

Revision ID: 7e22fc432d2b
Revises: 8dd656d24d5a
Create Date: 2026-06-04 22:32:50.468898
"""

from __future__ import annotations

from alembic import op


revision = '7e22fc432d2b'
down_revision = '8dd656d24d5a'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        create function public.portfolio_items_set_updated_at()
        returns trigger
        language plpgsql
        as $$
        begin
            new.updated_at = now();
            return new;
        end;
        $$;

        create table public.portfolio_items (
            id uuid primary key default gen_random_uuid(),
            user_id uuid not null references public.users(id) on delete cascade,
            stock_id uuid not null references public.stocks(id) on delete restrict,
            position_size_pct double precision,
            why_i_own_it text[] not null default '{}',
            bull_case text[] not null default '{}',
            bear_case text[] not null default '{}',
            key_metrics text[] not null default '{}',
            red_flags text[] not null default '{}',
            action_triggers text[] not null default '{}',
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now(),
            unique (user_id, stock_id)
        );

        create trigger portfolio_items_set_updated_at
        before update on public.portfolio_items
        for each row
        execute function public.portfolio_items_set_updated_at();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        drop trigger if exists portfolio_items_set_updated_at on public.portfolio_items;
        drop table if exists public.portfolio_items;
        drop function if exists public.portfolio_items_set_updated_at();
        """
    )
