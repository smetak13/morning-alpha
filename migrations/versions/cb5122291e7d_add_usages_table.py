"""add usages table

Revision ID: cb5122291e7d
Revises: 0bbdded790b0
Create Date: 2026-06-09 08:07:24.719889
"""

from __future__ import annotations

from alembic import op


revision = 'cb5122291e7d'
down_revision = '0bbdded790b0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        create table public.usages (
            id uuid primary key default gen_random_uuid(),
            user_id uuid not null references public.users(id) on delete cascade,
            task text not null,
            input_tokens integer not null default 0,
            output_tokens integer not null default 0,
            total_tokens integer not null default 0,
            total_cost numeric(14, 8) not null default 0,
            created_at timestamptz not null default now()
        );

        create index usages_user_id_created_at_idx
        on public.usages (user_id, created_at desc);

        create index usages_task_created_at_idx
        on public.usages (task, created_at desc);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        drop table if exists public.usages;
        """
    )
