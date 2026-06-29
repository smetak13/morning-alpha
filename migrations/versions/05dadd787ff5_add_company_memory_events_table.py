"""add company_memory_events table

Revision ID: 05dadd787ff5
Revises: b81014c2a852
Create Date: 2026-06-27 00:57:43.069087
"""

from __future__ import annotations

from alembic import op


revision = '05dadd787ff5'
down_revision = 'b81014c2a852'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        create table public.company_memory_events (
            id uuid primary key default gen_random_uuid(),
            company_memory_item_id uuid not null references public.company_memory_items(id) on delete cascade,
            user_id uuid not null references public.users(id) on delete cascade,
            stock_id uuid not null references public.stocks(id) on delete restrict,
            report_id uuid references public.reports(id) on delete set null,
            event_key text not null,
            event_date date not null,
            event_type text not null,
            relationship text,
            headline text,
            summary text not null,
            source_url text,
            source text,
            importance text not null default 'medium',
            thesis_points jsonb not null default '[]'::jsonb,
            metadata jsonb not null default '{}'::jsonb,
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now(),
            constraint company_memory_events_event_type_check
                check (event_type in ('created', 'updated')),
            constraint company_memory_events_importance_check
                check (importance in ('medium', 'high')),
            constraint company_memory_events_event_key_not_blank_check
                check (length(trim(event_key)) > 0),
            unique (company_memory_item_id, event_key)
        );

        create index company_memory_events_item_date_idx
        on public.company_memory_events (company_memory_item_id, event_date desc, created_at desc);

        create index company_memory_events_user_stock_date_idx
        on public.company_memory_events (user_id, stock_id, event_date desc, created_at desc);

        create index company_memory_events_report_id_idx
        on public.company_memory_events (report_id);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        drop index if exists public.company_memory_events_report_id_idx;
        drop index if exists public.company_memory_events_user_stock_date_idx;
        drop index if exists public.company_memory_events_item_date_idx;
        drop table if exists public.company_memory_events;
        """
    )
