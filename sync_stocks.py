from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

from database import connection
from report import FmpClient, load_dotenv_if_available, load_yaml


ROOT = Path(__file__).resolve().parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync active FMP symbols into the stocks table.")
    parser.add_argument("--config", default="config.yaml", help="Path to config YAML.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and compare data without changing the database.",
    )
    parser.add_argument(
        "--min-symbol-count",
        type=int,
        default=10000,
        help="Abort if FMP returns fewer symbols than this. Use 0 to disable.",
    )
    return parser.parse_args()


def fmp_client(config: dict[str, Any]) -> FmpClient:
    api_key = os.getenv("FMP_API_KEY")
    if not api_key:
        raise SystemExit("FMP_API_KEY is required. Add it to .env or the environment.")

    fmp_config = config.get("fmp", {})
    return FmpClient(
        api_key=api_key,
        base_url=fmp_config.get("base_url", "https://financialmodelingprep.com/stable"),
        timeout_seconds=int(fmp_config.get("request_timeout_seconds", 20)),
    )


def normalize_stock_rows(items: Any) -> list[tuple[str, str]]:
    if not isinstance(items, list):
        raise SystemExit("Expected FMP actively-trading-list response to be a JSON list.")

    rows_by_symbol: dict[str, tuple[str, str]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue

        symbol = str(item.get("symbol") or item.get("ticker") or "").upper().strip()
        company_name = str(item.get("name") or item.get("companyName") or item.get("company_name") or "").strip()
        if not symbol or not company_name:
            continue

        rows_by_symbol.setdefault(symbol, (symbol, company_name))

    return sorted(rows_by_symbol.values())


def fetch_active_stocks(client: FmpClient, min_symbol_count: int) -> list[tuple[str, str]]:
    rows = normalize_stock_rows(client.get("actively-trading-list", {}))
    if min_symbol_count > 0 and len(rows) < min_symbol_count:
        raise SystemExit(
            f"FMP returned only {len(rows)} valid symbols, below --min-symbol-count={min_symbol_count}. "
            "Aborting to avoid marking existing stocks inactive from a partial response."
        )
    return rows


def sync_stocks(rows: list[tuple[str, str]], dry_run: bool = False) -> dict[str, int]:
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                create temporary table active_stocks_import (
                    symbol text primary key,
                    company_name text not null
                ) on commit drop
                """
            )
            cursor.executemany(
                """
                insert into active_stocks_import (symbol, company_name)
                values (%s, %s)
                on conflict (symbol) do nothing
                """,
                rows,
            )

            cursor.execute(
                """
                select count(*)
                from active_stocks_import imported
                where not exists (
                    select 1
                    from public.stocks stocks
                    where stocks.symbol = imported.symbol
                )
                """
            )
            new_count = int(cursor.fetchone()[0])

            cursor.execute(
                """
                select count(*)
                from public.stocks stocks
                where stocks.is_actively_trading = false
                and exists (
                    select 1
                    from active_stocks_import imported
                    where imported.symbol = stocks.symbol
                )
                """
            )
            reactivate_count = int(cursor.fetchone()[0])

            cursor.execute(
                """
                select count(*)
                from public.stocks stocks
                where stocks.is_actively_trading = true
                and not exists (
                    select 1
                    from active_stocks_import imported
                    where imported.symbol = stocks.symbol
                )
                """
            )
            deactivate_count = int(cursor.fetchone()[0])

            if dry_run:
                conn.rollback()
                return {
                    "fetched": len(rows),
                    "inserted": new_count,
                    "reactivated": reactivate_count,
                    "deactivated": deactivate_count,
                }

            cursor.execute(
                """
                insert into public.stocks (symbol, company_name, is_actively_trading)
                select symbol, company_name, true
                from active_stocks_import
                on conflict (symbol) do nothing
                """
            )
            inserted_count = cursor.rowcount

            cursor.execute(
                """
                update public.stocks stocks
                set is_actively_trading = true
                where stocks.is_actively_trading = false
                and exists (
                    select 1
                    from active_stocks_import imported
                    where imported.symbol = stocks.symbol
                )
                """
            )
            reactivated_count = cursor.rowcount

            cursor.execute(
                """
                update public.stocks stocks
                set is_actively_trading = false
                where stocks.is_actively_trading = true
                and not exists (
                    select 1
                    from active_stocks_import imported
                    where imported.symbol = stocks.symbol
                )
                """
            )
            deactivated_count = cursor.rowcount

    return {
        "fetched": len(rows),
        "inserted": inserted_count,
        "reactivated": reactivated_count,
        "deactivated": deactivated_count,
    }


def main() -> int:
    args = parse_args()
    load_dotenv_if_available()

    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = ROOT / config_path

    config = load_yaml(config_path)
    rows = fetch_active_stocks(fmp_client(config), min_symbol_count=args.min_symbol_count)
    result = sync_stocks(rows, dry_run=args.dry_run)

    mode = "Dry run" if args.dry_run else "Synced"
    print(
        f"{mode} stocks: fetched={result['fetched']} "
        f"inserted={result['inserted']} "
        f"reactivated={result['reactivated']} "
        f"deactivated={result['deactivated']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
