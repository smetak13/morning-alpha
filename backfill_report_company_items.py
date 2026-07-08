from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

if load_dotenv is not None:
    load_dotenv(Path(__file__).resolve().parent / ".env")

from database import connection


class CompanyCardExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.cards: list[dict[str, str]] = []
        self._capturing = False
        self._depth = 0
        self._chunks: list[str] = []
        self._attrs: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {name: value or "" for name, value in attrs}
        class_name = attr_map.get("class", "")
        if tag == "div" and "company-card" in class_name.split() and not self._capturing:
            self._capturing = True
            self._depth = 1
            self._chunks = [self.get_starttag_text() or ""]
            self._attrs = attr_map
            return
        if self._capturing:
            if tag == "div":
                self._depth += 1
            self._chunks.append(self.get_starttag_text() or "")

    def handle_endtag(self, tag: str) -> None:
        if not self._capturing:
            return
        self._chunks.append(f"</{tag}>")
        if tag == "div":
            self._depth -= 1
            if self._depth <= 0:
                self.cards.append({"attrs": json.dumps(self._attrs), "html": "".join(self._chunks)})
                self._capturing = False
                self._chunks = []
                self._attrs = {}

    def handle_data(self, data: str) -> None:
        if self._capturing:
            self._chunks.append(data)

    def handle_entityref(self, name: str) -> None:
        if self._capturing:
            self._chunks.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if self._capturing:
            self._chunks.append(f"&#{name};")


def tag_text(card_html: str, tag: str) -> list[str]:
    pattern = rf"<{tag}\b[^>]*>(.*?)</{tag}>"
    values = []
    for match in re.finditer(pattern, card_html, flags=re.IGNORECASE | re.DOTALL):
        text = html.unescape(re.sub(r"<[^>]+>", " ", match.group(1)))
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            values.append(text)
    return values


def first_attr(card_html: str, tag: str, attr: str) -> str:
    match = re.search(rf"<{tag}\b[^>]*\s{attr}=[\"']([^\"']+)[\"'][^>]*>", card_html, flags=re.IGNORECASE)
    return html.unescape(match.group(1)).strip() if match else ""


def clean_label_text(value: str, label: str) -> str:
    return re.sub(rf"^\s*{re.escape(label)}\s*:?\s*", "", value, flags=re.IGNORECASE).strip()


def parse_company_card(card: dict[str, str]) -> dict[str, Any] | None:
    attrs = json.loads(card["attrs"])
    card_id = attrs.get("id") or ""
    if card_id.startswith("portfolio-"):
        section = "portfolio"
    elif card_id.startswith("watchlist-"):
        section = "watchlist"
    else:
        return None

    card_html = card["html"]
    h3 = tag_text(card_html, "h3")
    h4 = tag_text(card_html, "h4")
    paragraphs = tag_text(card_html, "p")
    bullets = tag_text(card_html, "li")
    ticker = h3[0].upper() if h3 else ""
    headline = h4[0] if h4 else ""
    source_url = first_attr(card_html, "a", "href")
    if source_url.startswith("#memory-"):
        source_url = ""
    source_text = ""
    source_match = re.search(r"Full article(?:\s*-\s*([^<]+))?", card_html, flags=re.IGNORECASE)
    if source_match:
        source_text = html.unescape(source_match.group(1) or "").strip()

    why_it_matters = ""
    thesis_summary = ""
    thesis_points: list[str] = []
    monitor_next = ""
    for paragraph in paragraphs:
        if paragraph.lower().startswith("portfolio holding") or paragraph.lower().startswith("watchlist company"):
            continue
        if paragraph.lower().startswith("affected thesis points"):
            thesis_points = [
                item.strip()
                for item in clean_label_text(paragraph, "Affected thesis points").split(",")
                if item.strip()
            ]
            continue
        if paragraph.lower().startswith("monitor next"):
            monitor_next = clean_label_text(paragraph, "Monitor next")
            continue
        if paragraph.lower().startswith("full article"):
            continue
        if "Tracked theme:" in paragraph:
            continue
        if not why_it_matters:
            why_it_matters = paragraph
        elif not thesis_summary and "Thesis impact" in card_html:
            thesis_summary = paragraph

    return {
        "section": section,
        "ticker": ticker,
        "headline": headline,
        "why_it_matters": why_it_matters,
        "article_summary": bullets[:5],
        "source": source_text,
        "source_url": source_url,
        "thesis_summary": thesis_summary,
        "thesis_points_affected": thesis_points[:8],
        "monitor_next": monitor_next,
    }


def extract_cards(report_html: str) -> list[dict[str, Any]]:
    parser = CompanyCardExtractor()
    parser.feed(report_html or "")
    return [item for card in parser.cards if (item := parse_company_card(card))]


