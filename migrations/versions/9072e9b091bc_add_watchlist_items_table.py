"""add watchlist_items table

Revision ID: 9072e9b091bc
Revises: 7e22fc432d2b
Create Date: 2026-06-05 14:33:29.027841
"""

from __future__ import annotations

from alembic import op


revision = '9072e9b091bc'
down_revision = '7e22fc432d2b'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        create function public.watchlist_items_set_updated_at()
        returns trigger
        language plpgsql
        as $$
        begin
            new.updated_at = now();
            return new;
        end;
        $$;

        create table public.watchlist_items (
            id uuid primary key default gen_random_uuid(),
            user_id uuid not null references public.users(id) on delete cascade,
            stock_id uuid not null references public.stocks(id) on delete restrict,
            why_i_watch_it text[] not null default '{}',
            bull_case text[] not null default '{}',
            bear_case text[] not null default '{}',
            key_metrics text[] not null default '{}',
            red_flags text[] not null default '{}',
            action_triggers text[] not null default '{}',
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now(),
            unique (user_id, stock_id)
        );

        create trigger watchlist_items_set_updated_at
        before update on public.watchlist_items
        for each row
        execute function public.watchlist_items_set_updated_at();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        drop trigger if exists watchlist_items_set_updated_at on public.watchlist_items;
        drop table if exists public.watchlist_items;
        drop function if exists public.watchlist_items_set_updated_at();
        """
    )
