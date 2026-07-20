"""allow aftermarket price source

Revision ID: 3f9a6b2c1d0e
Revises: 8c7f1d2a9b34
Create Date: 2026-07-17 13:00:00.000000
"""

from __future__ import annotations

from alembic import op


revision = '3f9a6b2c1d0e'
down_revision = '8c7f1d2a9b34'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        alter table public.price_plans
        drop constraint if exists price_plans_reference_source_check;

        alter table public.price_plans
        add constraint price_plans_reference_source_check
            check (reference_price_source in ('1min', '5min', '15min', 'aftermarket-quote'));

        alter table public.price_plans
        drop constraint if exists price_plans_last_checked_source_check;

        alter table public.price_plans
        add constraint price_plans_last_checked_source_check
            check (
                last_checked_price_source is null
                or last_checked_price_source in ('1min', '5min', '15min', 'aftermarket-quote')
            );

        alter table public.price_plans
        drop constraint if exists price_plans_triggered_source_check;

        alter table public.price_plans
        add constraint price_plans_triggered_source_check
            check (
                triggered_price_source is null
                or triggered_price_source in ('1min', '5min', '15min', 'aftermarket-quote')
            );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        alter table public.price_plans
        drop constraint if exists price_plans_reference_source_check;

        alter table public.price_plans
        add constraint price_plans_reference_source_check
            check (reference_price_source in ('1min', '5min', '15min'));

        alter table public.price_plans
        drop constraint if exists price_plans_last_checked_source_check;

        alter table public.price_plans
        add constraint price_plans_last_checked_source_check
            check (
                last_checked_price_source is null
                or last_checked_price_source in ('1min', '5min', '15min')
            );

        alter table public.price_plans
        drop constraint if exists price_plans_triggered_source_check;

        alter table public.price_plans
        add constraint price_plans_triggered_source_check
            check (
                triggered_price_source is null
                or triggered_price_source in ('1min', '5min', '15min')
            );
        """
    )