def stock_lookup(cursor: Any, user_id: str) -> dict[str, dict[str, str]]:
    cursor.execute(
        """
        select distinct stocks.id::text as stock_id, stocks.symbol, stocks.company_name
        from public.stocks
        left join public.portfolio_items on portfolio_items.stock_id = stocks.id and portfolio_items.user_id = %(user_id)s
        left join public.watchlist_items on watchlist_items.stock_id = stocks.id and watchlist_items.user_id = %(user_id)s
        left join public.notes on notes.stock_id = stocks.id and notes.user_id = %(user_id)s
        where portfolio_items.id is not null
           or watchlist_items.id is not null
           or notes.id is not null
        """,
        {"user_id": user_id},
    )
    return {
        str(row["symbol"]).upper(): {
            "stock_id": str(row["stock_id"]),
            "company_name": row["company_name"],
        }
        for row in cursor.fetchall()
    }


def backfill_report(cursor: Any, report: dict[str, Any], dry_run: bool) -> int:
    cards = extract_cards(report["html"])
    stocks = stock_lookup(cursor, str(report["user_id"]))
    rows = []
    for card in cards:
        stock = stocks.get(card["ticker"])
        if not stock:
            continue
        rows.append({**card, **stock})
    if dry_run:
        return len(rows)

    cursor.execute(
        "delete from public.report_company_items where report_id = %(report_id)s and user_id = %(user_id)s",
        {"report_id": report["id"], "user_id": report["user_id"]},
    )
    for row in rows:
        cursor.execute(
            """
            insert into public.report_company_items (
                user_id,
                report_id,
                stock_id,
                section,
                ticker,
                company_name,
                headline,
                why_it_matters,
                article_summary,
                source,
                source_url,
                thesis_summary,
                thesis_points_affected,
                monitor_next,
                metadata,
                report_date
            )
            values (
                %(user_id)s,
                %(report_id)s,
                %(stock_id)s,
                %(section)s,
                %(ticker)s,
                %(company_name)s,
                %(headline)s,
                %(why_it_matters)s,
                %(article_summary)s::jsonb,
                %(source)s,
                %(source_url)s,
                %(thesis_summary)s,
                %(thesis_points_affected)s::jsonb,
                %(monitor_next)s,
                '{}'::jsonb,
                %(report_date)s
            )
            on conflict (report_id, stock_id, section, (coalesce(nullif(source_url, ''), lower(coalesce(headline, '')))))
            do update set
                company_name = excluded.company_name,
                headline = excluded.headline,
                why_it_matters = excluded.why_it_matters,
                article_summary = excluded.article_summary,
                source = excluded.source,
                source_url = excluded.source_url,
                thesis_summary = excluded.thesis_summary,
                thesis_points_affected = excluded.thesis_points_affected,
                monitor_next = excluded.monitor_next,
                report_date = excluded.report_date,
                updated_at = now()
            """,
            {
                **row,
                "user_id": report["user_id"],
                "report_id": report["id"],
                "report_date": report["report_date"],
                "article_summary": json.dumps(row["article_summary"]),
                "thesis_points_affected": json.dumps(row["thesis_points_affected"]),
            },
        )
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill report_company_items from saved report HTML for all users.")
    parser.add_argument("--dry-run", action="store_true", help="Parse reports without writing rows.")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of reports to process.")
    parser.add_argument("--user-id", default=None, help="Optional single user_id filter.")
    args = parser.parse_args()

    from psycopg.rows import dict_row

    clauses = []
    params: dict[str, Any] = {}
    if args.user_id:
        clauses.append("user_id::text = %(user_id)s")
        params["user_id"] = args.user_id
    where_sql = f"where {' and '.join(clauses)}" if clauses else ""
    limit_sql = "limit %(limit)s" if args.limit else ""
    if args.limit:
        params["limit"] = args.limit

    with connection(row_factory=dict_row) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                select id, user_id, report_date, html
                from public.reports
                {where_sql}
                order by report_date asc, created_at asc
                {limit_sql}
                """,
                params,
            )
            reports = cursor.fetchall()
            total_items = 0
            for index, report in enumerate(reports, start=1):
                count = backfill_report(cursor, dict(report), args.dry_run)
                total_items += count
                date_value = report["report_date"]
                if isinstance(date_value, dt.date):
                    date_value = date_value.isoformat()
                print(f"[{index}/{len(reports)}] report={report['id']} date={date_value} items={count}")
            if args.dry_run:
                conn.rollback()
            print(f"Backfill complete reports={len(reports)} items={total_items} dry_run={args.dry_run}")


if __name__ == "__main__":
    main()
