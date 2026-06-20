"""add deep research tables

Revision ID: c4ef05031f14
Revises: 458879f4ed84
Create Date: 2026-06-20 19:24:42.591772
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = 'c4ef05031f14'
down_revision = '458879f4ed84'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        alter table public.research_items
        drop constraint if exists research_items_research_type_check;

        alter table public.research_items
        add constraint research_items_research_type_check
        check (research_type in ('portfolio_check', 'watchlist_check', 'company_primer', 'deep_research'));

        alter table public.usages
        add column if not exists model text not null default 'gpt-4.1-mini';

        create index if not exists usages_model_created_at_idx
        on public.usages (model, created_at desc);

        create table public.research_runs (
            id uuid primary key default gen_random_uuid(),
            user_id uuid not null references public.users(id) on delete cascade,
            stock_id uuid not null references public.stocks(id) on delete restrict,
            research_item_id uuid references public.research_items(id) on delete set null,
            usage_id uuid references public.usages(id) on delete set null,
            research_type text not null default 'deep_research',
            status text not null default 'queued',
            progress_step text,
            progress_pct integer not null default 0,
            model text not null default 'gpt-5.4',
            request jsonb not null default '{}'::jsonb,
            usage jsonb not null default '{}'::jsonb,
            error text,
            created_at timestamptz not null default now(),
            started_at timestamptz,
            completed_at timestamptz,
            updated_at timestamptz not null default now(),
            constraint research_runs_research_type_check
                check (research_type in ('deep_research')),
            constraint research_runs_status_check
                check (status in ('queued', 'running', 'completed', 'failed', 'cancelled')),
            constraint research_runs_progress_pct_check
                check (progress_pct >= 0 and progress_pct <= 100)
        );

        create index research_runs_user_id_created_at_idx
        on public.research_runs (user_id, created_at desc);

        create index research_runs_status_created_at_idx
        on public.research_runs (status, created_at);

        create index research_runs_user_id_stock_id_created_at_idx
        on public.research_runs (user_id, stock_id, created_at desc);

        create table public.research_sources (
            id uuid primary key default gen_random_uuid(),
            research_item_id uuid references public.research_items(id) on delete cascade,
            research_run_id uuid references public.research_runs(id) on delete cascade,
            user_id uuid not null references public.users(id) on delete cascade,
            stock_id uuid not null references public.stocks(id) on delete restrict,
            source_key text not null,
            source_type text not null,
            title text,
            url text,
            publisher text,
            published_at timestamptz,
            fetched_at timestamptz not null default now(),
            metadata jsonb not null default '{}'::jsonb,
            excerpt text
        );

        create index research_sources_item_idx
        on public.research_sources (research_item_id);

        create index research_sources_run_idx
        on public.research_sources (research_run_id);

        create index research_sources_user_stock_type_idx
        on public.research_sources (user_id, stock_id, source_type);

        create table public.research_artifacts (
            id uuid primary key default gen_random_uuid(),
            research_item_id uuid references public.research_items(id) on delete cascade,
            research_run_id uuid references public.research_runs(id) on delete cascade,
            user_id uuid not null references public.users(id) on delete cascade,
            stock_id uuid not null references public.stocks(id) on delete restrict,
            artifact_type text not null,
            title text,
            data jsonb not null default '{}'::jsonb,
            created_at timestamptz not null default now()
        );

        create index research_artifacts_item_type_idx
        on public.research_artifacts (research_item_id, artifact_type);

        create index research_artifacts_run_type_idx
        on public.research_artifacts (research_run_id, artifact_type);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        drop table if exists public.research_artifacts;
        drop table if exists public.research_sources;
        drop table if exists public.research_runs;

        drop index if exists public.usages_model_created_at_idx;
        alter table public.usages drop column if exists model;

        alter table public.research_items
        drop constraint if exists research_items_research_type_check;

        alter table public.research_items
        add constraint research_items_research_type_check
        check (research_type in ('portfolio_check', 'watchlist_check', 'company_primer'));
        """
    )
