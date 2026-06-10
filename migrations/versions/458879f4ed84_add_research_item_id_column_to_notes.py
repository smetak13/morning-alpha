"""add research_item_id column to notes

Revision ID: 458879f4ed84
Revises: af2a4b9986b3
Create Date: 2026-06-10 18:49:41.450127
"""

from __future__ import annotations

from alembic import op


revision = '458879f4ed84'
down_revision = 'af2a4b9986b3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        alter table public.notes
        add column research_item_id uuid references public.research_items(id) on delete cascade;

        create index notes_user_id_research_item_id_created_at_idx
        on public.notes (user_id, research_item_id, created_at desc);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        drop index if exists public.notes_user_id_research_item_id_created_at_idx;

        alter table public.notes
        drop column if exists research_item_id;
        """
    )
