from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
import time
import traceback
from typing import Any

from psycopg.rows import dict_row
from psycopg.types.json import Json

from database import connection
from deep_research import DEEP_RESEARCH_MODEL, generate_deep_research


try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


if load_dotenv is not None:
    load_dotenv()


logging.basicConfig(
    level=os.getenv("DEEP_RESEARCH_WORKER_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s [deep-research-worker] %(message)s",
)
logger = logging.getLogger("deep_research_worker")


def claim_next_run() -> dict[str, Any] | None:
    with connection(row_factory=dict_row) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                select
                    research_runs.id::text as id,
                    research_runs.user_id::text as user_id,
                    research_runs.stock_id::text as stock_id,
                    research_runs.model,
                    research_runs.request,
                    stocks.symbol,
                    stocks.company_name
                from public.research_runs
                join public.stocks on stocks.id = research_runs.stock_id
                where research_runs.status = 'queued'
                order by research_runs.created_at
                for update skip locked
                limit 1
                """
            )
            row = cursor.fetchone()
            if not row:
                return None
            cursor.execute(
                """
                update public.research_runs
                set status = 'running',
                    started_at = now(),
                    updated_at = now(),
                    progress_step = 'Starting deep research',
                    progress_pct = 2
                where id::text = %(id)s
                """,
                {"id": row["id"]},
            )
            claimed = dict(row)
            logger.info(
                "Claimed deep research run %s for %s (%s), user %s, stock %s.",
                claimed["id"],
                claimed["symbol"],
                claimed["company_name"],
                claimed["user_id"],
                claimed["stock_id"],
            )
            return claimed


def update_progress(run_id: str, step: str, pct: int) -> None:
    logger.info("Run %s progress %s%%: %s.", run_id, max(0, min(99, int(pct))), step)
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                update public.research_runs
                set progress_step = %s,
                    progress_pct = %s,
                    updated_at = now()
                where id::text = %s
                  and status = 'running'
                """,
                (step[:240], max(0, min(99, int(pct))), run_id),
            )


def parse_timestamp_or_none(value: Any) -> dt.datetime | dt.date | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            return dt.date.fromisoformat(text[:10])
        except ValueError:
            return None


