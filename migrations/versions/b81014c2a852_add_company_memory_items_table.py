"""add company_memory_items table

Revision ID: b81014c2a852
Revises: c4ef05031f14
Create Date: 2026-06-26 23:34:17.347568
"""

from __future__ import annotations

from alembic import op


revision = 'b81014c2a852'
down_revision = 'c4ef05031f14'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        create function public.company_memory_items_set_updated_at()
        returns trigger
        language plpgsql
        as $$
        begin
            new.updated_at = now();
            return new;
        end;
        $$;

        create table public.company_memory_items (
            id uuid primary key default gen_random_uuid(),
            user_id uuid not null references public.users(id) on delete cascade,
            stock_id uuid not null references public.stocks(id) on delete restrict,
            last_report_id uuid references public.reports(id) on delete set null,
            theme text not null,
            normalized_theme text not null,
            description text not null,
            latest_development text,
            thesis_points jsonb not null default '[]'::jsonb,
            thesis_linked boolean not null default false,
            keywords jsonb not null default '[]'::jsonb,
            source_urls jsonb not null default '[]'::jsonb,
            last_source_url text,
            importance text not null default 'medium',
            status text not null default 'active',
            evidence_count integer not null default 1,
            first_seen_at date not null,
            last_seen_at date not null,
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now(),
            constraint company_memory_items_importance_check
                check (importance in ('medium', 'high')),
            constraint company_memory_items_status_check
                check (status in ('active', 'stale', 'resolved')),
            constraint company_memory_items_evidence_count_check
                check (evidence_count >= 1),
            constraint company_memory_items_theme_not_blank_check
                check (length(trim(theme)) > 0 and length(trim(normalized_theme)) > 0),
            unique (user_id, stock_id, normalized_theme)
        );

        create trigger company_memory_items_set_updated_at
        before update on public.company_memory_items
        for each row
        execute function public.company_memory_items_set_updated_at();

        create index company_memory_items_user_stock_status_seen_idx
        on public.company_memory_items (user_id, stock_id, status, last_seen_at desc);

        create index company_memory_items_user_stock_importance_seen_idx
        on public.company_memory_items (user_id, stock_id, importance, last_seen_at desc);

        create index company_memory_items_last_report_id_idx
        on public.company_memory_items (last_report_id);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        drop index if exists public.company_memory_items_last_report_id_idx;
        drop index if exists public.company_memory_items_user_stock_importance_seen_idx;
        drop index if exists public.company_memory_items_user_stock_status_seen_idx;
        drop trigger if exists company_memory_items_set_updated_at on public.company_memory_items;
        drop table if exists public.company_memory_items;
        drop function if exists public.company_memory_items_set_updated_at();
        """
    )
