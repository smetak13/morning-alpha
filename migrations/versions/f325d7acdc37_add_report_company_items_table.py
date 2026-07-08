"""add report_company_items table

Revision ID: f325d7acdc37
Revises: 4513f55e5d6c
Create Date: 2026-07-08 15:18:50.467513
"""

from __future__ import annotations

from alembic import op


revision = 'f325d7acdc37'
down_revision = '4513f55e5d6c'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        create table public.report_company_items (
            id uuid primary key default gen_random_uuid(),
            user_id uuid not null references public.users(id) on delete cascade,
            report_id uuid not null references public.reports(id) on delete cascade,
            stock_id uuid not null references public.stocks(id) on delete restrict,
            company_memory_item_id uuid references public.company_memory_items(id) on delete set null,
            section text not null,
            ticker text not null,
            company_name text,
            headline text,
            why_it_matters text,
            article_summary jsonb not null default '[]'::jsonb,
            source text,
            source_url text,
            attention_label text,
            importance text,
            thesis_impact text,
            thesis_summary text,
            thesis_points_affected jsonb not null default '[]'::jsonb,
            monitor_next text,
            metadata jsonb not null default '{}'::jsonb,
            report_date date not null,
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now(),
            constraint report_company_items_section_check
                check (section in ('portfolio', 'watchlist')),
            constraint report_company_items_ticker_not_blank_check
                check (length(trim(ticker)) > 0)
        );

        create index report_company_items_user_stock_date_idx
        on public.report_company_items (user_id, stock_id, report_date desc, created_at desc);

        create index report_company_items_report_id_idx
        on public.report_company_items (report_id);

        create index report_company_items_memory_item_idx
        on public.report_company_items (company_memory_item_id);

        create unique index report_company_items_report_stock_section_source_idx
        on public.report_company_items (
            report_id,
            stock_id,
            section,
            coalesce(nullif(source_url, ''), lower(coalesce(headline, '')))
        );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        drop index if exists public.report_company_items_report_stock_section_source_idx;
        drop index if exists public.report_company_items_memory_item_idx;
        drop index if exists public.report_company_items_report_id_idx;
        drop index if exists public.report_company_items_user_stock_date_idx;
        drop table if exists public.report_company_items;
        """
    )
