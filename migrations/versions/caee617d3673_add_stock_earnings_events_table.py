"""add stock_earnings_events table

Revision ID: caee617d3673
Revises: d2e9287ccb16
Create Date: 2026-07-09 11:09:00.524586
"""

from __future__ import annotations

from alembic import op


revision = 'caee617d3673'
down_revision = 'd2e9287ccb16'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        create table public.stock_earnings_events (
            id uuid primary key default gen_random_uuid(),
            stock_id uuid not null references public.stocks(id) on delete cascade,
            symbol text not null,
            event_date date not null,
            report_time text,
            fiscal_quarter text,
            fiscal_year text,
            source text not null default 'fmp',
            raw jsonb not null default '{}'::jsonb,
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now()
        );

        create unique index stock_earnings_events_stock_date_key
        on public.stock_earnings_events (stock_id, event_date);

        create index stock_earnings_events_event_date_idx
        on public.stock_earnings_events (event_date);

        create index stock_earnings_events_symbol_event_date_idx
        on public.stock_earnings_events (symbol, event_date);
        """
    )


def downgrade() -> None:
    op.execute("drop table if exists public.stock_earnings_events;")
