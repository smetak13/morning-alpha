from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path
from typing import Any

from company_memory import (
    extract_backfill_report_with_gpt,
    load_user_stock_map,
    update_company_memory_from_report,
)
from database import connection
from report import ROOT, load_yaml


def parse_date(value: str | None) -> dt.date | None:
    if not value:
        return None
    return dt.date.fromisoformat(value)


def load_reports(user_id: str, *, limit: int | None, date_from: dt.date | None, date_to: dt.date | None) -> list[dict[str, Any]]:
    try:
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise RuntimeError("Missing dependency 'psycopg'. Install dependencies with: pip install -r requirements.txt") from exc

    clauses = ["user_id = %(user_id)s"]
    params: dict[str, Any] = {"user_id": user_id}
    if date_from:
        clauses.append("report_date >= %(date_from)s")
        params["date_from"] = date_from
    if date_to:
        clauses.append("report_date <= %(date_to)s")
        params["date_to"] = date_to
    limit_sql = "limit %(limit)s" if limit else ""
    if limit:
        params["limit"] = limit
    with connection(row_factory=dict_row) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                select id::text as id, report_date, html
                from public.reports
                where {" and ".join(clauses)}
                order by report_date asc, created_at asc
                {limit_sql}
                """,
                params,
            )
            return [dict(row) for row in cursor.fetchall()]


def synthetic_context(known_stocks: dict[str, str]) -> dict[str, Any]:
    return {
        "portfolio": [
            {"ticker": ticker, "stock_id": stock_id, "thesis": {}}
            for ticker, stock_id in sorted(known_stocks.items())
        ],
        "watchlist": [],
        "ranked_news": [],
        "company_memory": [],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill company memory from existing Morning Alpha reports.")
    parser.add_argument("--user-id", required=True, help="User ID whose reports should be processed.")
    parser.add_argument("--config", default="config.yaml", help="Path to config YAML.")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of reports to process.")
    parser.add_argument("--date-from", default=None, help="Oldest report_date to process, YYYY-MM-DD.")
    parser.add_argument("--date-to", default=None, help="Newest report_date to process, YYYY-MM-DD.")
    parser.add_argument("--dry-run", action="store_true", help="Classify and print counts without writing memory rows.")
    args = parser.parse_args()

    try:
        from dotenv import load_dotenv
    except ImportError:
        load_dotenv = None
    if load_dotenv:
        load_dotenv()

    config_path = Path(args.config)
    config = load_yaml(config_path if config_path.is_absolute() else ROOT / config_path)
    known_stocks = load_user_stock_map(args.user_id)
    if not known_stocks:
        raise SystemExit("No user stocks found in portfolio, watchlist, or notes. Nothing to backfill.")

    reports = load_reports(
        args.user_id,
        limit=args.limit,
        date_from=parse_date(args.date_from),
        date_to=parse_date(args.date_to),
    )
    if not reports:
        raise SystemExit("No reports found for the selected filters.")

    totals = {"created": 0, "updated": 0, "ignored": 0, "events": 0}
    for index, row in enumerate(reports, start=1):
        report_date = row["report_date"] if isinstance(row["report_date"], dt.date) else dt.date.fromisoformat(str(row["report_date"]))
        print(f"[{index}/{len(reports)}] Processing report {row['id']} date={report_date.isoformat()}")
        report, extraction_usage = extract_backfill_report_with_gpt(
            user_id=args.user_id,
            report_html=row["html"],
            report_date=report_date,
            known_stocks=known_stocks,
            config=config,
        )
        summary = update_company_memory_from_report(
            user_id=args.user_id,
            report=report,
            context=synthetic_context(known_stocks),
            config=config,
            report_id=row["id"],
            report_date=report_date,
            dry_run=args.dry_run,
        )
        for key in totals:
            totals[key] += int(summary.get(key) or 0)
        usage_note = ""
        if extraction_usage:
            usage_note = f" extraction_tokens={extraction_usage.get('total_tokens', 0)}"
        print(
            f"  created={summary.get('created', 0)} updated={summary.get('updated', 0)} "
            f"ignored={summary.get('ignored', 0)} events={summary.get('events', 0)}{usage_note}"
        )

    mode = "DRY RUN " if args.dry_run else ""
    print(
        f"{mode}Done. created={totals['created']} updated={totals['updated']} "
        f"ignored={totals['ignored']} events={totals['events']}"
    )


if __name__ == "__main__":
    main()
