from __future__ import annotations

import argparse
import datetime as dt
import email.message
import json
import math
import os
import re
import smtplib
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent
NY_TZ = ZoneInfo("America/New_York")
PRAGUE_TZ = ZoneInfo("Europe/Prague")

ATTENTION_LABELS = {
    "no_action",
    "monitor",
    "review_thesis",
    "review_valuation",
    "deeper_analysis_needed",
}

EVENT_KEYWORDS = {
    "earnings": ("earnings", "results", "quarter", "eps", "revenue", "profit", "margin"),
    "guidance": ("guidance", "forecast", "outlook", "raises forecast", "cuts forecast"),
    "m_and_a": ("acquisition", "acquire", "merger", "takeover", "buyout", "deal"),
    "regulation": ("regulation", "regulator", "antitrust", "ftc", "doj", "eu commission"),
    "lawsuit": ("lawsuit", "sues", "sued", "settlement", "court", "legal"),
    "buyback": ("buyback", "repurchase", "share repurchase"),
    "dividend": ("dividend", "payout"),
    "sec_filing": ("sec", "10-k", "10-q", "8-k", "filing"),
    "management": ("ceo", "cfo", "resigns", "appointed", "management"),
}

STOPWORDS = {
    "about",
    "after",
    "against",
    "from",
    "have",
    "into",
    "more",
    "over",
    "said",
    "says",
    "that",
    "their",
    "this",
    "with",
    "will",
    "would",
}


@dataclass(frozen=True)
class Holding:
    ticker: str
    position_size_pct: float
    thesis: dict[str, Any]


@dataclass(frozen=True)
class MarketData:
    ticker: str
    price_change_pct: float | None = None
    volume_ratio: float | None = None


@dataclass
class NewsItem:
    ticker: str | None
    title: str
    text: str
    url: str
    source: str
    published_at: str | None
    symbols: list[str]
    event_types: list[str]
    score: float = 0
    score_reasons: list[str] | None = None
    matched_thesis_terms: list[str] | None = None
    duplicate_source_count: int = 1
    price_change_pct: float | None = None
    volume_ratio: float | None = None


def require_dependency(module_name: str, install_name: str | None = None) -> Any:
    try:
        return __import__(module_name)
    except ImportError as exc:
        package = install_name or module_name
        raise SystemExit(
            f"Missing dependency '{package}'. Install dependencies with: pip install -r requirements.txt"
        ) from exc


def load_dotenv_if_available() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(ROOT / ".env")


def load_yaml(path: Path) -> dict[str, Any]:
    yaml = require_dependency("yaml", "PyYAML")
    if not path.exists():
        raise SystemExit(f"Missing required file: {path}")
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise SystemExit(f"Expected a YAML mapping in {path}")
    return data


