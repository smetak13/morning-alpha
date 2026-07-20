from __future__ import annotations

import os
import argparse
import datetime as dt
import html
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from database import connection
from market_prices import latest_market_price
from psycopg.types.json import Json
from report import email_asset_src, load_dotenv_if_available, load_yaml, send_email
from sync_stocks import fmp_client, fetch_active_stocks, sync_stocks


DEFAULT_TIMEZONE = "Europe/Prague"
SCHEDULER_INTERVAL_MINS = int(os.getenv("SCHEDULER_INTERVAL_MINS", "15"))
UTC = dt.timezone.utc
PRAGUE_TZ = ZoneInfo(DEFAULT_TIMEZONE)
STOCK_SYNC_MIN_SYMBOL_COUNT = int(os.getenv("STOCK_SYNC_MIN_SYMBOL_COUNT", "10000"))
_last_stock_sync_date: dt.date | None = None
_last_earnings_notification_date: dt.date | None = None


@dataclass(frozen=True)
class ScheduledReportJob:
    user_id: str
    email: str
    timezone: str
    report_scheduled_at: dt.time
    report_frequency: str
    scheduled_for: dt.datetime


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run scheduled Morning Alpha report jobs.")
    parser.add_argument("--once", action="store_true", help="Run one scheduler cycle and exit.")
    parser.add_argument("--run-immediately", action="store_true", help="Run one cycle immediately before hourly loop.")
    parser.add_argument("--date", default="latest", help="'latest' or an explicit YYYY-MM-DD US trading date.")
    parser.add_argument("--config", default="config.yaml", help="Path to config YAML.")
    parser.add_argument("--skip-openai", action="store_true", help="Use deterministic fallback report generation.")
    parser.add_argument("--lookback-minutes", type=int, default=SCHEDULER_INTERVAL_MINS, help="Scheduler lookback window in minutes.")
    parser.add_argument("--log-level", default="INFO", choices=("DEBUG", "INFO", "WARNING", "ERROR"))
    return parser.parse_args()


def normalize_timezone(value: str | None) -> str:
    timezone = (value or "").strip() or DEFAULT_TIMEZONE
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError:
        logging.warning("Invalid user timezone %r, falling back to %s", value, DEFAULT_TIMEZONE)
        return DEFAULT_TIMEZONE
    return timezone


def coerce_time(value: Any) -> dt.time:
    if isinstance(value, dt.time):
        return value.replace(tzinfo=None)
    if isinstance(value, dt.timedelta):
        seconds = int(value.total_seconds()) % 86_400
        hour, remainder = divmod(seconds, 3600)
        minute, second = divmod(remainder, 60)
        return dt.time(hour=hour, minute=minute, second=second)
    if isinstance(value, str):
        return dt.time.fromisoformat(value)
    raise TypeError(f"Unsupported report_scheduled_at value: {value!r}")


def due_scheduled_time(
    *,
    report_scheduled_at: dt.time,
    timezone: str,
    run_at_utc: dt.datetime,
    lookback: dt.timedelta,
) -> dt.datetime | None:
    tz = ZoneInfo(timezone)
    local_end = run_at_utc.astimezone(tz)
    local_start = local_end - lookback

    for scheduled_date in {local_start.date(), local_end.date()}:
        scheduled_local = dt.datetime.combine(scheduled_date, report_scheduled_at, tzinfo=tz)
        if local_start < scheduled_local <= local_end:
            return scheduled_local.astimezone(UTC)
    return None


def normalize_report_frequency(value: str | None) -> str:
    frequency = str(value or "daily").strip().lower()
    return frequency if frequency in {"daily", "weekly", "monthly"} else "daily"


def report_delivery_is_enabled(*, timezone: str, run_at_utc: dt.datetime, frequency: str) -> bool:
    local_date = run_at_utc.astimezone(ZoneInfo(timezone)).date()
    if frequency == "weekly":
        return local_date.weekday() == 6
    if frequency == "monthly":
        return local_date.day == 1
    return local_date.weekday() < 5


