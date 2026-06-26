from __future__ import annotations

import datetime as dt
import html
import json
import os
import re
from html.parser import HTMLParser
from typing import Any

from database import connection


DEFAULT_MAX_CONTEXT_ITEMS_PER_TICKER = 3
DEFAULT_MAX_MEMORY_ITEMS_PER_STOCK = 30
DEFAULT_MEMORY_LOOKBACK_DAYS = 365
DEFAULT_MEMORY_MODEL = "gpt-4.1-mini"
STOPWORDS = {
    "about",
    "after",
    "again",
    "also",
    "from",
    "have",
    "into",
    "more",
    "that",
    "the",
    "their",
    "this",
    "with",
    "would",
}
SKIP_LABELS = {"no_action", "no_material_change", "needs_more_evidence"}
STORE_LABELS = {
    "monitor",
    "review_thesis",
    "review_valuation",
    "deeper_analysis_needed",
    "positive_signal",
    "negative_signal",
    "mixed_signal",
}


def clean_text(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def truncate(value: Any, max_length: int = 900) -> str:
    text = clean_text(value)
    if len(text) <= max_length:
        return text
    return text[: max_length - 1].rstrip() + "..."


def tokenize(value: Any) -> list[str]:
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9\-]{2,}", str(value or "").lower())
    return [word for word in words if word not in STOPWORDS]


def unique_strings(values: list[Any], limit: int | None = None) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        text = clean_text(value)
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        output.append(text)
        if limit and len(output) >= limit:
            break
    return output


def normalize_theme(value: Any) -> str:
    words = tokenize(value)
    normalized = "_".join(words[:10])
    return normalized or "company_memory"


def normalize_importance(value: Any, *, thesis_linked: bool = False) -> str:
    if thesis_linked:
        return "high"
    importance = str(value or "").strip().lower()
    return "high" if importance == "high" else "medium"


def memory_config(config: dict[str, Any]) -> dict[str, Any]:
    raw = config.get("company_memory") if isinstance(config.get("company_memory"), dict) else {}
    return {
        "enabled": bool(raw.get("enabled", True)),
        "model": str(raw.get("model") or config.get("openai", {}).get("memory_model") or DEFAULT_MEMORY_MODEL),
        "max_context_items_per_ticker": int(raw.get("max_context_items_per_ticker", DEFAULT_MAX_CONTEXT_ITEMS_PER_TICKER)),
        "max_memory_items_per_stock": int(raw.get("max_memory_items_per_stock", DEFAULT_MAX_MEMORY_ITEMS_PER_STOCK)),
        "lookback_days": int(raw.get("lookback_days", DEFAULT_MEMORY_LOOKBACK_DAYS)),
        "shortlist_size": int(raw.get("shortlist_size", 8)),
    }