def parse_bool(value: str | None, default: bool = True) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def first_env(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return None


def parse_holdings(raw: dict[str, Any], default_position_size: float = 0) -> dict[str, Holding]:
    holdings: dict[str, Holding] = {}
    for item in raw.get("tickers", []):
        if isinstance(item, str):
            ticker = item.upper()
            holdings[ticker] = Holding(ticker=ticker, position_size_pct=default_position_size, thesis={})
            continue
        ticker = str(item.get("ticker", "")).upper().strip()
        if not ticker:
            continue
        holdings[ticker] = Holding(
            ticker=ticker,
            position_size_pct=float(item.get("position_size_pct", default_position_size) or 0),
            thesis=item.get("thesis", {}) or {},
        )
    return holdings


def flatten_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(flatten_strings(item))
        return result
    if isinstance(value, dict):
        result = []
        for item in value.values():
            result.extend(flatten_strings(item))
        return result
    return []


def tokenize(text: str) -> list[str]:
    terms = re.findall(r"[A-Za-z][A-Za-z0-9\-]{2,}", text.lower())
    return [term for term in terms if term not in STOPWORDS and len(term) >= 4]


def thesis_keywords(holding: Holding) -> set[str]:
    terms: set[str] = set()
    for text in flatten_strings(holding.thesis):
        terms.update(tokenize(text))
    return terms


def detect_event_types(text: str) -> list[str]:
    lowered = text.lower()
    detected = []
    for event_type, keywords in EVENT_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            detected.append(event_type)
    return detected


def parse_date(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(normalized)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                parsed = dt.datetime.strptime(value, fmt)
                break
            except ValueError:
                continue
        else:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=NY_TZ)
    return parsed


def observed_date(month: int, day: int, year: int) -> dt.date:
    actual = dt.date(year, month, day)
    if actual.weekday() == 5:
        return actual - dt.timedelta(days=1)
    if actual.weekday() == 6:
        return actual + dt.timedelta(days=1)
    return actual


def nth_weekday(year: int, month: int, weekday: int, n: int) -> dt.date:
    date = dt.date(year, month, 1)
    while date.weekday() != weekday:
        date += dt.timedelta(days=1)
    return date + dt.timedelta(days=7 * (n - 1))


def last_weekday(year: int, month: int, weekday: int) -> dt.date:
    if month == 12:
        date = dt.date(year, 12, 31)
    else:
        date = dt.date(year, month + 1, 1) - dt.timedelta(days=1)
    while date.weekday() != weekday:
        date -= dt.timedelta(days=1)
    return date


def easter_date(year: int) -> dt.date:
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return dt.date(year, month, day)


def nyse_holidays(year: int) -> set[dt.date]:
    holidays = {
        observed_date(1, 1, year),
        nth_weekday(year, 1, 0, 3),
        nth_weekday(year, 2, 0, 3),
        easter_date(year) - dt.timedelta(days=2),
        last_weekday(year, 5, 0),
        observed_date(7, 4, year),
        nth_weekday(year, 9, 0, 1),
        nth_weekday(year, 11, 3, 4),
        observed_date(12, 25, year),
    }
    if year >= 2022:
        holidays.add(observed_date(6, 19, year))
    return holidays


def is_us_trading_day(date: dt.date) -> bool:
    return date.weekday() < 5 and date not in nyse_holidays(date.year)


def previous_us_trading_day(before_date: dt.date) -> dt.date:
    candidate = before_date - dt.timedelta(days=1)
    while not is_us_trading_day(candidate):
        candidate -= dt.timedelta(days=1)
    return candidate


def latest_completed_us_trading_day(now: dt.datetime | None = None) -> dt.date:
    now = now or dt.datetime.now(tz=PRAGUE_TZ)
    ny_date = now.astimezone(NY_TZ).date()
    return previous_us_trading_day(ny_date)


class FmpClient:
    def __init__(self, api_key: str, base_url: str, timeout_seconds: int = 20) -> None:
        self.requests = require_dependency("requests")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def get(self, endpoint: str, params: dict[str, Any]) -> Any:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        query = {key: value for key, value in params.items() if value is not None}
        query["apikey"] = self.api_key
        response = self.requests.get(url, params=query, timeout=self.timeout_seconds)
        response.raise_for_status()
        return response.json()

    def stock_news(self, symbols: list[str], start: dt.date, end: dt.date, limit: int) -> list[dict[str, Any]]:
        if not symbols:
            return []
        data = self.get(
            "news/stock",
            {
                "symbols": ",".join(symbols),
                "from": start.isoformat(),
                "to": end.isoformat(),
                "limit": limit,
            },
        )
        return data if isinstance(data, list) else []

    def general_news(self, limit: int) -> list[dict[str, Any]]:
        data = self.get("news/general-latest", {"page": 0, "limit": limit})
        return data if isinstance(data, list) else []

    def quote(self, symbol: str) -> dict[str, Any] | None:
        data = self.get("quote", {"symbol": symbol})
        if isinstance(data, list) and data:
            return data[0]
        if isinstance(data, dict):
            return data
        return None


def domain_from_url(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def source_key(source: str, url: str) -> str:
    domain = domain_from_url(url)
    return domain or source.lower().strip()


def normalize_symbols(value: Any) -> list[str]:
    if isinstance(value, str):
        parts = re.split(r"[,;\s]+", value)
    elif isinstance(value, list):
        parts = [str(item) for item in value]
    else:
        parts = []
    return sorted({part.upper().strip() for part in parts if part and part.strip()})


def normalize_news_item(raw: dict[str, Any]) -> NewsItem | None:
    title = str(raw.get("title") or raw.get("headline") or "").strip()
    url = str(raw.get("url") or raw.get("link") or "").strip()
    if not title or not url:
        return None
    text = str(raw.get("text") or raw.get("summary") or raw.get("content") or "").strip()
    source = str(raw.get("site") or raw.get("source") or domain_from_url(url) or "unknown").strip()
    published_at = raw.get("publishedDate") or raw.get("published_at") or raw.get("date")
    symbols = normalize_symbols(raw.get("symbols") or raw.get("symbol") or raw.get("ticker"))
    event_types = detect_event_types(f"{title} {text}")
    return NewsItem(
        ticker=symbols[0] if symbols else None,
        title=title,
        text=text,
        url=url,
        source=source,
        published_at=str(published_at) if published_at else None,
        symbols=symbols,
        event_types=event_types,
        score_reasons=[],
        matched_thesis_terms=[],
    )


def dedupe_news(items: list[NewsItem]) -> list[NewsItem]:
    by_key: dict[str, NewsItem] = {}
    source_sets: dict[str, set[str]] = {}
    for item in items:
        words = [word for word in tokenize(item.title) if word not in STOPWORDS][:10]
        key = " ".join(words) or item.url
        if key not in by_key:
            by_key[key] = item
            source_sets[key] = set()
        source_sets[key].add(source_key(item.source, item.url))
    for key, item in by_key.items():
        item.duplicate_source_count = len(source_sets[key])
    return list(by_key.values())


def fetch_market_data(client: FmpClient, symbols: list[str]) -> dict[str, MarketData]:
    result: dict[str, MarketData] = {}
    for symbol in symbols:
        try:
            quote = client.quote(symbol)
        except Exception as exc:
            print(f"Warning: failed to fetch quote for {symbol}: {exc}", file=sys.stderr)
            result[symbol] = MarketData(ticker=symbol)
            continue
        if not quote:
            result[symbol] = MarketData(ticker=symbol)
            continue
        change = quote.get("changesPercentage") or quote.get("changePercentage")
        volume = quote.get("volume")
        avg_volume = quote.get("avgVolume") or quote.get("averageVolume")
        volume_ratio = None
        try:
            if volume and avg_volume:
                volume_ratio = float(volume) / float(avg_volume)
        except (TypeError, ValueError, ZeroDivisionError):
            volume_ratio = None
        try:
            price_change_pct = float(str(change).replace("%", "")) if change is not None else None
        except ValueError:
            price_change_pct = None
        result[symbol] = MarketData(symbol, price_change_pct=price_change_pct, volume_ratio=volume_ratio)
    return result


def score_news_item(
    item: NewsItem,
    portfolio: dict[str, Holding],
    watchlist: dict[str, Holding],
    market_data: dict[str, MarketData],
    config: dict[str, Any],
) -> None:
    scoring = config.get("scoring", {})
    event_weights = scoring.get("event_weights", {})
    reasons: list[str] = []
    score = 0.0
    symbols = item.symbols or ([item.ticker] if item.ticker else [])

    portfolio_symbols = [symbol for symbol in symbols if symbol in portfolio]
    watchlist_symbols = [symbol for symbol in symbols if symbol in watchlist]

    if portfolio_symbols:
        score += float(scoring.get("portfolio_ticker", 80))
        reasons.append("portfolio_ticker")
        score += sum(portfolio[symbol].position_size_pct for symbol in portfolio_symbols)
    if watchlist_symbols:
        score += float(scoring.get("watchlist_ticker", 45))
        reasons.append("watchlist_ticker")

    for event_type in item.event_types:
        score += float(event_weights.get(event_type, 0))
        reasons.append(f"event:{event_type}")

    source = source_key(item.source, item.url)
    source_quality = float(config.get("source_quality", {}).get(source, 0.5))
    score += source_quality * float(scoring.get("source_quality_multiplier", 10))

    if item.duplicate_source_count > 1:
        score += (item.duplicate_source_count - 1) * float(scoring.get("duplicate_source", 8))
        reasons.append("duplicate_coverage")

    primary_symbol = portfolio_symbols[0] if portfolio_symbols else watchlist_symbols[0] if watchlist_symbols else symbols[0] if symbols else None
    if primary_symbol:
        item.ticker = primary_symbol
        data = market_data.get(primary_symbol)
        if data:
            item.price_change_pct = data.price_change_pct
            item.volume_ratio = data.volume_ratio
            if data.price_change_pct is not None:
                absolute_move = abs(data.price_change_pct)
                if absolute_move >= 5:
                    score += float(scoring.get("price_move_abs_5pct", 25))
                    reasons.append("price_move_abs_5pct")
                elif absolute_move >= 3:
                    score += float(scoring.get("price_move_abs_3pct", 15))
                    reasons.append("price_move_abs_3pct")
            if data.volume_ratio is not None and data.volume_ratio >= 2:
                score += float(scoring.get("volume_ratio_2x", 15))
                reasons.append("volume_ratio_2x")

    text_terms = set(tokenize(f"{item.title} {item.text}"))
    matched_terms: set[str] = set()
    for symbol in portfolio_symbols:
        matched_terms.update(text_terms.intersection(thesis_keywords(portfolio[symbol])))
    for symbol in watchlist_symbols:
        matched_terms.update(text_terms.intersection(thesis_keywords(watchlist[symbol])))
    if matched_terms:
        score += len(matched_terms) * float(scoring.get("thesis_keyword", 8))
        reasons.append("thesis_keyword")

    item.score = round(score, 2)
    item.score_reasons = reasons
    item.matched_thesis_terms = sorted(matched_terms)[:12]


def truncate(text: str, max_chars: int) -> str:
    clean = re.sub(r"\s+", " ", text).strip()
    if len(clean) <= max_chars:
        return clean
    return clean[: max_chars - 1].rstrip() + "..."


def compact_context(
    report_date: dt.date,
    window_start: dt.datetime,
    window_end: dt.datetime,
    portfolio: dict[str, Holding],
    watchlist: dict[str, Holding],
    items: list[NewsItem],
    max_items: int,
) -> dict[str, Any]:
    top_items = sorted(items, key=lambda item: item.score, reverse=True)[:max_items]
    return {
        "report_date": report_date.isoformat(),
        "news_window": {
            "start": window_start.isoformat(),
            "end": window_end.isoformat(),
        },
        "portfolio": [
            {
                "ticker": holding.ticker,
                "position_size_pct": holding.position_size_pct,
                "thesis": holding.thesis,
            }
            for holding in portfolio.values()
        ],
        "watchlist": [
            {
                "ticker": holding.ticker,
                "thesis": holding.thesis,
            }
            for holding in watchlist.values()
        ],
        "ranked_news": [
            {
                "ticker": item.ticker,
                "symbols": item.symbols,
                "title": item.title,
                "snippet": truncate(item.text, 360),
                "source": item.source,
                "url": item.url,
                "published_at": item.published_at,
                "event_types": item.event_types,
                "relevance_score": item.score,
                "score_reasons": item.score_reasons,
                "matched_thesis_terms": item.matched_thesis_terms,
                "duplicate_source_count": item.duplicate_source_count,
                "price_change_pct": item.price_change_pct,
                "volume_ratio": round(item.volume_ratio, 2) if item.volume_ratio is not None else None,
            }
            for item in top_items
        ],
        "constraints": {
            "allowed_attention_labels": sorted(ATTENTION_LABELS),
            "must_not_include": [
                "direct buy recommendations",
                "direct sell recommendations",
                "portfolio allocation instructions",
            ],
        },
    }


def parse_model_json(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?", "", stripped).strip()
        stripped = re.sub(r"```$", "", stripped).strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", stripped, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise


def default_report(context: dict[str, Any]) -> dict[str, Any]:
    items = context.get("ranked_news", [])
    portfolio_tickers = {item["ticker"] for item in context.get("portfolio", [])}
    watchlist_tickers = {item["ticker"] for item in context.get("watchlist", [])}
    portfolio_news = []
    watchlist_news = []
    flags = []
    for item in items[:10]:
        entry = {
            "ticker": item.get("ticker") or "MARKET",
            "headline": item.get("title", ""),
            "why_it_matters": "Relevant based on ticker match, event type, price/volume signal, or thesis keyword match.",
            "attention_label": "monitor",
            "source": item.get("source", ""),
            "source_url": item.get("url", ""),
        }
        if item.get("ticker") in portfolio_tickers:
            portfolio_news.append(entry)
        elif item.get("ticker") in watchlist_tickers:
            watchlist_news.append(entry)
        if item.get("score_reasons"):
            flags.append(
                {
                    "ticker": item.get("ticker") or "MARKET",
                    "label": "monitor",
                    "reason": ", ".join(item.get("score_reasons", [])[:4]),
                }
            )
    return {
        "report_date": context["report_date"],
        "executive_summary": [
            "OpenAI generation was skipped; this fallback report uses deterministic relevance scoring.",
            f"{len(items)} ranked news items were included in the compact context.",
        ],
        "portfolio_news": portfolio_news,
        "thesis_impact": [],
        "watchlist_news": watchlist_news,
        "top_market_themes": [],
        "attention_flags": flags,
        "sources": [
            {
                "title": item.get("title", ""),
                "source": item.get("source", ""),
                "url": item.get("url", ""),
            }
            for item in items[:12]
        ],
    }


def generate_report_with_openai(context: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    from openai import OpenAI

    model = config.get("openai", {}).get("model", "gpt-4.1-mini")
    client = OpenAI()
    system = (
        "You write concise personalized investment morning reports. "
        "Use only the supplied compact JSON context. "
        "Do not create direct buy, sell, hold, position sizing, or trading recommendations. "
        "Classify relevance, thesis impact, and next things to monitor. "
        "Return valid JSON only."
    )
    user = {
        "task": "Create a daily investment morning report from this prefiltered context.",
        "output_schema": {
            "report_date": "YYYY-MM-DD",
            "executive_summary": ["string"],
            "portfolio_news": [
                {
                    "ticker": "string",
                    "headline": "string",
                    "why_it_matters": "string",
                    "attention_label": "no_action|monitor|review_thesis|review_valuation|deeper_analysis_needed",
                    "source": "string",
                    "source_url": "string",
                }
            ],
            "thesis_impact": [
                {
                    "ticker": "string",
                    "impact": "supports|challenges|mixed|unclear",
                    "rationale": "string",
                    "monitor_next": "string",
                }
            ],
            "watchlist_news": [
                {
                    "ticker": "string",
                    "headline": "string",
                    "why_it_matters": "string",
                    "attention_label": "no_action|monitor|review_thesis|review_valuation|deeper_analysis_needed",
                    "source": "string",
                    "source_url": "string",
                }
            ],
            "top_market_themes": ["string"],
            "attention_flags": [
                {
                    "ticker": "string",
                    "label": "no_action|monitor|review_thesis|review_valuation|deeper_analysis_needed",
                    "reason": "string",
                }
            ],
            "sources": [{"title": "string", "source": "string", "url": "string"}],
        },
        "context": context,
    }
    response = client.responses.create(
        model=model,
        input=[
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
        ],
    )
    report = parse_model_json(response.output_text)
    report.setdefault("report_date", context["report_date"])
    return validate_report(report, context)


def validate_label(value: str | None) -> str:
    if value in ATTENTION_LABELS:
        return value
    return "monitor"


def normalize_match_text(value: str | None) -> set[str]:
    if not value:
        return set()
    return set(tokenize(value))


def enrich_report_item_sources(items: list[dict[str, Any]], context: dict[str, Any]) -> None:
    ranked_news = context.get("ranked_news", [])
    for item in items:
        if item.get("url") and not item.get("source_url"):
            item["source_url"] = item["url"]
        if item.get("source_url"):
            continue
        ticker = str(item.get("ticker") or "").upper()
        headline_terms = normalize_match_text(item.get("headline"))
        best_match = None
        best_score = -1
        for news in ranked_news:
            score = 0
            if ticker and ticker == str(news.get("ticker") or "").upper():
                score += 5
            overlap = headline_terms.intersection(normalize_match_text(news.get("title")))
            score += len(overlap)
            if score > best_score:
                best_score = score
                best_match = news
        if best_match and best_score > 0:
            item["source"] = item.get("source") or best_match.get("source", "")
            item["source_url"] = best_match.get("url", "")


def validate_report(report: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    report["report_date"] = str(report.get("report_date") or context["report_date"])
    for key in ("executive_summary", "portfolio_news", "thesis_impact", "watchlist_news", "top_market_themes", "attention_flags", "sources"):
        if not isinstance(report.get(key), list):
            report[key] = []
    for section in ("portfolio_news", "watchlist_news"):
        for item in report[section]:
            item["attention_label"] = validate_label(item.get("attention_label"))
        enrich_report_item_sources(report[section], context)
    for item in report["attention_flags"]:
        item["label"] = validate_label(item.get("label"))
    if not report["sources"]:
        report["sources"] = [
            {"title": item.get("title", ""), "source": item.get("source", ""), "url": item.get("url", "")}
            for item in context.get("ranked_news", [])[:12]
        ]
    return report


def render_email(report: dict[str, Any], subject: str) -> str:
    jinja2 = require_dependency("jinja2", "Jinja2")
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(ROOT / "templates"),
        autoescape=True,
    )
    template = env.get_template("email_report.html")
    return template.render(
        report=report,
        subject=subject,
        generated_at=dt.datetime.now(tz=PRAGUE_TZ).isoformat(timespec="minutes"),
    )


def send_email(subject: str, html: str) -> None:
    host = first_env("SMTP_HOST", "SMTP_SERVER")
    username = first_env("SMTP_USERNAME", "SMTP_SENDER")
    password = first_env("SMTP_PASSWORD", "SMTP_PWD")
    from_address = first_env("SMTP_FROM", "SMTP_SENDER")
    recipients_raw = first_env("SMTP_TO", "SMTP_RECIPIENTS", "SMTP_RECIPIENT") or ""
    to_addresses = [item.strip() for item in recipients_raw.split(",") if item.strip()]
    if not host or not from_address or not to_addresses:
        raise SystemExit("SMTP_HOST/SMTP_SERVER, SMTP_FROM/SMTP_SENDER, and SMTP_TO must be set to send email.")

    port = int(os.getenv("SMTP_PORT", "465" if host.lower() == "smtp.gmail.com" else "587"))
    use_ssl = parse_bool(os.getenv("SMTP_USE_SSL"), default=port == 465)
    use_tls = parse_bool(os.getenv("SMTP_USE_TLS"), default=not use_ssl)

    message = email.message.EmailMessage()
    message["Subject"] = subject
    message["From"] = from_address
    message["To"] = ", ".join(to_addresses)
    message.set_content("Your email client does not support HTML reports.")
    message.add_alternative(html, subtype="html")

    if use_ssl:
        smtp_context = smtplib.SMTP_SSL(host, port, timeout=30)
    else:
        smtp_context = smtplib.SMTP(host, port, timeout=30)

    with smtp_context as smtp:
        if use_tls and not use_ssl:
            smtp.starttls()
        if username and password:
            smtp.login(username, password)
        smtp.send_message(message)


def fetch_and_rank_news(
    client: FmpClient,
    portfolio: dict[str, Holding],
    watchlist: dict[str, Holding],
    config: dict[str, Any],
    report_date: dt.date,
    window_start: dt.datetime,
    window_end: dt.datetime,
) -> list[NewsItem]:
    symbols = sorted(set(portfolio) | set(watchlist))
    fmp_config = config.get("fmp", {})
    raw_items: list[dict[str, Any]] = []
    raw_items.extend(
        client.stock_news(
            symbols=symbols,
            start=window_start.date(),
            end=window_end.date(),
            limit=int(fmp_config.get("news_limit_per_ticker", 30)) * max(1, len(symbols)),
        )
    )
    raw_items.extend(client.general_news(limit=int(fmp_config.get("general_news_limit", 40))))

    normalized = [item for item in (normalize_news_item(raw) for raw in raw_items) if item is not None]
    filtered = []
    for item in normalized:
        published = parse_date(item.published_at)
        if published and not (window_start <= published.astimezone(window_start.tzinfo) <= window_end):
            continue
        filtered.append(item)

    deduped = dedupe_news(filtered)
    market_data = fetch_market_data(client, symbols)
    for item in deduped:
        score_news_item(item, portfolio, watchlist, market_data, config)
    return sorted(deduped, key=lambda item: item.score, reverse=True)


def build_subject(config: dict[str, Any], report_date: dt.date) -> str:
    prefix = config.get("email", {}).get("subject_prefix", "Investment morning report")
    return f"{prefix} - {report_date.isoformat()}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a personalized investment morning report.")
    parser.add_argument("--date", default="latest", help="'latest' or an explicit YYYY-MM-DD US trading date.")
    parser.add_argument("--config", default="config.yaml", help="Path to config YAML.")
    parser.add_argument("--portfolio", default="portfolio.yaml", help="Path to portfolio YAML.")
    parser.add_argument("--watchlist", default="watchlist.yaml", help="Path to watchlist YAML.")
    parser.add_argument("--send-email", action="store_true", help="Send the generated report through SMTP.")
    parser.add_argument("--skip-openai", action="store_true", help="Use deterministic fallback report generation.")
    parser.add_argument("--output-html", default="out/report.html", help="Where to write the rendered HTML report.")
    parser.add_argument("--output-json", default="out/report.json", help="Where to write the structured report JSON.")
    parser.add_argument("--context-json", default="out/context.json", help="Where to write the compact OpenAI input JSON.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_dotenv_if_available()

    config = load_yaml(ROOT / args.config)
    portfolio = parse_holdings(load_yaml(ROOT / args.portfolio))
    watchlist = parse_holdings(load_yaml(ROOT / args.watchlist))

    if args.date == "latest":
        report_date = latest_completed_us_trading_day()
    else:
        report_date = dt.date.fromisoformat(args.date)
        if not is_us_trading_day(report_date):
            raise SystemExit(f"{report_date} is not a regular US trading day.")

    now_prague = dt.datetime.now(tz=ZoneInfo(config.get("timezone", "Europe/Prague")))
    window_start = dt.datetime.combine(report_date, dt.time.min, tzinfo=NY_TZ)
    window_end = now_prague

    fmp_api_key = os.getenv("FMP_API_KEY")
    if not fmp_api_key:
        raise SystemExit("FMP_API_KEY is required. Add it to .env or the environment.")

    fmp_config = config.get("fmp", {})
    client = FmpClient(
        api_key=fmp_api_key,
        base_url=fmp_config.get("base_url", "https://financialmodelingprep.com/stable"),
        timeout_seconds=int(fmp_config.get("request_timeout_seconds", 20)),
    )

    ranked_news = fetch_and_rank_news(client, portfolio, watchlist, config, report_date, window_start, window_end)
    context = compact_context(
        report_date=report_date,
        window_start=window_start,
        window_end=window_end,
        portfolio=portfolio,
        watchlist=watchlist,
        items=ranked_news,
        max_items=int(config.get("openai", {}).get("max_input_items", 35)),
    )

    if args.skip_openai:
        report = validate_report(default_report(context), context)
    else:
        if not os.getenv("OPENAI_API_KEY"):
            raise SystemExit("OPENAI_API_KEY is required unless --skip-openai is used.")
        report = generate_report_with_openai(context, config)

    subject = build_subject(config, report_date)
    html = render_email(report, subject)

    for output_path, payload, is_json in (
        (Path(args.context_json), context, True),
        (Path(args.output_json), report, True),
        (Path(args.output_html), html, False),
    ):
        path = output_path if output_path.is_absolute() else ROOT / output_path
        path.parent.mkdir(parents=True, exist_ok=True)
        if is_json:
            path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        else:
            path.write_text(str(payload), encoding="utf-8")

    if args.send_email:
        send_email(subject, html)
        print(f"Sent report email: {subject}")
    else:
        print(f"Generated report: {subject}")
        print(f"HTML: {Path(args.output_html)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