def complete_run(run: dict[str, Any], result: dict[str, Any]) -> str:
    logger.info(
        "Persisting completed deep research run %s for %s, user %s.",
        run["id"],
        run["symbol"],
        run["user_id"],
    )
    with connection(row_factory=dict_row) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                insert into public.research_items (
                    user_id,
                    stock_id,
                    body,
                    research_type,
                    signal,
                    date_from,
                    date_to
                )
                values (
                    %(user_id)s,
                    %(stock_id)s,
                    %(body)s,
                    'deep_research',
                    %(signal)s,
                    null,
                    null
                )
                returning id::text
                """,
                {
                    "user_id": run["user_id"],
                    "stock_id": run["stock_id"],
                    "body": Json(result["body"]),
                    "signal": result.get("signal"),
                },
            )
            research_item_id = str(cursor.fetchone()["id"])
            result["body"]["research_item_id"] = research_item_id

            cursor.execute(
                "update public.research_items set body = %(body)s where id::text = %(id)s",
                {"body": Json(result["body"]), "id": research_item_id},
            )

            for source in result.get("sources") or []:
                cursor.execute(
                    """
                    insert into public.research_sources (
                        research_item_id,
                        research_run_id,
                        user_id,
                        stock_id,
                        source_key,
                        source_type,
                        title,
                        url,
                        publisher,
                        published_at,
                        metadata,
                        excerpt
                    )
                    values (
                        %(research_item_id)s,
                        %(research_run_id)s,
                        %(user_id)s,
                        %(stock_id)s,
                        %(source_key)s,
                        %(source_type)s,
                        %(title)s,
                        %(url)s,
                        %(publisher)s,
                        %(published_at)s,
                        %(metadata)s,
                        %(excerpt)s
                    )
                    """,
                    {
                        "research_item_id": research_item_id,
                        "research_run_id": run["id"],
                        "user_id": run["user_id"],
                        "stock_id": run["stock_id"],
                        "source_key": source.get("source_key") or "",
                        "source_type": source.get("source_type") or "unknown",
                        "title": source.get("title"),
                        "url": source.get("url"),
                        "publisher": source.get("publisher"),
                        "published_at": parse_timestamp_or_none(source.get("published_at")),
                        "metadata": Json(source.get("metadata") or {}),
                        "excerpt": source.get("excerpt"),
                    },
                )

            for artifact in result.get("artifacts") or []:
                cursor.execute(
                    """
                    insert into public.research_artifacts (
                        research_item_id,
                        research_run_id,
                        user_id,
                        stock_id,
                        artifact_type,
                        title,
                        data
                    )
                    values (
                        %(research_item_id)s,
                        %(research_run_id)s,
                        %(user_id)s,
                        %(stock_id)s,
                        %(artifact_type)s,
                        %(title)s,
                        %(data)s
                    )
                    """,
                    {
                        "research_item_id": research_item_id,
                        "research_run_id": run["id"],
                        "user_id": run["user_id"],
                        "stock_id": run["stock_id"],
                        "artifact_type": artifact.get("artifact_type") or "artifact",
                        "title": artifact.get("title"),
                        "data": Json(artifact.get("data") or {}),
                    },
                )

            cursor.execute(
                """
                update public.research_runs
                set status = 'completed',
                    research_item_id = %(research_item_id)s,
                    usage_id = %(usage_id)s,
                    usage = %(usage)s,
                    progress_step = 'Deep research completed',
                    progress_pct = 100,
                    completed_at = now(),
                    updated_at = now()
                where id::text = %(id)s
                """,
                {
                    "id": run["id"],
                    "research_item_id": research_item_id,
                    "usage_id": result.get("usage_id"),
                    "usage": Json(result.get("usage") or {}),
                },
            )
            logger.info(
                "Completed deep research run %s. Created research item %s for %s. Sources: %s, artifacts: %s, usage_id: %s.",
                run["id"],
                research_item_id,
                run["symbol"],
                len(result.get("sources") or []),
                len(result.get("artifacts") or []),
                result.get("usage_id") or "none",
            )
            return research_item_id


def fail_run(run_id: str, error: str) -> None:
    logger.error("Deep research run %s failed: %s", run_id, error[:1000])
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                update public.research_runs
                set status = 'failed',
                    error = %s,
                    progress_step = 'Deep research failed',
                    completed_at = now(),
                    updated_at = now()
                where id::text = %s
                """,
                (error[:4000], run_id),
            )


def process_one() -> bool:
    run = claim_next_run()
    if not run:
        logger.debug("No queued deep research runs found.")
        return False
    request_payload = run.get("request") if isinstance(run.get("request"), dict) else {}
    relationship = request_payload.get("relationship") or "new"
    try:
        logger.info(
            "Starting deep research for %s (%s), relationship=%s, user=%s, model=%s.",
            str(run["symbol"]).upper(),
            run["company_name"],
            relationship,
            run["user_id"],
            run.get("model") or DEEP_RESEARCH_MODEL,
        )
        result = generate_deep_research(
            user_id=run["user_id"],
            stock_id=run["stock_id"],
            symbol=str(run["symbol"]).upper(),
            company_name=run["company_name"],
            relationship=relationship,
            model=run.get("model") or DEEP_RESEARCH_MODEL,
            progress=lambda step, pct: update_progress(run["id"], step, pct),
        )
        complete_run(run, result)
    except Exception as exc:
        logger.exception("Unhandled exception while processing deep research run %s.", run["id"])
        fail_run(run["id"], f"{exc}\n\n{traceback.format_exc()}")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Process queued Morning Alpha deep research jobs.")
    parser.add_argument("--once", action="store_true", help="Process at most one queued job and exit.")
    parser.add_argument(
        "--poll-seconds",
        type=float,
        default=float(os.getenv("DEEP_RESEARCH_WORKER_POLL_SECONDS", "5")),
        help="Seconds to sleep between queue polls.",
    )
    args = parser.parse_args()
    logger.info(
        "Deep research worker started. poll_seconds=%s, once=%s, log_level=%s.",
        args.poll_seconds,
        args.once,
        logging.getLevelName(logger.getEffectiveLevel()),
    )

    while True:
        processed = process_one()
        if args.once:
            logger.info("Deep research worker exiting after one poll because --once was set.")
            break
        if not processed:
            time.sleep(max(0.5, args.poll_seconds))


if __name__ == "__main__":
    main()