def load_due_jobs(run_at_utc: dt.datetime, lookback: dt.timedelta) -> list[ScheduledReportJob]:
    try:
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise RuntimeError("Missing dependency 'psycopg'. Install dependencies with: pip install -r requirements.txt") from exc

    with connection(row_factory=dict_row) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                select
                    id::text as id,
                    email,
                    timezone,
                    report_scheduled_at,
                    report_frequency
                from public.users
                where email is not null
                  and report_scheduled_at is not null
                order by report_scheduled_at, id
                """
            )
            rows = cursor.fetchall()

    due_jobs: list[ScheduledReportJob] = []
    for row in rows:
        email = str(row["email"] or "").strip()
        if not email:
            continue

        timezone = normalize_timezone(row.get("timezone"))
        report_frequency = normalize_report_frequency(row.get("report_frequency"))
        if not report_delivery_is_enabled(timezone=timezone, run_at_utc=run_at_utc, frequency=report_frequency):
            logging.debug(
                "Skipping scheduled report outside frequency window user_id=%s timezone=%s frequency=%s local_date=%s",
                row["id"],
                timezone,
                report_frequency,
                run_at_utc.astimezone(ZoneInfo(timezone)).date().isoformat(),
            )
            continue

        report_scheduled_at = coerce_time(row["report_scheduled_at"])
        scheduled_for = due_scheduled_time(
            report_scheduled_at=report_scheduled_at,
            timezone=timezone,
            run_at_utc=run_at_utc,
            lookback=lookback,
        )
        if scheduled_for is None:
            continue

        due_jobs.append(
            ScheduledReportJob(
                user_id=str(row["id"]),
                email=email,
                timezone=timezone,
                report_scheduled_at=report_scheduled_at,
                report_frequency=report_frequency,
                scheduled_for=scheduled_for,
            )
        )

    return due_jobs


def enqueue_report_runs(
    *,
    jobs: list[ScheduledReportJob],
    date_arg: str,
    config_path: str,
    skip_openai: bool,
) -> None:
    if not jobs:
        logging.info("No report runs to enqueue")
        return

    inserted = 0
    duplicate = 0
    with connection() as conn:
        with conn.cursor() as cursor:
            for job in jobs:
                cursor.execute(
                    """
                    insert into public.report_runs (
                        user_id,
                        recipient_email,
                        timezone,
                        report_scheduled_at,
                        report_frequency,
                        scheduled_for,
                        date_arg,
                        status,
                        progress_step,
                        progress_pct,
                        request
                    )
                    values (
                        %(user_id)s,
                        %(recipient_email)s,
                        %(timezone)s,
                        %(report_scheduled_at)s,
                        %(report_frequency)s,
                        %(scheduled_for)s,
                        %(date_arg)s,
                        'queued',
                        'Queued for report generation',
                        0,
                        %(request)s
                    )
                    on conflict (user_id, scheduled_for, report_frequency) do nothing
                    returning id::text
                    """,
                    {
                        "user_id": job.user_id,
                        "recipient_email": job.email,
                        "timezone": job.timezone,
                        "report_scheduled_at": job.report_scheduled_at,
                        "report_frequency": job.report_frequency,
                        "scheduled_for": job.scheduled_for,
                        "date_arg": date_arg,
                        "request": Json(
                            {
                                "config_path": config_path,
                                "skip_openai": skip_openai,
                                "scheduler": "report_scheduler.py",
                            }
                        ),
                    },
                )
                row = cursor.fetchone()
                if row:
                    inserted += 1
                    logging.info(
                        "Queued report run id=%s user_id=%s email=%s frequency=%s scheduled_for=%s timezone=%s",
                        row[0],
                        job.user_id,
                        job.email,
                        job.report_frequency,
                        job.scheduled_for.isoformat(),
                        job.timezone,
                    )
                else:
                    duplicate += 1
                    logging.info(
                        "Skipped duplicate report run user_id=%s frequency=%s scheduled_for=%s",
                        job.user_id,
                        job.report_frequency,
                        job.scheduled_for.isoformat(),
                    )
    logging.info("Scheduler enqueue finished total=%s inserted=%s duplicate=%s", len(jobs), inserted, duplicate)


def stock_sync_is_due(run_at_utc: dt.datetime) -> bool:
    global _last_stock_sync_date
    local_run_at = run_at_utc.astimezone(PRAGUE_TZ)
    if local_run_at.hour != 0:
        return False
    if _last_stock_sync_date == local_run_at.date():
        return False
    return True


def run_daily_stock_sync(args: argparse.Namespace, run_at_utc: dt.datetime) -> None:
    global _last_stock_sync_date
    if not stock_sync_is_due(run_at_utc):
        return

    local_date = run_at_utc.astimezone(PRAGUE_TZ).date()
    logging.info(
        "Starting daily stock sync local_date=%s timezone=%s min_symbol_count=%s",
        local_date.isoformat(),
        DEFAULT_TIMEZONE,
        STOCK_SYNC_MIN_SYMBOL_COUNT,
    )
    try:
        config_path = Path(args.config)
        if not config_path.is_absolute():
            config_path = Path(__file__).resolve().parent / config_path
        config = load_yaml(config_path)
        rows = fetch_active_stocks(fmp_client(config), min_symbol_count=STOCK_SYNC_MIN_SYMBOL_COUNT)
        result = sync_stocks(rows, dry_run=False)
    except Exception:
        logging.exception("Daily stock sync failed local_date=%s", local_date.isoformat())
        return

    _last_stock_sync_date = local_date
    logging.info(
        "Daily stock sync finished local_date=%s fetched=%s inserted=%s reactivated=%s deactivated=%s",
        local_date.isoformat(),
        result["fetched"],
        result["inserted"],
        result["reactivated"],
        result["deactivated"],
    )


def earnings_notification_sync_is_due(run_at_utc: dt.datetime) -> bool:
    global _last_earnings_notification_date
    local_run_at = run_at_utc.astimezone(PRAGUE_TZ)
    if local_run_at.hour != 2:
        return False
    if _last_earnings_notification_date == local_run_at.date():
        return False
    return True


def scheduler_fmp_items(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict):
        items = data.get("historical") or data.get("historicalStockList") or data.get("data") or []
    elif isinstance(data, list):
        items = data
    else:
        return []
    return [item for item in items if isinstance(item, dict)]


def parse_fmp_date(value: Any) -> dt.date | None:
    if not value:
        return None
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def row_any(row: dict[str, Any], *names: str) -> Any:
    lower_map = {str(key).lower(): value for key, value in row.items()} if isinstance(row, dict) else {}
    for name in names:
        if name in row and row.get(name) not in (None, "", []):
            return row.get(name)
        value = lower_map.get(str(name).lower())
        if value not in (None, "", []):
            return value
    return None


def normalize_earnings_event(row: dict[str, Any], today: dt.date) -> dict[str, Any] | None:
    event_date = parse_fmp_date(row_any(row, "date", "fiscalDateEnding"))
    if event_date is None or event_date < today:
        return None

    quarter = row_any(row, "quarter", "fiscalQuarter", "period")
    fiscal_quarter = str(quarter).strip().upper() if quarter not in (None, "", []) else None
    if fiscal_quarter and fiscal_quarter.isdigit():
        fiscal_quarter = f"Q{fiscal_quarter}"

    fiscal_year = row_any(row, "calendarYear", "fiscalYear", "year")
    if fiscal_year not in (None, "", []):
        try:
            fiscal_year = str(int(float(fiscal_year)))
        except (TypeError, ValueError):
            fiscal_year = str(fiscal_year)
    else:
        fiscal_year = None

    report_time = row_any(row, "time", "reportTime", "publicationTime", "epsTime")
    return {
        "event_date": event_date,
        "report_time": str(report_time).strip() if report_time not in (None, "", []) else None,
        "fiscal_quarter": fiscal_quarter,
        "fiscal_year": fiscal_year,
        "raw": row,
    }


def fetch_upcoming_earnings_events(client: Any, symbol: str, today: dt.date) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for endpoint, params in (
        ("earnings", {"symbol": symbol, "limit": 20, "includeReportTimes": True}),
        ("historical/earning_calendar", {"symbol": symbol, "limit": 20}),
        ("earnings-calendar", {"symbol": symbol, "limit": 20}),
    ):
        try:
            rows = scheduler_fmp_items(client.get(endpoint, params))
        except Exception as exc:
            logging.warning("FMP earnings fetch failed symbol=%s endpoint=%s error=%s", symbol, endpoint, exc)
            continue
        if rows:
            break

    events: list[dict[str, Any]] = []
    seen_dates: set[dt.date] = set()
    for row in rows:
        event = normalize_earnings_event(row, today)
        if not event or event["event_date"] in seen_dates:
            continue
        seen_dates.add(event["event_date"])
        events.append(event)
    return sorted(events, key=lambda item: item["event_date"])


def load_notification_stock_universe(cursor: Any) -> list[dict[str, Any]]:
    cursor.execute(
        """
        select distinct
            stocks.id::text as stock_id,
            stocks.symbol,
            stocks.company_name
        from public.stocks
        where exists (
            select 1 from public.portfolio_items
            where portfolio_items.stock_id = stocks.id
        )
           or exists (
            select 1 from public.watchlist_items
            where watchlist_items.stock_id = stocks.id
        )
        order by stocks.symbol
        """
    )
    return [dict(row) for row in cursor.fetchall()]


def refresh_stock_earnings_events(*, client: Any, today: dt.date) -> int:
    from psycopg.rows import dict_row

    updated = 0
    with connection(row_factory=dict_row) as conn:
        with conn.cursor() as cursor:
            stocks = load_notification_stock_universe(cursor)
            logging.info("Refreshing earnings events for %s unique stocks", len(stocks))
            for stock in stocks:
                symbol = str(stock["symbol"]).upper()
                events = fetch_upcoming_earnings_events(client, symbol, today)
                for event in events:
                    cursor.execute(
                        """
                        insert into public.stock_earnings_events (
                            stock_id,
                            symbol,
                            event_date,
                            report_time,
                            fiscal_quarter,
                            fiscal_year,
                            source,
                            raw,
                            updated_at
                        )
                        values (
                            %(stock_id)s,
                            %(symbol)s,
                            %(event_date)s,
                            %(report_time)s,
                            %(fiscal_quarter)s,
                            %(fiscal_year)s,
                            'fmp',
                            %(raw)s,
                            now()
                        )
                        on conflict (stock_id, event_date) do update
                        set symbol = excluded.symbol,
                            report_time = excluded.report_time,
                            fiscal_quarter = excluded.fiscal_quarter,
                            fiscal_year = excluded.fiscal_year,
                            source = excluded.source,
                            raw = excluded.raw,
                            updated_at = now()
                        """,
                        {
                            "stock_id": stock["stock_id"],
                            "symbol": symbol,
                            "event_date": event["event_date"],
                            "report_time": event["report_time"],
                            "fiscal_quarter": event["fiscal_quarter"],
                            "fiscal_year": event["fiscal_year"],
                            "raw": Json(event["raw"]),
                        },
                    )
                    updated += 1
    return updated


def reminder_title(symbol: str, company_name: str, reminder_kind: str) -> str:
    prefix = "Soon" if reminder_kind == "1d" else "Upcoming"
    return f"{prefix}: {symbol} earnings call"


def reminder_body(company_name: str, event_date: dt.date, report_time: str | None, reminder_kind: str) -> str:
    date_text = event_date.strftime("%b %-d, %Y") if os.name != "nt" else event_date.strftime("%b %#d, %Y")
    timing = f" ({report_time})" if report_time else ""
    if reminder_kind == "1d":
        return f"{company_name} is expected to report earnings soon: {date_text}{timing}."
    return f"{company_name} is expected to report earnings on {date_text}{timing}."


def create_earnings_notifications(today: dt.date) -> int:
    from psycopg.rows import dict_row

    inserted = 0
    with connection(row_factory=dict_row) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                select
                    holdings.user_id::text as user_id,
                    holdings.relationship,
                    holdings.item_id::text as item_id,
                    stocks.id::text as stock_id,
                    stocks.symbol,
                    stocks.company_name,
                    events.event_date,
                    events.report_time,
                    events.fiscal_quarter,
                    events.fiscal_year
                from (
                    select user_id, stock_id, id as item_id, 'portfolio'::text as relationship
                    from public.portfolio_items
                    union all
                    select user_id, stock_id, id as item_id, 'watchlist'::text as relationship
                    from public.watchlist_items
                ) holdings
                join public.stocks on stocks.id = holdings.stock_id
                join public.stock_earnings_events events on events.stock_id = holdings.stock_id
                where events.event_date between %(today)s and %(week_end)s
                order by holdings.user_id, events.event_date, stocks.symbol
                """,
                {"today": today, "week_end": today + dt.timedelta(days=7)},
            )
            rows = cursor.fetchall()
            for row in rows:
                event_date = row["event_date"]
                days_until = (event_date - today).days
                reminder_kinds = ["7d"]
                if days_until <= 1:
                    reminder_kinds.append("1d")

                for reminder_kind in reminder_kinds:
                    symbol = str(row["symbol"]).upper()
                    target_url = f"/research#{row['relationship']}-{row['item_id']}"
                    params = {
                        "user_id": row["user_id"],
                        "stock_id": row["stock_id"],
                        "portfolio_item_id": row["item_id"] if row["relationship"] == "portfolio" else None,
                        "watchlist_item_id": row["item_id"] if row["relationship"] == "watchlist" else None,
                        "event_date": event_date,
                        "reminder_kind": reminder_kind,
                        "title": reminder_title(symbol, row["company_name"], reminder_kind),
                        "body": reminder_body(row["company_name"], event_date, row["report_time"], reminder_kind),
                        "target_url": target_url,
                        "expires_at": dt.datetime.combine(event_date + dt.timedelta(days=7), dt.time.min, tzinfo=UTC),
                        "metadata": Json(
                            {
                                "symbol": symbol,
                                "company_name": row["company_name"],
                                "relationship": row["relationship"],
                                "fiscal_quarter": row["fiscal_quarter"],
                                "fiscal_year": row["fiscal_year"],
                                "report_time": row["report_time"],
                            }
                        ),
                    }
                    cursor.execute(
                        """
                        insert into public.notifications (
                            user_id,
                            type,
                            title,
                            body,
                            target_url,
                            stock_id,
                            portfolio_item_id,
                            watchlist_item_id,
                            event_date,
                            reminder_kind,
                            expires_at,
                            metadata
                        )
                        values (
                            %(user_id)s,
                            'earnings_call_reminder',
                            %(title)s,
                            %(body)s,
                            %(target_url)s,
                            %(stock_id)s,
                            %(portfolio_item_id)s,
                            %(watchlist_item_id)s,
                            %(event_date)s,
                            %(reminder_kind)s,
                            %(expires_at)s,
                            %(metadata)s
                        )
                        on conflict (user_id, type, stock_id, event_date, reminder_kind)
                        where type = 'earnings_call_reminder'
                          and stock_id is not null
                          and event_date is not null
                          and reminder_kind is not null
                        do nothing
                        returning id
                        """,
                        params,
                    )
                    if cursor.fetchone():
                        inserted += 1
    return inserted


