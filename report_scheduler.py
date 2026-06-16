from __future__ import annotations

import os
import argparse
import datetime as dt
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from queue import Queue
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from database import connection
from report import load_dotenv_if_available, load_yaml, run_report_for_user
from sync_stocks import fmp_client, fetch_active_stocks, sync_stocks


DEFAULT_TIMEZONE = "Europe/Prague"
SCHEDULER_INTERVAL_MINS = int(os.getenv("SCHEDULER_INTERVAL_MINS", "30"))
UTC = dt.timezone.utc
PRAGUE_TZ = ZoneInfo(DEFAULT_TIMEZONE)
STOCK_SYNC_MIN_SYMBOL_COUNT = int(os.getenv("STOCK_SYNC_MIN_SYMBOL_COUNT", "10000"))
_last_stock_sync_date: dt.date | None = None


@dataclass(frozen=True)
class ScheduledReportJob:
    user_id: str
    email: str
    timezone: str
    report_scheduled_at: dt.time


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


def scheduled_time_is_due(
    *,
    report_scheduled_at: dt.time,
    timezone: str,
    run_at_utc: dt.datetime,
    lookback: dt.timedelta,
) -> bool:
    local_end = run_at_utc.astimezone(ZoneInfo(timezone))
    local_start = local_end - lookback

    for scheduled_date in {local_start.date(), local_end.date()}:
        scheduled_local = dt.datetime.combine(scheduled_date, report_scheduled_at, tzinfo=local_end.tzinfo)
        if local_start < scheduled_local <= local_end:
            return True
    return False


def report_delivery_is_enabled(*, timezone: str, run_at_utc: dt.datetime) -> bool:
    local_date = run_at_utc.astimezone(ZoneInfo(timezone)).date()
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
                    report_scheduled_at
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
        if not report_delivery_is_enabled(timezone=timezone, run_at_utc=run_at_utc):
            logging.debug(
                "Skipping scheduled report on weekend user_id=%s timezone=%s local_date=%s",
                row["id"],
                timezone,
                run_at_utc.astimezone(ZoneInfo(timezone)).date().isoformat(),
            )
            continue

        report_scheduled_at = coerce_time(row["report_scheduled_at"])
        if not scheduled_time_is_due(
            report_scheduled_at=report_scheduled_at,
            timezone=timezone,
            run_at_utc=run_at_utc,
            lookback=lookback,
        ):
            continue

        due_jobs.append(
            ScheduledReportJob(
                user_id=str(row["id"]),
                email=email,
                timezone=timezone,
                report_scheduled_at=report_scheduled_at,
            )
        )

    return due_jobs


def enqueue_jobs(jobs: list[ScheduledReportJob]) -> Queue[ScheduledReportJob]:
    queue: Queue[ScheduledReportJob] = Queue()
    for job in jobs:
        queue.put(job)
    return queue


def output_paths_for_job(job: ScheduledReportJob, run_at_utc: dt.datetime) -> dict[str, Path]:
    run_id = run_at_utc.strftime("%Y%m%dT%H%M%SZ")
    base = Path("out") / "scheduled" / run_id / job.user_id
    return {
        "context_json": base / "context.json",
        "output_json": base / "report.json",
        "usage_json": base / "usage.json",
        "output_html": base / "report.html",
    }


def process_queue(
    *,
    queue: Queue[ScheduledReportJob],
    run_at_utc: dt.datetime,
    date_arg: str,
    config_path: str,
    skip_openai: bool,
) -> None:
    total = queue.qsize()
    completed = 0
    failed = 0

    while not queue.empty():
        job = queue.get()
        logging.info(
            "Starting scheduled report user_id=%s email=%s scheduled_at=%s timezone=%s",
            job.user_id,
            job.email,
            job.report_scheduled_at.isoformat(timespec="minutes"),
            job.timezone,
        )
        try:
            paths = output_paths_for_job(job, run_at_utc)
            result = run_report_for_user(
                user_id=job.user_id,
                recipient_email=job.email,
                date_arg=date_arg,
                config_path=config_path,
                send_email_report=True,
                skip_openai=skip_openai,
                **paths,
            )
        except Exception:
            failed += 1
            logging.exception("Scheduled report failed user_id=%s email=%s", job.user_id, job.email)
        else:
            completed += 1
            logging.info("Scheduled report sent user_id=%s subject=%s", job.user_id, result["subject"])
        finally:
            queue.task_done()

    logging.info("Scheduler cycle finished total=%s completed=%s failed=%s", total, completed, failed)


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


def run_scheduler_cycle(args: argparse.Namespace, run_at_utc: dt.datetime | None = None) -> None:
    run_at = (run_at_utc or dt.datetime.now(tz=UTC)).astimezone(UTC)
    lookback = dt.timedelta(minutes=args.lookback_minutes)
    logging.info("Scheduler cycle started run_at_utc=%s lookback=%s", run_at.isoformat(), lookback)

    run_daily_stock_sync(args, run_at)

    jobs = load_due_jobs(run_at, lookback)
    logging.info("Scheduler found %s due users", len(jobs))
    queue = enqueue_jobs(jobs)
    process_queue(
        queue=queue,
        run_at_utc=run_at,
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
