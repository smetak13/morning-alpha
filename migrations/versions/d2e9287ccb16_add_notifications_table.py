"""add notifications table

Revision ID: d2e9287ccb16
Revises: 0266b82d11f9
Create Date: 2026-07-09 11:08:44.337039
"""

from __future__ import annotations

from alembic import op


revision = 'd2e9287ccb16'
down_revision = '0266b82d11f9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        create table public.notifications (
            id uuid primary key default gen_random_uuid(),
            user_id uuid not null references public.users(id) on delete cascade,
            type text not null,
            title text not null,
            body text,
            target_url text,
            stock_id uuid references public.stocks(id) on delete restrict,
            portfolio_item_id uuid references public.portfolio_items(id) on delete cascade,
            watchlist_item_id uuid references public.watchlist_items(id) on delete cascade,
            event_date date,
            reminder_kind text,
            read_at timestamptz,
            expires_at timestamptz,
            metadata jsonb not null default '{}'::jsonb,
            created_at timestamptz not null default now(),
            constraint notifications_type_check
                check (type in ('earnings_call_reminder', 'product_announcement', 'news')),
            constraint notifications_reminder_kind_check
                check (reminder_kind is null or reminder_kind in ('7d', '1d')),
            constraint notifications_one_relationship_check
                check (
                    portfolio_item_id is null
                    or watchlist_item_id is null
                )
        );

        create unique index notifications_earnings_reminder_key
        on public.notifications (user_id, type, stock_id, event_date, reminder_kind)
        where type = 'earnings_call_reminder'
          and stock_id is not null
          and event_date is not null
          and reminder_kind is not null;

        create index notifications_user_created_at_idx
        on public.notifications (user_id, created_at desc);

        create index notifications_user_unread_idx
        on public.notifications (user_id, created_at desc)
        where read_at is null;
        """
    )


def downgrade() -> None:
    op.execute("drop table if exists public.notifications;")