def format_price_for_notification(value: Any, currency: str) -> str:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return str(value)
    prefix = "$" if str(currency or "USD").upper() == "USD" else f"{str(currency).upper()} "
    return f"{prefix}{amount:,.2f}"


def html_escape(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def html_email_text(value: Any) -> str:
    return html_escape(value).replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")


def price_plan_condition_label(direction: str) -> str:
    return "Price rose above your target" if direction == "above" else "Price fell below your target"


def format_price_plan_time(value: Any, timezone: str | None) -> str:
    if isinstance(value, dt.datetime):
        timestamp = value if value.tzinfo else value.replace(tzinfo=UTC)
        timezone_name = normalize_timezone(timezone)
        local_timestamp = timestamp.astimezone(ZoneInfo(timezone_name))
        timezone_label = local_timestamp.tzname() or timezone_name
        return local_timestamp.strftime("%b %d, %Y %H:%M").replace(" 0", " ") + f" {timezone_label}"
    return str(value or "Unavailable")


def price_plan_stock_logo_url(symbol: str) -> str:
    cleaned_symbol = "".join(char for char in str(symbol or "").upper().strip() if char.isalnum() or char in {".", "-"})
    return f"https://financialmodelingprep.com/image-stock/{cleaned_symbol}.png" if cleaned_symbol else ""


def render_price_plan_email(
    *,
    symbol: str,
    company_name: str,
    target_label: str,
    triggered_label: str,
    direction: str,
    price_at: Any,
    timezone: str | None,
    note: str | None,
) -> str:
    logo_src = email_asset_src("ma-logo.png")
    brand_html = (
        f'<img src="{html_escape(logo_src)}" width="270" height="50" alt="Morning Alpha" style="border:0;display:block;height:auto;line-height:0;max-width:270px;width:270px;">'
        if logo_src
        else '<strong style="color:#ffffff;font-size:20px;">Morning Alpha</strong>'
    )
    stock_logo_src = price_plan_stock_logo_url(symbol)
    stock_logo_html = (
        f"""
        <table border="0" cellpadding="0" cellspacing="0" role="presentation" width="46" style="border-collapse:collapse;width:46px;">
          <tr>
            <td align="center" bgcolor="#222222" style="background:#222222;background-color:#222222!important;border:1px solid #343434;border-radius:8px;height:44px;padding:0;text-align:center;vertical-align:middle;width:44px;">
              <img src="{html_escape(stock_logo_src)}" width="34" height="34" alt="{html_escape(symbol)}" style="-webkit-filter:none!important;border:0;display:inline-block;filter:none!important;height:34px;line-height:34px;max-height:34px;max-width:34px;min-height:34px;min-width:34px;object-fit:contain;outline:0;text-decoration:none;vertical-align:middle;width:34px;">
            </td>
          </tr>
        </table>
        """
        if stock_logo_src
        else f"""
        <table border="0" cellpadding="0" cellspacing="0" role="presentation" width="46" style="border-collapse:collapse;width:46px;">
          <tr>
            <td align="center" bgcolor="#0d0d0d" style="background:#0d0d0d;background-color:#0d0d0d!important;border:1px solid #2a2a2a;border-radius:8px;color:#f4c430;font-size:16px;font-weight:700;height:44px;line-height:44px;text-align:center;vertical-align:middle;width:44px;">{html_escape(symbol[:2])}</td>
          </tr>
        </table>
        """
    )
    metrics = [
        ("Target price", target_label),
        ("Triggered price", triggered_label),
        ("Trigger condition", price_plan_condition_label(direction)),
        ("Price observed at", format_price_plan_time(price_at, timezone)),
    ]
    metric_cells = [
        f"""
        <td width="50%" style="width:50%;padding:6px;vertical-align:top;">
          <div style="background:#0d0d0d;border:1px solid #2a2a2a;border-radius:8px;margin:0;padding:10px;">
            <div style="color:#a7a7a0;font-size:12px;line-height:1.25;">{html_escape(label)}</div>
            <div style="color:#ffffff;font-size:15px;font-weight:700;line-height:1.25;margin-top:4px;">{html_escape(value)}</div>
          </div>
        </td>
        """
        for label, value in metrics
    ]
    metric_rows = "".join(f"<tr>{''.join(metric_cells[index:index + 2])}</tr>" for index in range(0, len(metric_cells), 2))
    note_html = (
        f"""
        <div style="background:#111111;border:1px solid #2a2a2a;border-radius:8px;margin:14px 0 0;padding:12px;">
          <div style="color:#f4c430;font-size:11px;font-weight:700;letter-spacing:.04em;line-height:1.25;margin-bottom:6px;text-transform:uppercase;">Note</div>
          <p style="color:#d7d7d0;font-size:14px;line-height:1.55;margin:0;">{html_email_text(note)}</p>
        </div>
        """
        if note
        else ""
    )
    return f"""
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <meta name="color-scheme" content="dark">
        <meta name="supported-color-schemes" content="dark">
        <title>{html_escape(symbol)} price alert</title>
      </head>
      <body style="margin:0;padding:0;background:#080808;color:#f4f4f0;font-family:Arial,Helvetica,sans-serif;">
        <div style="background:#080808;padding:28px 12px;">
          <div style="max-width:760px;margin:0 auto;background:#111111;border:1px solid #2a2a2a;border-radius:8px;overflow:hidden;">
            <div style="background:#151515;border-bottom:1px solid #2a2a2a;padding:26px 28px 22px;">
              <div style="margin-bottom:26px;">{brand_html}</div>
              <div style="color:#8f8f87;font-size:10px;font-weight:700;letter-spacing:.08em;line-height:1.2;text-transform:uppercase;">Price alert</div>
              <h1 style="color:#ffffff;font-size:28px;line-height:1.15;margin:8px 0 0;">{html_escape(symbol)} reached your price alert</h1>
            </div>
            <div style="padding:24px 28px 28px;">
              <div style="background:#181818;border:1px solid #2a2a2a;border-radius:8px;margin:0 0 14px;overflow:hidden;">
                <div style="background:#151515;border-bottom:1px solid #2a2a2a;padding:14px 16px;">
                  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;">
                    <tr>
                      <td width="58" style="width:58px;vertical-align:middle;padding:0 12px 0 0;">{stock_logo_html}</td>
                      <td style="vertical-align:middle;padding:0;">
                        <div style="color:#ffffff;font-size:18px;font-weight:700;line-height:1.25;">{html_escape(symbol)}</div>
                        <div style="color:#d7d7d0;font-size:14px;line-height:1.4;margin-top:2px;">{html_escape(company_name)}</div>
                        <div style="margin-top:9px;">
                          <span style="background:rgba(244,196,48,.12);border:1px solid #f4c430;border-radius:999px;color:#f4d76b;display:inline-block;font-size:9px;font-weight:700;letter-spacing:0;line-height:1.2;padding:6px 10px;text-transform:uppercase;">Price alert triggered</span>
                        </div>
                      </td>
                    </tr>
                  </table>
                </div>
                <div style="padding:16px;">
                  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;table-layout:fixed;">{metric_rows}</table>
                  {note_html}
                </div>
              </div>
              <p style="border-top:1px solid #343434;color:#a7a7a0;font-size:12px;line-height:1.5;margin:24px 0 0;padding-top:16px;">This is an informational alert from your Morning Alpha price plan, not investment advice.</p>
            </div>
          </div>
        </div>
      </body>
    </html>
    """


def send_price_plan_email(plan: dict[str, Any], *, symbol: str, current_price: Any, latest: dict[str, Any]) -> None:
    target_label = format_price_for_notification(plan["target_price"], plan["currency"])
    triggered_label = format_price_for_notification(current_price, plan["currency"])
    subject = f"{symbol} reached your {target_label} price alert"
    html_body = render_price_plan_email(
        symbol=symbol,
        company_name=str(plan.get("company_name") or symbol),
        target_label=target_label,
        triggered_label=triggered_label,
        direction=str(plan["direction"]),
        price_at=latest.get("price_at"),
        timezone=str(plan.get("timezone") or ""),
        note=str(plan.get("note") or "").strip() or None,
    )
    send_email(subject, html_body, recipient_email=str(plan["user_email"]))


def load_active_price_plans(cursor: Any) -> list[dict[str, Any]]:
    cursor.execute(
        """
        select
            price_plans.id::text as id,
            price_plans.user_id::text as user_id,
            price_plans.stock_id::text as stock_id,
            price_plans.target_price,
            price_plans.currency,
            price_plans.direction,
            price_plans.note,
            price_plans.email_on_trigger,
            users.email as user_email,
            users.timezone,
            stocks.symbol,
            stocks.company_name
        from public.price_plans
        join public.stocks on stocks.id = price_plans.stock_id
        join public.users on users.id = price_plans.user_id
        where price_plans.status = 'active'
        order by stocks.symbol, price_plans.created_at
        """
    )
    return [dict(row) for row in cursor.fetchall()]


def create_price_plan_notifications(client: Any, run_at_utc: dt.datetime) -> int:
    from psycopg.rows import dict_row

    triggered = 0
    with connection(row_factory=dict_row) as conn:
        with conn.cursor() as cursor:
            plans = load_active_price_plans(cursor)
            by_symbol: dict[str, list[dict[str, Any]]] = {}
            for plan in plans:
                by_symbol.setdefault(str(plan["symbol"]).upper(), []).append(plan)

            for symbol, symbol_plans in by_symbol.items():
                latest = latest_market_price(client, symbol, now=run_at_utc)
                if latest is None:
                    logging.info("Skipping price plans; market price unavailable symbol=%s", symbol)
                    continue

                current_price = latest["price"]
                for plan in symbol_plans:
                    cursor.execute(
                        """
                        update public.price_plans
                        set last_checked_price = %(price)s,
                            last_checked_price_source = %(source)s,
                            last_checked_price_at = %(price_at)s,
                            last_checked_at = %(checked_at)s
                        where id::text = %(id)s
                          and status = 'active'
                        """,
                        {
                            "id": plan["id"],
                            "price": current_price,
                            "source": latest["source"],
                            "price_at": latest["price_at"],
                            "checked_at": latest["checked_at"],
                        },
                    )

                    target_price = plan["target_price"]
                    direction = str(plan["direction"])
                    reached = (
                        direction == "above" and current_price >= target_price
                    ) or (
                        direction == "below" and current_price <= target_price
                    )
                    if not reached:
                        continue

                    cursor.execute(
                        """
                        update public.price_plans
                        set status = 'triggered',
                            triggered_price = %(price)s,
                            triggered_price_source = %(source)s,
                            triggered_price_at = %(price_at)s,
                            triggered_at = %(triggered_at)s
                        where id::text = %(id)s
                          and status = 'active'
                        returning id::text
                        """,
                        {
                            "id": plan["id"],
                            "price": current_price,
                            "source": latest["source"],
                            "price_at": latest["price_at"],
                            "triggered_at": run_at_utc,
                        },
                    )
                    if not cursor.fetchone():
                        continue

                    target_label = format_price_for_notification(plan["target_price"], plan["currency"])
                    cursor.execute(
                        """
                        insert into public.notifications (
                            user_id,
                            type,
                            title,
                            body,
                            stock_id,
                            expires_at,
                            metadata
                        )
                        values (
                            %(user_id)s,
                            'price_plan_triggered',
                            %(title)s,
                            %(body)s,
                            %(stock_id)s,
                            %(expires_at)s,
                            %(metadata)s
                        )
                        """,
                        {
                            "user_id": plan["user_id"],
                            "title": f"{symbol} reached your {target_label} alert",
                            "body": str(plan.get("note") or "").strip() or None,
                            "stock_id": plan["stock_id"],
                            "expires_at": run_at_utc + dt.timedelta(days=7),
                            "metadata": Json(
                                {
                                    "price_plan_id": plan["id"],
                                    "symbol": symbol,
                                    "company_name": plan["company_name"],
                                    "target_price": float(plan["target_price"]),
                                    "triggered_price": float(current_price),
                                    "direction": direction,
                                    "source": latest["source"],
                                    "price_at": latest["price_at"].isoformat(),
                                }
                            ),
                        },
                    )
                    triggered += 1
                    user_email = str(plan.get("user_email") or "").strip()
                    if plan.get("email_on_trigger") and user_email:
                        try:
                            send_price_plan_email(plan, symbol=symbol, current_price=current_price, latest=latest)
                        except (Exception, SystemExit) as exc:
                            logging.error(
                                "Price plan email failed price_plan_id=%s user_id=%s email=%s error=%s",
                                plan["id"],
                                plan["user_id"],
                                user_email,
                                exc,
                            )
    return triggered


def run_daily_earnings_notifications(args: argparse.Namespace, run_at_utc: dt.datetime) -> None:
    global _last_earnings_notification_date
    if not earnings_notification_sync_is_due(run_at_utc):
        return

    local_date = run_at_utc.astimezone(PRAGUE_TZ).date()
    logging.info("Starting daily earnings notification sync local_date=%s", local_date.isoformat())
    try:
        config_path = Path(args.config)
        if not config_path.is_absolute():
            config_path = Path(__file__).resolve().parent / config_path
        config = load_yaml(config_path)
        client = fmp_client(config)
        updated_events = refresh_stock_earnings_events(client=client, today=local_date)
        inserted_notifications = create_earnings_notifications(local_date)
    except SystemExit as exc:
        logging.error("Daily earnings notification sync failed local_date=%s error=%s", local_date.isoformat(), exc)
        return
    except Exception:
        logging.exception("Daily earnings notification sync failed local_date=%s", local_date.isoformat())
        return

    _last_earnings_notification_date = local_date
    logging.info(
        "Daily earnings notification sync finished local_date=%s updated_events=%s inserted_notifications=%s",
        local_date.isoformat(),
        updated_events,
        inserted_notifications,
    )


def run_price_plan_notifications(args: argparse.Namespace, run_at_utc: dt.datetime) -> None:
    logging.info("Starting price plan notification sync")
    try:
        config_path = Path(args.config)
        if not config_path.is_absolute():
            config_path = Path(__file__).resolve().parent / config_path
        config = load_yaml(config_path)
        client = fmp_client(config)
        triggered = create_price_plan_notifications(client, run_at_utc)
    except SystemExit as exc:
        logging.error("Price plan notification sync failed error=%s", exc)
        return
    except Exception:
        logging.exception("Price plan notification sync failed")
        return

    logging.info("Price plan notification sync finished triggered=%s", triggered)


def run_scheduler_cycle(args: argparse.Namespace, run_at_utc: dt.datetime | None = None) -> None:
    run_at = (run_at_utc or dt.datetime.now(tz=UTC)).astimezone(UTC)
    lookback = dt.timedelta(minutes=args.lookback_minutes)
    logging.info("Scheduler cycle started run_at_utc=%s lookback=%s", run_at.isoformat(), lookback)

    run_daily_stock_sync(args, run_at)
    run_daily_earnings_notifications(args, run_at)
    run_price_plan_notifications(args, run_at)

    jobs = load_due_jobs(run_at, lookback)
    logging.info("Scheduler found %s due users", len(jobs))
    enqueue_report_runs(
        jobs=jobs,
        date_arg=args.date,
        config_path=args.config,
        skip_openai=args.skip_openai,
    )


def next_minutes(now: dt.datetime, minutes: int) -> dt.datetime:
    current = now.astimezone(UTC)

    current = current.replace(second=0, microsecond=0)

    next_minute = ((current.minute // minutes) + 1) * minutes

    return (
        current.replace(minute=0)
        + dt.timedelta(minutes=next_minute)
    ).astimezone(UTC)


def sleep_until(target: dt.datetime) -> None:
    seconds = max(0.0, (target - dt.datetime.now(tz=UTC)).total_seconds())
    logging.info("Sleeping %.0f seconds until next scheduler cycle at %s", seconds, target.isoformat())
    time.sleep(seconds)


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(asctime)s %(levelname)s %(message)s")
    load_dotenv_if_available()

    if args.once:
        run_scheduler_cycle(args)
        return 0

    if args.run_immediately:
        run_scheduler_cycle(args)

    while True:
        target = next_minutes(dt.datetime.now(tz=UTC), minutes=SCHEDULER_INTERVAL_MINS)
        sleep_until(target)
        run_scheduler_cycle(args, run_at_utc=target)


if __name__ == "__main__":
    raise SystemExit(main())