def stock_ids_by_ticker(context: dict[str, Any]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for section in ("portfolio", "watchlist"):
        for item in context.get(section, []):
            ticker = str(item.get("ticker") or "").upper()
            stock_id = str(item.get("stock_id") or "")
            if ticker and stock_id:
                mapping[ticker] = stock_id
    return mapping


def thesis_by_ticker(context: dict[str, Any]) -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    for section in ("portfolio", "watchlist"):
        for item in context.get(section, []):
            ticker = str(item.get("ticker") or "").upper()
            if ticker:
                mapping[ticker] = item.get("thesis") if isinstance(item.get("thesis"), dict) else {}
    return mapping


def item_text_for_matching(item: dict[str, Any]) -> str:
    parts = [
        item.get("ticker"),
        item.get("headline"),
        item.get("title"),
        item.get("why_it_matters"),
        item.get("reason"),
        item.get("rationale"),
        item.get("portfolio_relevance"),
        item.get("latest_development"),
        item.get("description"),
        item.get("theme"),
    ]
    if isinstance(item.get("article_summary"), list):
        parts.extend(item["article_summary"])
    if isinstance(item.get("thesis_points_affected"), list):
        parts.extend(item["thesis_points_affected"])
    return clean_text(" ".join(str(part or "") for part in parts))


def memory_text(row: dict[str, Any]) -> str:
    parts = [
        row.get("theme"),
        row.get("description"),
        row.get("latest_development"),
        " ".join(row.get("keywords") or []),
        " ".join(row.get("thesis_points") or []),
    ]
    return clean_text(" ".join(str(part or "") for part in parts))


def memory_similarity_score(item: dict[str, Any], memory: dict[str, Any], today: dt.date | None = None) -> float:
    item_terms = set(tokenize(item_text_for_matching(item)))
    memory_terms = set(tokenize(memory_text(memory)))
    if not item_terms or not memory_terms:
        return 0.0
    overlap = item_terms.intersection(memory_terms)
    score = len(overlap) * 4.0
    if memory.get("importance") == "high":
        score += 2.0
    if memory.get("thesis_linked"):
        score += 2.0
    last_seen = memory.get("last_seen_at")
    if today and hasattr(last_seen, "toordinal"):
        age_days = max((today - last_seen).days, 0)
        if age_days <= 30:
            score += 2.0
        elif age_days <= 90:
            score += 1.0
    return score


def shortlist_memories(
    item: dict[str, Any],
    memories: list[dict[str, Any]],
    *,
    today: dt.date | None = None,
    limit: int = 8,
    min_score: float = 4.0,
) -> list[dict[str, Any]]:
    scored = [
        (memory_similarity_score(item, memory, today), memory)
        for memory in memories
        if str(memory.get("stock_id") or "") == str(item.get("stock_id") or "")
    ]
    scored = [(score, memory) for score, memory in scored if score >= min_score]
    scored.sort(key=lambda pair: pair[0], reverse=True)
    output = []
    for score, memory in scored[:limit]:
        copy = dict(memory)
        copy["similarity_score"] = round(score, 2)
        output.append(copy)
    return output


def load_memories_for_stocks(
    user_id: str,
    stock_ids: list[str],
    *,
    lookback_days: int = DEFAULT_MEMORY_LOOKBACK_DAYS,
) -> list[dict[str, Any]]:
    if not stock_ids:
        return []
    try:
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise RuntimeError("Missing dependency 'psycopg'. Install dependencies with: pip install -r requirements.txt") from exc

    cutoff = dt.date.today() - dt.timedelta(days=lookback_days)
    with connection(row_factory=dict_row) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                select
                    company_memory_items.id::text as id,
                    company_memory_items.user_id::text as user_id,
                    company_memory_items.stock_id::text as stock_id,
                    stocks.symbol,
                    company_memory_items.theme,
                    company_memory_items.normalized_theme,
                    company_memory_items.description,
                    company_memory_items.latest_development,
                    company_memory_items.thesis_points,
                    company_memory_items.thesis_linked,
                    company_memory_items.keywords,
                    company_memory_items.source_urls,
                    company_memory_items.last_source_url,
                    company_memory_items.importance,
                    company_memory_items.status,
                    company_memory_items.evidence_count,
                    company_memory_items.first_seen_at,
                    company_memory_items.last_seen_at
                from public.company_memory_items
                join public.stocks on stocks.id = company_memory_items.stock_id
                where company_memory_items.user_id = %(user_id)s
                  and company_memory_items.stock_id = any(%(stock_ids)s::uuid[])
                  and company_memory_items.status = 'active'
                  and company_memory_items.last_seen_at >= %(cutoff)s
                order by company_memory_items.importance desc, company_memory_items.last_seen_at desc
                """,
                {"user_id": user_id, "stock_ids": stock_ids, "cutoff": cutoff},
            )
            return [dict(row) for row in cursor.fetchall()]


def build_company_memory_context(
    *,
    user_id: str,
    context: dict[str, Any],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    settings = memory_config(config)
    if not settings["enabled"]:
        return []
    stock_map = stock_ids_by_ticker(context)
    memories = load_memories_for_stocks(
        user_id,
        list(stock_map.values()),
        lookback_days=settings["lookback_days"],
    )
    selected_by_id: dict[str, dict[str, Any]] = {}
    today = dt.date.fromisoformat(str(context.get("report_date"))) if context.get("report_date") else dt.date.today()
    news_items = [item for item in context.get("ranked_news", []) if item.get("ticker") in stock_map]
    for news in news_items:
        item = {
            "ticker": news.get("ticker"),
            "stock_id": stock_map.get(str(news.get("ticker") or "").upper()),
            "headline": news.get("title"),
            "why_it_matters": news.get("snippet"),
        }
        for memory in shortlist_memories(item, memories, today=today, limit=2, min_score=4.0):
            selected_by_id[memory["id"]] = memory

    by_ticker: dict[str, list[dict[str, Any]]] = {}
    for memory in selected_by_id.values():
        by_ticker.setdefault(str(memory.get("symbol") or "").upper(), []).append(memory)

    output: list[dict[str, Any]] = []
    for ticker, rows in by_ticker.items():
        rows.sort(key=lambda row: (row.get("importance") == "high", row.get("last_seen_at")), reverse=True)
        for row in rows[: settings["max_context_items_per_ticker"]]:
            output.append(
                {
                    "ticker": ticker,
                    "memory_id": row["id"],
                    "theme": row["theme"],
                    "description": truncate(row["description"], 420),
                    "latest_development": truncate(row.get("latest_development"), 260),
                    "importance": row["importance"],
                    "thesis_points": row.get("thesis_points") or [],
                    "first_seen_at": row["first_seen_at"].isoformat() if hasattr(row["first_seen_at"], "isoformat") else row["first_seen_at"],
                    "last_seen_at": row["last_seen_at"].isoformat() if hasattr(row["last_seen_at"], "isoformat") else row["last_seen_at"],
                    "instruction": "Use only as historical context. Treat today's article as duplicate coverage only if it adds no new facts; treat it as a development only if today's article adds new evidence.",
                }
            )
    return output


def report_memory_candidates(report: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
    stock_map = stock_ids_by_ticker(context)
    thesis_map = thesis_by_ticker(context)
    thesis_impact_by_ticker = {
        str(item.get("ticker") or "").upper(): item
        for item in report.get("thesis_impact", [])
        if isinstance(item, dict) and item.get("ticker")
    }
    candidates = []
    for section in ("portfolio_news", "watchlist_news"):
        for item in report.get(section, []):
            if not isinstance(item, dict):
                continue
            ticker = str(item.get("ticker") or "").upper()
            stock_id = stock_map.get(ticker)
            label = str(item.get("attention_label") or "").strip().lower()
            if not ticker or not stock_id or label in SKIP_LABELS or label not in STORE_LABELS:
                continue
            thesis_impact = thesis_impact_by_ticker.get(ticker) if section == "portfolio_news" else None
            thesis_points = []
            if thesis_impact and isinstance(thesis_impact.get("thesis_points_affected"), list):
                thesis_points = thesis_impact["thesis_points_affected"]
            thesis_linked = bool(thesis_impact)
            importance = normalize_importance(item.get("importance"), thesis_linked=thesis_linked)
            if importance not in {"medium", "high"}:
                continue
            if label == "monitor" and importance != "high" and section == "portfolio_news":
                # Store monitor items only when they are at least medium by validation; this is already true here.
                pass
            text = item_text_for_matching({**item, **(thesis_impact or {})})
            keywords = unique_strings(tokenize(text), limit=12)
            candidates.append(
                {
                    "ticker": ticker,
                    "stock_id": stock_id,
                    "section": section,
                    "headline": clean_text(item.get("headline")),
                    "summary": truncate(item.get("why_it_matters") or text, 900),
                    "article_summary": item.get("article_summary") if isinstance(item.get("article_summary"), list) else [],
                    "attention_label": label,
                    "importance": importance,
                    "source_url": clean_text(item.get("source_url") or item.get("url")),
                    "source": clean_text(item.get("source")),
                    "thesis_linked": thesis_linked,
                    "thesis_points": unique_strings(thesis_points, limit=8),
                    "thesis": thesis_map.get(ticker) or {},
                    "keywords": keywords,
                    "report_text": truncate(text, 1400),
                }
            )
    return candidates


def compact_memory_for_prompt(memory: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": memory["id"],
        "theme": memory.get("theme"),
        "description": truncate(memory.get("description"), 500),
        "latest_development": truncate(memory.get("latest_development"), 300),
        "keywords": (memory.get("keywords") or [])[:12],
        "importance": memory.get("importance"),
        "thesis_points": (memory.get("thesis_points") or [])[:8],
        "first_seen_at": memory.get("first_seen_at").isoformat() if hasattr(memory.get("first_seen_at"), "isoformat") else memory.get("first_seen_at"),
        "last_seen_at": memory.get("last_seen_at").isoformat() if hasattr(memory.get("last_seen_at"), "isoformat") else memory.get("last_seen_at"),
        "similarity_score": memory.get("similarity_score"),
    }


def classify_memory_updates_with_gpt(
    *,
    user_id: str,
    items: list[dict[str, Any]],
    memories_by_item: list[list[dict[str, Any]]],
    config: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    if not items or not os.getenv("OPENAI_API_KEY"):
        return [], None
    from openai import OpenAI
    from report import log_openai_usage, openai_usage_summary, parse_model_json

    settings = memory_config(config)
    payload = {
        "instructions": [
            "Decide whether each report item should create, update, or ignore company memory.",
            "Match only when today's item and memory describe the same business issue. Same broad category is not enough.",
            "Memory is historical context, not evidence. Do not infer causality unless today's item states it.",
            "Create new memory only for topics likely to be useful in future reports.",
            "Ignore low-value, one-off, generic, or immaterial items.",
            "If today's item touches the user's thesis, importance must be high.",
        ],
        "items": [
            {
                "index": index,
                "ticker": item["ticker"],
                "headline": item["headline"],
                "summary": item["summary"],
                "article_summary": item["article_summary"][:4],
                "attention_label": item["attention_label"],
                "importance": item["importance"],
                "thesis_linked": item["thesis_linked"],
                "thesis_points": item["thesis_points"],
                "keywords": item["keywords"],
                "candidate_memories": [compact_memory_for_prompt(memory) for memory in memories_by_item[index]],
            }
            for index, item in enumerate(items)
        ],
        "output_schema": {
            "items": [
                {
                    "index": "number",
                    "decision": "update_existing|create_new|ignore",
                    "matched_memory_id": "string|null",
                    "relationship": "duplicate_coverage|follow_up|new_evidence|unrelated",
                    "confidence": "low|medium|high",
                    "theme": "short reusable theme",
                    "description": "stable memory description for future report context",
                    "latest_development": "what changed in this report item",
                    "keywords": ["keyword"],
                    "thesis_points": ["specific thesis point affected"],
                    "importance": "medium|high",
                    "status": "active|stale|resolved",
                    "reason": "short explanation",
                }
            ]
        },
    }
    response = OpenAI(timeout=90).responses.create(
        model=settings["model"],
        input=[
            {"role": "system", "content": "Return valid JSON only. You are a conservative investment memory classifier."},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
    )
    usage = openai_usage_summary(response, settings["model"], config)
    usage_id = log_openai_usage(user_id, "company_memory_upsert", usage)
    if usage_id:
        usage["usage_id"] = usage_id
    parsed = parse_model_json(response.output_text)
    decisions = parsed.get("items") if isinstance(parsed.get("items"), list) else []
    return [decision for decision in decisions if isinstance(decision, dict)], usage


def fallback_memory_decisions(items: list[dict[str, Any]], memories_by_item: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    decisions = []
    for index, item in enumerate(items):
        memories = memories_by_item[index]
        if memories:
            matched = memories[0]
            decisions.append(
                {
                    "index": index,
                    "decision": "update_existing",
                    "matched_memory_id": matched["id"],
                    "relationship": "follow_up",
                    "confidence": "medium",
                    "theme": matched.get("theme") or item.get("headline") or item["ticker"],
                    "description": matched.get("description") or item["summary"],
                    "latest_development": item["summary"],
                    "keywords": item.get("keywords") or [],
                    "thesis_points": item.get("thesis_points") or [],
                    "importance": item["importance"],
                    "status": "active",
                }
            )
        else:
            decisions.append(
                {
                    "index": index,
                    "decision": "create_new",
                    "matched_memory_id": None,
                    "relationship": "new_evidence",
                    "confidence": "medium",
                    "theme": item.get("headline") or item["ticker"],
                    "description": item["summary"],
                    "latest_development": item["summary"],
                    "keywords": item.get("keywords") or [],
                    "thesis_points": item.get("thesis_points") or [],
                    "importance": item["importance"],
                    "status": "active",
                }
            )
    return decisions


def prune_company_memory(cursor: Any, user_id: str, stock_id: str, max_items: int) -> None:
    cursor.execute(
        """
        delete from public.company_memory_items
        where id in (
            select id
            from (
                select
                    id,
                    row_number() over (
                        partition by user_id, stock_id
                        order by
                            case when status = 'active' then 0 else 1 end,
                            case when importance = 'high' then 0 else 1 end,
                            last_seen_at desc,
                            updated_at desc
                    ) as row_num
                from public.company_memory_items
                where user_id = %(user_id)s
                  and stock_id = %(stock_id)s
            ) ranked
            where row_num > %(max_items)s
        )
        """,
        {"user_id": user_id, "stock_id": stock_id, "max_items": max_items},
    )


def memory_decision_effect(decision: dict[str, Any] | None, candidate_ids: set[str]) -> str:
    if not decision:
        return "ignored"
    action = str(decision.get("decision") or "ignore").strip().lower()
    confidence = str(decision.get("confidence") or "low").strip().lower()
    if action == "ignore" or confidence == "low":
        return "ignored"
    matched_id = str(decision.get("matched_memory_id") or "")
    if action == "update_existing" and matched_id in candidate_ids:
        return "updated"
    if action == "create_new" and confidence in {"medium", "high"}:
        return "created"
    return "ignored"


def apply_memory_decisions(
    *,
    user_id: str,
    report_id: str | None,
    report_date: dt.date,
    items: list[dict[str, Any]],
    memories_by_item: list[list[dict[str, Any]]],
    decisions: list[dict[str, Any]],
    config: dict[str, Any],
    dry_run: bool = False,
) -> dict[str, int]:
    from psycopg.types.json import Json

    settings = memory_config(config)
    decisions_by_index: dict[int, dict[str, Any]] = {}
    for decision in decisions:
        try:
            decisions_by_index[int(decision.get("index"))] = decision
        except (TypeError, ValueError):
            continue
    summary = {"created": 0, "updated": 0, "ignored": 0}
    if dry_run:
        for index in range(len(items)):
            candidate_ids = {str(memory["id"]) for memory in memories_by_item[index]}
            summary[memory_decision_effect(decisions_by_index.get(index), candidate_ids)] += 1
        return summary

    with connection() as conn:
        with conn.cursor() as cursor:
            for index, item in enumerate(items):
                decision = decisions_by_index.get(index)
                candidate_ids = {str(memory["id"]) for memory in memories_by_item[index]}
                effect = memory_decision_effect(decision, candidate_ids)
                if effect == "ignored":
                    summary["ignored"] += 1
                    continue

                action = str(decision.get("decision") or "ignore").strip().lower()
                matched_id = str(decision.get("matched_memory_id") or "")
                theme = truncate(decision.get("theme") or item.get("headline") or item["ticker"], 140)
                normalized_theme = normalize_theme(theme)
                description = truncate(decision.get("description") or item["summary"], 1200)
                latest_development = truncate(decision.get("latest_development") or item["summary"], 800)
                thesis_points = unique_strings((decision.get("thesis_points") or []) + item.get("thesis_points", []), limit=10)
                keywords = unique_strings((decision.get("keywords") or []) + item.get("keywords", []), limit=16)
                importance = normalize_importance(decision.get("importance") or item["importance"], thesis_linked=item.get("thesis_linked", False))
                status = str(decision.get("status") or "active").strip().lower()
                status = status if status in {"active", "stale", "resolved"} else "active"
                source_urls = unique_strings([item.get("source_url")], limit=20)

                if action == "update_existing" and matched_id in candidate_ids:
                    cursor.execute(
                        """
                        select source_urls
                        from public.company_memory_items
                        where id::text = %(id)s
                          and user_id = %(user_id)s
                          and stock_id = %(stock_id)s
                        """,
                        {"id": matched_id, "user_id": user_id, "stock_id": item["stock_id"]},
                    )
                    row = cursor.fetchone()
                    if not row:
                        summary["ignored"] += 1
                        continue
                    existing_urls = list(row[0] or [])
                    merged_urls = unique_strings(existing_urls + source_urls, limit=20)
                    cursor.execute(
                        """
                        update public.company_memory_items
                        set
                            theme = %(theme)s,
                            description = %(description)s,
                            latest_development = %(latest_development)s,
                            thesis_points = %(thesis_points)s,
                            thesis_linked = company_memory_items.thesis_linked or %(thesis_linked)s,
                            keywords = %(keywords)s,
                            source_urls = %(source_urls)s,
                            last_source_url = %(last_source_url)s,
                            importance = case
                                when company_memory_items.importance = 'high' or %(importance)s = 'high' then 'high'
                                else 'medium'
                            end,
                            status = %(status)s,
                            evidence_count = company_memory_items.evidence_count + 1,
                            last_seen_at = %(last_seen_at)s,
                            last_report_id = %(last_report_id)s
                        where id::text = %(id)s
                          and user_id = %(user_id)s
                          and stock_id = %(stock_id)s
                        """,
                        {
                            "id": matched_id,
                            "user_id": user_id,
                            "stock_id": item["stock_id"],
                            "theme": theme,
                            "description": description,
                            "latest_development": latest_development,
                            "thesis_points": Json(thesis_points),
                            "thesis_linked": bool(item.get("thesis_linked")),
                            "keywords": Json(keywords),
                            "source_urls": Json(merged_urls),
                            "last_source_url": item.get("source_url") or None,
                            "importance": importance,
                            "status": status,
                            "last_seen_at": report_date,
                            "last_report_id": report_id,
                        },
                    )
                    summary["updated"] += 1
                elif effect == "created":
                    cursor.execute(
                        """
                        insert into public.company_memory_items (
                            user_id,
                            stock_id,
                            last_report_id,
                            theme,
                            normalized_theme,
                            description,
                            latest_development,
                            thesis_points,
                            thesis_linked,
                            keywords,
                            source_urls,
                            last_source_url,
                            importance,
                            status,
                            first_seen_at,
                            last_seen_at
                        )
                        values (
                            %(user_id)s,
                            %(stock_id)s,
                            %(last_report_id)s,
                            %(theme)s,
                            %(normalized_theme)s,
                            %(description)s,
                            %(latest_development)s,
                            %(thesis_points)s,
                            %(thesis_linked)s,
                            %(keywords)s,
                            %(source_urls)s,
                            %(last_source_url)s,
                            %(importance)s,
                            %(status)s,
                            %(first_seen_at)s,
                            %(last_seen_at)s
                        )
                        on conflict (user_id, stock_id, normalized_theme) do update
                        set
                            description = excluded.description,
                            latest_development = excluded.latest_development,
                            thesis_points = excluded.thesis_points,
                            thesis_linked = public.company_memory_items.thesis_linked or excluded.thesis_linked,
                            keywords = excluded.keywords,
                            source_urls = (
                                select coalesce(jsonb_agg(distinct elem.value), '[]'::jsonb)
                                from jsonb_array_elements_text(public.company_memory_items.source_urls || excluded.source_urls) as elem(value)
                            ),
                            last_source_url = excluded.last_source_url,
                            importance = case
                                when public.company_memory_items.importance = 'high' or excluded.importance = 'high' then 'high'
                                else 'medium'
                            end,
                            status = excluded.status,
                            evidence_count = public.company_memory_items.evidence_count + 1,
                            last_seen_at = excluded.last_seen_at,
                            last_report_id = excluded.last_report_id
                        returning (xmax = 0) as inserted
                        """,
                        {
                            "user_id": user_id,
                            "stock_id": item["stock_id"],
                            "last_report_id": report_id,
                            "theme": theme,
                            "normalized_theme": normalized_theme,
                            "description": description,
                            "latest_development": latest_development,
                            "thesis_points": Json(thesis_points),
                            "thesis_linked": bool(item.get("thesis_linked")),
                            "keywords": Json(keywords),
                            "source_urls": Json(source_urls),
                            "last_source_url": item.get("source_url") or None,
                            "importance": importance,
                            "status": status,
                            "first_seen_at": report_date,
                            "last_seen_at": report_date,
                        },
                    )
                    inserted = bool(cursor.fetchone()[0])
                    summary["created" if inserted else "updated"] += 1
                else:
                    summary["ignored"] += 1
                prune_company_memory(cursor, user_id, item["stock_id"], settings["max_memory_items_per_stock"])
    return summary


def update_company_memory_from_report(
    *,
    user_id: str,
    report: dict[str, Any],
    context: dict[str, Any],
    config: dict[str, Any],
    report_id: str | None,
    report_date: dt.date,
    dry_run: bool = False,
) -> dict[str, Any]:
    settings = memory_config(config)
    if not settings["enabled"]:
        return {"created": 0, "updated": 0, "ignored": 0, "usage": None}
    items = report_memory_candidates(report, context)
    if not items:
        return {"created": 0, "updated": 0, "ignored": 0, "usage": None}
    memories = load_memories_for_stocks(
        user_id,
        unique_strings([item["stock_id"] for item in items]),
        lookback_days=settings["lookback_days"],
    )
    memories_by_item = [
        shortlist_memories(item, memories, today=report_date, limit=settings["shortlist_size"])
        for item in items
    ]
    decisions, usage = classify_memory_updates_with_gpt(
        user_id=user_id,
        items=items,
        memories_by_item=memories_by_item,
        config=config,
    )
    if not decisions:
        decisions = fallback_memory_decisions(items, memories_by_item)
    summary = apply_memory_decisions(
        user_id=user_id,
        report_id=report_id,
        report_date=report_date,
        items=items,
        memories_by_item=memories_by_item,
        decisions=decisions,
        config=config,
        dry_run=dry_run,
    )
    return {**summary, "usage": usage}


class ReportTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []
        self.links: list[str] = []
        self._buffer: list[str] = []
        self._href: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            attrs_dict = dict(attrs)
            self._href = attrs_dict.get("href")

    def handle_data(self, data: str) -> None:
        text = clean_text(data)
        if text:
            self._buffer.append(text)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href:
            self.links.append(self._href)
            self._href = None
        if tag in {"h1", "h2", "h3", "h4", "p", "li"} and self._buffer:
            self.lines.append(clean_text(" ".join(self._buffer)))
            self._buffer = []

    def text(self) -> str:
        if self._buffer:
            self.lines.append(clean_text(" ".join(self._buffer)))
            self._buffer = []
        return "\n".join(line for line in self.lines if line)


def report_html_to_text(report_html: str) -> tuple[str, list[str]]:
    parser = ReportTextParser()
    parser.feed(report_html or "")
    return parser.text(), unique_strings(parser.links, limit=50)


def extract_backfill_report_with_gpt(
    *,
    user_id: str,
    report_html: str,
    report_date: dt.date,
    known_stocks: dict[str, str],
    config: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    text, links = report_html_to_text(report_html)
    if not text or not os.getenv("OPENAI_API_KEY"):
        return {"report_date": report_date.isoformat(), "portfolio_news": [], "watchlist_news": [], "thesis_impact": []}, None
    from openai import OpenAI
    from report import log_openai_usage, openai_usage_summary, parse_model_json

    settings = memory_config(config)
    payload = {
        "task": "Extract memory-worthy company items from this Morning Alpha report text.",
        "known_tickers": sorted(known_stocks)[:300],
        "report_date": report_date.isoformat(),
        "rules": [
            "Extract only medium/high relevance company-specific items.",
            "Ignore low relevance, no action, routine legal PR, generic sources, and market sections not tied to a company.",
            "Use only tickers present in known_tickers.",
        ],
        "report_text": truncate(text, 24000),
        "source_urls": links,
        "output_schema": {
            "portfolio_news": [
                {
                    "ticker": "string",
                    "headline": "string",
                    "why_it_matters": "string",
                    "article_summary": ["string"],
                    "attention_label": "monitor|review_thesis|review_valuation|deeper_analysis_needed",
                    "importance": "medium|high",
                    "source_url": "string",
                }
            ],
            "watchlist_news": [
                {
                    "ticker": "string",
                    "headline": "string",
                    "why_it_matters": "string",
                    "article_summary": ["string"],
                    "attention_label": "positive_signal|negative_signal|mixed_signal",
                    "importance": "medium|high",
                    "source_url": "string",
                }
            ],
            "thesis_impact": [
                {
                    "ticker": "string",
                    "rationale": "string",
                    "thesis_points_affected": ["string"],
                    "monitor_next": "string",
                }
            ],
        },
    }
    response = OpenAI(timeout=90).responses.create(
        model=settings["model"],
        input=[
            {"role": "system", "content": "Return valid JSON only. Extract conservative company memory candidates."},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
    )
    usage = openai_usage_summary(response, settings["model"], config)
    usage_id = log_openai_usage(user_id, "company_memory_backfill_extract", usage)
    if usage_id:
        usage["usage_id"] = usage_id
    parsed = parse_model_json(response.output_text)
    parsed["report_date"] = report_date.isoformat()
    return parsed, usage


def load_user_stock_map(user_id: str) -> dict[str, str]:
    try:
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise RuntimeError("Missing dependency 'psycopg'. Install dependencies with: pip install -r requirements.txt") from exc

    with connection(row_factory=dict_row) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                select distinct stocks.symbol, stocks.id::text as stock_id
                from public.stocks
                where exists (
                    select 1 from public.portfolio_items
                    where portfolio_items.user_id = %(user_id)s
                      and portfolio_items.stock_id = stocks.id
                )
                or exists (
                    select 1 from public.watchlist_items
                    where watchlist_items.user_id = %(user_id)s
                      and watchlist_items.stock_id = stocks.id
                )
                or exists (
                    select 1 from public.notes
                    where notes.user_id = %(user_id)s
                      and notes.stock_id = stocks.id
                )
                order by stocks.symbol
                """,
                {"user_id": user_id},
            )
            return {str(row["symbol"]).upper(): str(row["stock_id"]) for row in cursor.fetchall()}
