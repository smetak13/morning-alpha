"""add users table

Revision ID: 294bbf59c16a
Revises: 
Create Date: 2026-06-04 11:30:28.897239
"""

from __future__ import annotations

from alembic import op


revision = '294bbf59c16a'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        create function public.users_set_updated_at()
        returns trigger
        language plpgsql
        as $$
        begin
            new.updated_at = now();
            return new;
        end;
        $$;

        create table public.users (
            id uuid primary key references neon_auth."user"(id) on delete cascade,
            email text,
            display_name text,
            timezone text not null default 'Europe/Prague',
            locale text not null default 'cs-CZ',
            onboarding_completed_at timestamptz,
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now()
        );

        create trigger users_set_updated_at
        before update on public.users
        for each row
        execute function public.users_set_updated_at();
        """
    )


def downgrade() -> None:
    op.execute(
        """
        drop trigger if exists users_set_updated_at on public.users;
        drop table if exists public.users;
        drop function if exists public.users_set_updated_at();
        """
    )
