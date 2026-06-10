"""add research_items table

Revision ID: af2a4b9986b3
Revises: 5230d6aa83d5
Create Date: 2026-06-10 18:47:40.699225
"""

from __future__ import annotations

from alembic import op


revision = 'af2a4b9986b3'
down_revision = '5230d6aa83d5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        create table public.research_items (
            id uuid primary key default gen_random_uuid(),
            user_id uuid not null references public.users(id) on delete cascade,
            stock_id uuid not null references public.stocks(id) on delete restrict,
            body jsonb not null,
            research_type text not null,
            signal text,
            date_from date,
            date_to date,
            created_at timestamptz not null default now(),
            constraint research_items_research_type_check
                check (research_type in ('portfolio_check', 'watchlist_check', 'company_primer'))
        );

        create index research_items_user_id_created_at_idx
        on public.research_items (user_id, created_at desc);

        create index research_items_user_id_stock_id_created_at_idx
        on public.research_items (user_id, stock_id, created_at desc);

        create index research_items_user_id_research_type_created_at_idx
        on public.research_items (user_id, research_type, created_at desc);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        drop table if exists public.research_items;
        """
    )
