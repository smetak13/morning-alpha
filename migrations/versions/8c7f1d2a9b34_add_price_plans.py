"""add price plans

Revision ID: 8c7f1d2a9b34
Revises: caee617d3673
Create Date: 2026-07-17 12:00:00.000000
"""

from __future__ import annotations

from alembic import op


revision = '8c7f1d2a9b34'
down_revision = 'caee617d3673'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        create table public.price_plans (
            id uuid primary key default gen_random_uuid(),
            user_id uuid not null references public.users(id) on delete cascade,
            stock_id uuid not null references public.stocks(id) on delete restrict,
            target_price numeric(18, 4) not null,
            currency text not null default 'USD',
            direction text not null,
            note text,
            status text not null default 'active',
            reference_price numeric(18, 4) not null,
            reference_price_source text not null,
            reference_price_at timestamptz,
            reference_checked_at timestamptz not null default now(),
            last_checked_price numeric(18, 4),
            last_checked_price_source text,
            last_checked_price_at timestamptz,
            last_checked_at timestamptz,
            triggered_price numeric(18, 4),
            triggered_price_source text,
            triggered_price_at timestamptz,
            triggered_at timestamptz,
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now(),
            constraint price_plans_target_price_check check (target_price > 0),
            constraint price_plans_currency_check check (length(trim(currency)) between 1 and 8),
            constraint price_plans_direction_check check (direction in ('above', 'below')),
            constraint price_plans_status_check check (status in ('active', 'triggered')),
            constraint price_plans_reference_source_check check (reference_price_source in ('1min', '5min', '15min')),
            constraint price_plans_last_checked_source_check check (
                last_checked_price_source is null or last_checked_price_source in ('1min', '5min', '15min')
            ),
            constraint price_plans_triggered_source_check check (
                triggered_price_source is null or triggered_price_source in ('1min', '5min', '15min')
            ),
            constraint price_plans_triggered_fields_check check (
                (status = 'active' and triggered_at is null)
                or
                (status = 'triggered' and triggered_at is not null)
            )
        );

        create function public.price_plans_set_updated_at()
        returns trigger
        language plpgsql
        as $$
        begin
            new.updated_at = now();
            return new;
        end;
        $$;

        create trigger price_plans_set_updated_at
        before update on public.price_plans
        for each row
        execute function public.price_plans_set_updated_at();

        create unique index price_plans_active_target_key
        on public.price_plans (user_id, stock_id, currency, target_price)
        where status = 'active';

        create index price_plans_active_stock_idx
        on public.price_plans (stock_id)
        where status = 'active';

        create index price_plans_user_stock_status_idx
        on public.price_plans (user_id, stock_id, status, created_at desc);

        alter table public.notifications
        drop constraint if exists notifications_type_check;

        alter table public.notifications
        add constraint notifications_type_check
            check (type in ('earnings_call_reminder', 'product_announcement', 'news', 'weekly_research_lead', 'price_plan_triggered'));
        """
    )


def downgrade() -> None:
    op.execute(
        """
        alter table public.notifications
        drop constraint if exists notifications_type_check;

        alter table public.notifications
        add constraint notifications_type_check
            check (type in ('earnings_call_reminder', 'product_announcement', 'news', 'weekly_research_lead'));

        drop trigger if exists price_plans_set_updated_at on public.price_plans;
        drop function if exists public.price_plans_set_updated_at();
        drop table if exists public.price_plans;
        """
    )
