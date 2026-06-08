from __future__ import annotations

import argparse
import base64
import datetime as dt
import html
import json
import math
import os
import re
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

SECTOR_KEYWORDS = {
    "technology": (
        "technology",
        "software",
        "cloud",
        "cybersecurity",
        "semiconductor",
        "chip",
        "chips",
        "ai",
        "artificial",
        "intelligence",
        "datacenter",
        "data",
        "center",
        "saas",
    ),
    "communication_services": (
        "advertising",
        "streaming",
        "media",
        "telecom",
        "communications",
        "social",
        "gaming",
        "internet",
    ),
    "financial_services": (
        "bank",
        "banks",
        "banking",
        "insurance",
        "fintech",
        "credit",
        "loan",
        "loans",
        "asset",
        "wealth",
        "payments",
        "capital",
    ),
    "healthcare": (
        "healthcare",
        "health",
        "biotech",
        "pharma",
        "drug",
        "drugs",
        "medical",
        "medicare",
        "clinical",
        "therapy",
    ),
    "consumer_cyclical": (
        "retail",
        "consumer",
        "automotive",
        "auto",
        "ecommerce",
        "travel",
        "restaurant",
        "housing",
        "apparel",
    ),
    "consumer_defensive": (
        "grocery",
        "food",
        "beverage",
        "staples",
        "household",
        "tobacco",
        "defensive",
    ),
    "industrials": (
        "industrial",
        "industrials",
        "aerospace",
        "defense",
        "machinery",
        "manufacturing",
        "logistics",
        "transport",
    ),
    "energy": (
        "energy",
        "oil",
        "gas",
        "lng",
        "lpg",
        "opec",
        "crude",
        "pipeline",
        "drilling",
    ),
    "utilities": (
        "utilities",
        "utility",
        "power",
        "electricity",
        "grid",
        "nuclear",
        "renewable",
        "solar",
        "wind",
    ),
    "real_estate": (
        "real",
        "estate",
        "reit",
        "housing",
        "mortgage",
        "office",
        "property",
        "properties",
    ),
    "materials": (
        "materials",
        "mining",
        "metals",
        "steel",
        "copper",
        "gold",
        "chemical",
        "chemicals",
        "lithium",
    ),
}

MARKET_THEME_KEYWORDS = {
    "Market rally and valuation risks": (
        "market",
        "markets",
        "stocks",
        "equities",
        "rally",
        "valuation",
        "valuations",
        "earnings",
        "margin",
        "margins",
        "bubble",
        "crash",
        "risk",
        "risks",
        "obstacle",
        "obstacles",
    ),
    "AI infrastructure and cloud": (
        "ai",
        "artificial",
        "intelligence",
        "cloud",
        "datacenter",
        "data",
        "center",
        "chip",
        "chips",
        "gpu",
        "semiconductor",
    ),
    "Rates and macro outlook": (
        "fed",
        "federal",
        "reserve",
        "rate",
        "rates",
        "inflation",
        "jobs",
        "payroll",
        "treasury",
        "yield",
        "gdp",
        "recession",
    ),
    "Geopolitics and regulation": (
        "tariff",
        "sanction",
        "china",
        "iran",
        "geopolitical",
        "regulation",
        "regulator",
        "antitrust",
        "investigation",
    ),
    "Energy and commodities": (
        "oil",
        "gas",
        "lng",
        "lpg",
        "opec",
        "crude",
        "energy",
        "power",
        "electricity",
        "nuclear",
        "commodity",
    ),
    "Credit and capital markets": (
        "bond",
        "bonds",
        "debt",
        "credit",
        "loan",
        "loans",
        "financing",
        "issuance",
        "yield",
        "spread",
    ),
    "Consumer and retail": (
        "consumer",
        "retail",
        "spending",
        "sales",
        "housing",
        "mortgage",
        "autos",
        "travel",
    ),
}


@dataclass(frozen=True)
class Holding:
    ticker: str
    position_size_pct: float
    thesis: dict[str, Any]
    company_name: str | None = None


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
    item_type: str = "news"
    score: float = 0
    score_reasons: list[str] | None = None
    matched_thesis_terms: list[str] | None = None
    duplicate_source_count: int = 1
    price_change_pct: float | None = None
    volume_ratio: float | None = None
    popularity: float | None = None


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


def first_number(data: dict[str, Any], *names: str) -> float | None:
    for name in names:
        value = data.get(name)
        if value is None:
            continue
        try:
            return float(str(value).replace(",", ""))
        except ValueError:
            continue
    return None


def clean_text(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def clean_url(value: Any) -> str:
    url = str(value or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return url


def normalize_text_array(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if item is not None]
    return [str(value)]


def load_portfolio_from_db(user_id: str) -> dict[str, Holding]:
    try:
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise RuntimeError("Missing dependency 'psycopg'. Install dependencies with: pip install -r requirements.txt") from exc

    from database import connection

    with connection(row_factory=dict_row) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                select
                    stocks.symbol,
                    stocks.company_name,
                    portfolio_items.position_size_pct,
                    portfolio_items.why_i_own_it,
                    portfolio_items.bull_case,
                    portfolio_items.bear_case,
                    portfolio_items.key_metrics,
                    portfolio_items.red_flags,
                    portfolio_items.action_triggers
                from public.portfolio_items
                join public.stocks on stocks.id = portfolio_items.stock_id
                where portfolio_items.user_id = %s
                  and portfolio_items.include_in_report = true
                order by portfolio_items.position_size_pct desc nulls last, stocks.symbol
                """,
                (user_id,),
            )
            rows = cursor.fetchall()

    holdings: dict[str, Holding] = {}
    for row in rows:
        symbol = str(row["symbol"]).upper().strip()
        if not symbol:
            continue
        holdings[symbol] = Holding(
            ticker=symbol,
            position_size_pct=float(row["position_size_pct"] or 0),
            company_name=str(row["company_name"]).strip() or None,
            thesis={
                "why_i_own_it": normalize_text_array(row["why_i_own_it"]),
                "bull_case": normalize_text_array(row["bull_case"]),
                "bear_case": normalize_text_array(row["bear_case"]),
                "key_metrics": normalize_text_array(row["key_metrics"]),
                "red_flags": normalize_text_array(row["red_flags"]),
                "action_triggers": normalize_text_array(row["action_triggers"]),
            },
        )

    if not holdings:
        raise SystemExit(f"No portfolio items found for user_id={user_id}.")
    return holdings


def load_watchlist_from_db(user_id: str) -> dict[str, Holding]:
    try:
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise RuntimeError("Missing dependency 'psycopg'. Install dependencies with: pip install -r requirements.txt") from exc

    from database import connection

    with connection(row_factory=dict_row) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                select
                    stocks.symbol,
                    stocks.company_name,
                    watchlist_items.why_i_watch_it,
                    watchlist_items.bull_case,
                    watchlist_items.bear_case,
                    watchlist_items.key_metrics,
                    watchlist_items.red_flags,
                    watchlist_items.action_triggers
                from public.watchlist_items
                join public.stocks on stocks.id = watchlist_items.stock_id
                where watchlist_items.user_id = %s
                  and watchlist_items.include_in_report = true
                order by stocks.symbol
                """,
                (user_id,),
            )
            rows = cursor.fetchall()

    holdings: dict[str, Holding] = {}
    for row in rows:
        symbol = str(row["symbol"]).upper().strip()
        if not symbol:
            continue
        holdings[symbol] = Holding(
            ticker=symbol,
            position_size_pct=0,
            company_name=str(row["company_name"]).strip() or None,
            thesis={
                "why_i_watch_it": normalize_text_array(row["why_i_watch_it"]),
                "bull_case": normalize_text_array(row["bull_case"]),
                "bear_case": normalize_text_array(row["bear_case"]),
                "key_metrics": normalize_text_array(row["key_metrics"]),
                "red_flags": normalize_text_array(row["red_flags"]),
                "action_triggers": normalize_text_array(row["action_triggers"]),
            },
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


def market_theme_terms(text: str) -> set[str]:
    terms = re.findall(r"[A-Za-z][A-Za-z0-9\-]{1,}", text.lower())
    return {term for term in terms if term not in STOPWORDS and len(term) >= 2}


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

    def fmp_articles(self, limit: int) -> list[dict[str, Any]]:
        data = self.get("fmp-articles", {"page": 0, "limit": limit})
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


def domain_matches(domain: str, configured_domain: str) -> bool:
    domain = domain.lower().strip()
    configured_domain = configured_domain.lower().strip()
    return domain == configured_domain or domain.endswith(f".{configured_domain}")


def source_domain_is_excluded(item: NewsItem, config: dict[str, Any]) -> bool:
    domain = domain_from_url(item.url)
    excluded = config.get("excluded_source_domains", [])
    if not isinstance(excluded, list):
        return False
    return any(domain_matches(domain, str(configured)) for configured in excluded if configured)


def source_quality_score(source: str, url: str, config: dict[str, Any]) -> float:
    source = source_key(source, url)
    configured = config.get("source_quality", {})
    if not isinstance(configured, dict):
        return 0.5
    for domain, score in configured.items():
        if domain_matches(source, str(domain)):
            return float(score)
    return 0.5


def normalize_symbols(value: Any) -> list[str]:
    if isinstance(value, str):
        parts = re.split(r"[,;\s]+", value)
    elif isinstance(value, list):
        parts = [str(item) for item in value]
    else:
        parts = []
    symbols = set()
    for part in parts:
        symbol = part.upper().strip()
        if symbol.endswith(":"):
            symbol = symbol[:-1]
        elif ":" in symbol:
            symbol = symbol.split(":")[-1]
        symbol = re.sub(r"[^A-Z.\-]", "", symbol)
        if 1 <= len(symbol) <= 6 and re.fullmatch(r"[A-Z][A-Z.\-]*", symbol):
            symbols.add(symbol)
    return sorted(symbols)


def title_ticker_symbols(title: str) -> list[str]:
    symbols = set()
    prefix_symbol = re.match(r"^\s*([A-Z]{1,6})\s*:", title)
    if prefix_symbol:
        symbols.update(normalize_symbols([prefix_symbol.group(1)]))
    exchange_symbols = re.findall(
        r"\b(?:NASDAQ|NYSE|AMEX|OTC|TSX|LSE|NYSEARCA)\s*:\s*([A-Z][A-Z0-9.\-]{0,5})\b",
        title,
    )
    symbols.update(normalize_symbols(exchange_symbols))
    return sorted(symbols)


def normalize_news_item(raw: dict[str, Any], item_type: str = "news") -> NewsItem | None:
    title = clean_text(raw.get("title") or raw.get("headline") or "")
    url = clean_url(raw.get("url") or raw.get("link") or "")
    if not title or not url:
        return None
    text = clean_text(raw.get("text") or raw.get("summary") or raw.get("content") or "")
    source = str(raw.get("site") or raw.get("source") or domain_from_url(url) or "unknown").strip()
    published_at = raw.get("publishedDate") or raw.get("published_at") or raw.get("date")
    symbols = normalize_symbols(raw.get("symbols") or raw.get("symbol") or raw.get("ticker"))
    title_symbols = title_ticker_symbols(title)
    if title_symbols:
        symbols = sorted(set(symbols).intersection(title_symbols) or set(title_symbols))
    event_types = detect_event_types(f"{title} {text}")
    popularity = first_number(raw, "views", "viewCount", "readCount", "reads", "popularity")
    return NewsItem(
        ticker=symbols[0] if symbols else None,
        title=title,
        text=text,
        url=url,
        source=source,
        published_at=str(published_at) if published_at else None,
        symbols=symbols,
        event_types=event_types,
        item_type=item_type,
        popularity=popularity,
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
    configured_symbols = set(portfolio) | set(watchlist)
    configured_holdings = {**watchlist, **portfolio}
    strong_configured_symbols = [
        symbol for symbol in configured_symbols if item_strongly_matches_holding(item, configured_holdings[symbol])
    ]
    original_symbols = set(item.symbols or ([item.ticker] if item.ticker else []))
    symbols = sorted((original_symbols - configured_symbols).union(strong_configured_symbols))
    item.symbols = symbols
    if item.ticker and item.ticker in configured_symbols and item.ticker not in strong_configured_symbols:
        item.ticker = None

    portfolio_symbols = [symbol for symbol in strong_configured_symbols if symbol in portfolio]
    watchlist_symbols = [symbol for symbol in strong_configured_symbols if symbol in watchlist and symbol not in portfolio]

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

    source_quality = source_quality_score(item.source, item.url, config)
    score += source_quality * float(scoring.get("source_quality_multiplier", 10))

    if item.duplicate_source_count > 1:
        score += (item.duplicate_source_count - 1) * float(scoring.get("duplicate_source", 8))
        reasons.append("duplicate_coverage")

    candidate_primary_symbols = portfolio_symbols or watchlist_symbols or symbols
    primary_symbol = None
    if candidate_primary_symbols:
        primary_symbol = max(
            candidate_primary_symbols,
            key=lambda symbol: (
                ticker_match_score(item, configured_holdings.get(symbol, Holding(ticker=symbol, position_size_pct=0, thesis={}))),
                -candidate_primary_symbols.index(symbol),
            ),
        )
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


def compact_news_item(item: NewsItem) -> dict[str, Any]:
    return {
        "ticker": item.ticker,
        "symbols": item.symbols,
        "item_type": item.item_type,
        "title": item.title,
        "snippet": truncate(item.text, 360),
        "source": item.source,
        "url": item.url,
        "published_at": item.published_at,
        "event_types": item.event_types,
        "relevance_score": item.score,
        "notability_score": notable_article_score(item),
        "popularity": item.popularity,
    }


def notable_article_score(item: NewsItem) -> float:
    score = 0.0
    if item.item_type == "fmp_article":
        score += 60
    elif item.item_type == "general_news":
        score += 25
    else:
        score += 10

    score += min(item.score, 80) * 0.25
    score += len(item.event_types) * 8

    if item.duplicate_source_count > 1:
        score += min(item.duplicate_source_count, 5) * 6
    if item.popularity is not None and item.popularity > 0:
        score += min(math.log10(item.popularity + 1) * 12, 60)

    title_terms = market_theme_terms(item.title)
    broad_terms = {
        "market",
        "markets",
        "stocks",
        "equities",
        "earnings",
        "outlook",
        "inflation",
        "rates",
        "fed",
        "ai",
        "energy",
        "china",
        "tariff",
        "regulation",
        "bonds",
        "credit",
    }
    score += len(title_terms.intersection(broad_terms)) * 4
    return round(score, 2)


def notable_market_article_candidates(items: list[NewsItem], max_articles: int = 6) -> list[dict[str, Any]]:
    seen_urls: set[str] = set()
    candidates = []
    for item in sorted(items, key=notable_article_score, reverse=True):
        if not item.url or item.url in seen_urls:
            continue
        seen_urls.add(item.url)
        candidates.append(
            {
                "theme_hint": item.title,
                "candidate_type": "notable_article",
                "supporting_articles": [compact_news_item(item)],
                "article_count": 1,
                "candidate_score": notable_article_score(item),
            }
        )
        if len(candidates) >= max_articles:
            break
    return candidates


def sector_label(sector: str) -> str:
    words = re.split(r"[_\-\s]+", str(sector).strip())
    return " ".join(word if word.isupper() else word.capitalize() for word in words if word)


def sector_terms(sector: str) -> set[str]:
    configured = SECTOR_KEYWORDS.get(sector, ())
    if configured:
        return set(configured)
    return market_theme_terms(sector.replace("_", " "))


def sector_article_candidates(
    items: list[NewsItem],
    selected_sectors: list[str],
    max_articles_per_sector: int,
) -> list[dict[str, Any]]:
    used_urls: set[str] = set()
    candidates = []
    scored_items = sorted(items, key=notable_article_score, reverse=True)

    for sector in selected_sectors:
        keywords = sector_terms(sector)
        if not keywords:
            continue

        sector_articles = []
        for item in scored_items:
            if not item.url or item.url in used_urls:
                continue
            text_terms = market_theme_terms(f"{item.title} {item.text}")
            hits = text_terms.intersection(keywords)
            if not hits:
                continue
            article = compact_news_item(item)
            article["sector_match_terms"] = sorted(hits)[:8]
            sector_articles.append(article)
            used_urls.add(item.url)
            if len(sector_articles) >= max_articles_per_sector:
                break

        if sector_articles:
            candidates.append(
                {
                    "theme_hint": sector_label(sector),
                    "theme_type": "sector_reads",
                    "sector": sector,
                    "supporting_articles": sector_articles,
                    "article_count": len(sector_articles),
                    "candidate_score": round(sum(article.get("notability_score", 0) for article in sector_articles), 2),
                }
            )

    return candidates


def item_mentions_ticker(item: NewsItem, ticker: str) -> bool:
    ticker = ticker.upper()
    if ticker in {symbol.upper() for symbol in item.symbols}:
        return True
    if item.ticker and item.ticker.upper() == ticker:
        return True
    return bool(re.search(rf"\b{re.escape(ticker)}\b", f"{item.title} {item.text}"))


def ticker_mention_count(item: NewsItem, ticker: str) -> int:
    return len(re.findall(rf"\b{re.escape(ticker)}\b", f"{item.title} {item.text}"))


LEGAL_COMPANY_SUFFIXES = (
    "incorporated",
    "corporation",
    "corp",
    "inc",
    "limited",
    "ltd",
    "plc",
    "llc",
    "s.a.",
    "sa",
    "n.v.",
    "nv",
    "ag",
    "se",
)

GENERIC_COMPANY_NAME_WORDS = {
    "the",
    "global",
    "holdings",
    "holding",
    "group",
    "technologies",
    "technology",
    "systems",
    "solutions",
    "energy",
    "financial",
    "capital",
}

GENERIC_ENTITY_PHRASES = {
    "AI",
    "EV",
    "FCF",
    "GMV",
    "TPV",
    "SMB",
    "RPO",
    "EBITDA",
}


def without_legal_suffixes(company_name: str) -> str:
    name = re.sub(r"\s+", " ", company_name.replace(",", " ")).strip(" .")
    while name:
        changed = False
        for suffix in LEGAL_COMPANY_SUFFIXES:
            pattern = rf"\s+{re.escape(suffix)}\.?$"
            updated = re.sub(pattern, "", name, flags=re.IGNORECASE).strip(" .")
            if updated != name:
                name = updated
                changed = True
                break
        if not changed:
            return name
    return name


def company_name_match_phrases(company_name: str | None) -> list[str]:
    if not company_name:
        return []

    phrases: list[str] = []
    for phrase in (company_name.strip(), without_legal_suffixes(company_name)):
        phrase = re.sub(r"\s+", " ", phrase).strip(" .")
        if phrase and phrase.lower() not in {item.lower() for item in phrases}:
            phrases.append(phrase)

    primary_word_match = re.match(r"[A-Za-z][A-Za-z0-9&.\-]+", without_legal_suffixes(company_name))
    if primary_word_match:
        primary_word = primary_word_match.group(0).replace(".com", "")
        normalized = re.sub(r"[^A-Za-z0-9&]", "", primary_word).strip()
        if len(normalized) >= 4 and normalized.lower() not in GENERIC_COMPANY_NAME_WORDS:
            if normalized.lower() not in {item.lower() for item in phrases}:
                phrases.append(normalized)

    return phrases


def thesis_entity_phrases(holding: Holding) -> list[str]:
    phrases: list[str] = []
    seen: set[str] = set()
    for text in flatten_strings(holding.thesis):
        for match in re.finditer(
            r"\b(?:[A-Z][A-Za-z0-9&.\-]{2,}|[A-Z]{3,})(?:\s+(?:[A-Z][A-Za-z0-9&.\-]{2,}|[A-Z]{3,}))*\b",
            text,
        ):
            phrase = match.group(0).strip(" .")
            if phrase in GENERIC_ENTITY_PHRASES:
                continue
            key = phrase.lower()
            if key not in seen:
                seen.add(key)
                phrases.append(phrase)
    return phrases


def item_symbol_matches_holding(item: NewsItem, ticker: str) -> bool:
    ticker = ticker.upper()
    if ticker in {symbol.upper() for symbol in item.symbols}:
        return True
    return bool(item.ticker and item.ticker.upper() == ticker)


def phrase_in_text(value: str, phrase: str, ignore_case: bool = True) -> bool:
    phrase = str(phrase).strip()
    if not phrase:
        return False
    flags = re.IGNORECASE if ignore_case else 0
    return bool(re.search(rf"(?<![A-Za-z0-9]){re.escape(phrase)}(?![A-Za-z0-9])", value, flags))


def item_strongly_matches_holding(item: NewsItem, holding: Holding) -> bool:
    ticker = holding.ticker.upper()
    title_symbols = set(title_ticker_symbols(item.title))
    if ticker in title_symbols:
        return True

    title_has_ticker = bool(re.search(rf"\b{re.escape(ticker)}\b", item.title))
    title_has_company_name = any(
        primary_match_phrase_in_title(item.title, phrase) for phrase in company_name_match_phrases(holding.company_name)
    )
    title_has_thesis_entity = any(
        primary_match_phrase_in_title(item.title, phrase) for phrase in thesis_entity_phrases(holding)
    )
    if title_has_ticker or title_has_company_name:
        return True
    if item_symbol_matches_holding(item, ticker) and title_has_thesis_entity:
        return True

    return False


def ticker_match_score(item: NewsItem, holding: Holding) -> int:
    ticker = holding.ticker.upper()
    score = 0
    if ticker in set(title_ticker_symbols(item.title)):
        score += 100
    if any(primary_match_phrase_in_title(item.title, phrase) for phrase in company_name_match_phrases(holding.company_name)):
        score += 80
    if re.search(rf"\b{re.escape(ticker)}\b", item.title):
        score += 70
    if item_symbol_matches_holding(item, ticker) and any(
        primary_match_phrase_in_title(item.title, phrase) for phrase in thesis_entity_phrases(holding)
    ):
        score += 65
    if ticker in {symbol.upper() for symbol in item.symbols}:
        score += 50
    score += min(ticker_mention_count(item, ticker), 5)
    return score


def primary_match_phrase_in_title(title: str, match_phrase: str) -> bool:
    if not phrase_in_text(title, match_phrase):
        return False
    match = re.search(rf"(?<![A-Za-z0-9]){re.escape(match_phrase)}(?![A-Za-z0-9])", title, re.IGNORECASE)
    if not match:
        return False
    tail = title[match.end() : match.end() + 12].lower()
    if re.match(r"\s+(ceo|cfo|cto|coo|founder|chair|executive)\b", tail):
        return False
    return match.start() <= 40


def keyword_match_count(item: NewsItem, keywords: list[str]) -> int:
    text = f"{item.title} {item.text}".lower()
    item_terms = market_theme_terms(text)
    count = 0
    for keyword in keywords:
        normalized = str(keyword).strip().lower()
        if not normalized:
            continue
        if normalized in text:
            count += 1
            continue
        keyword_terms = market_theme_terms(normalized)
        if keyword_terms and keyword_terms.issubset(item_terms):
            count += 1
    return count


def loose_theme_hit_count(item: NewsItem, text_fragments: list[str]) -> int:
    item_terms = market_theme_terms(f"{item.title} {item.text}")
    hits = 0
    for fragment in text_fragments:
        terms = market_theme_terms(str(fragment))
        if terms and item_terms.intersection(terms):
            hits += 1
    return hits


def portfolio_watchlist_related_tickers(
    related_tickers: list[str],
    portfolio: dict[str, Holding],
    watchlist: dict[str, Holding],
) -> tuple[list[str], list[str]]:
    related = {str(ticker).upper() for ticker in related_tickers}
    portfolio_matches = sorted(related.intersection(portfolio))
    watchlist_matches = sorted(related.intersection(watchlist))
    return portfolio_matches, watchlist_matches


def why_you_see_interest(name: str, portfolio_matches: list[str], watchlist_matches: list[str]) -> str:
    parts = []
    if portfolio_matches:
        parts.append(f"you own {', '.join(portfolio_matches)}")
    if watchlist_matches:
        parts.append(f"you watch {', '.join(watchlist_matches)}")
    if not parts:
        return f"You selected {name} as a market interest."
    return f"You selected {name}; " + " and ".join(parts) + "."


def market_interest_candidates(
    items: list[NewsItem],
    interests: list[dict[str, Any]],
    portfolio: dict[str, Holding],
    watchlist: dict[str, Holding],
    max_articles_per_interest: int,
    max_total_articles: int,
    min_confidence_score: float,
) -> list[dict[str, Any]]:
    scored_matches = []
    for interest in interests:
        name = str(interest.get("name") or "").strip()
        if not name:
            continue
        sectors = [str(sector) for sector in interest.get("sectors", []) if sector]
        keywords = [str(keyword) for keyword in interest.get("keywords", []) if keyword]
        related_tickers = [str(ticker).upper() for ticker in interest.get("related_tickers", []) if ticker]
        sector_keyword_terms = set()
        for sector in sectors:
            sector_keyword_terms.update(sector_terms(sector))
        portfolio_matches, watchlist_matches = portfolio_watchlist_related_tickers(related_tickers, portfolio, watchlist)

        for item in items:
            if not item.url:
                continue
            item_terms = market_theme_terms(f"{item.title} {item.text}")
            sector_hits = item_terms.intersection(sector_keyword_terms)
            keyword_hits = keyword_match_count(item, keywords)
            loose_theme_hits = loose_theme_hit_count(item, [name, *keywords])
            related_hits = [ticker for ticker in related_tickers if item_mentions_ticker(item, ticker)]
            portfolio_hits = [ticker for ticker in portfolio if item_mentions_ticker(item, ticker)]
            watchlist_hits = [ticker for ticker in watchlist if item_mentions_ticker(item, ticker)]

            strong_match = keyword_hits >= 2 or (keyword_hits >= 1 and bool(sector_hits)) or (
                bool(related_hits) and loose_theme_hits >= 2
            )
            if not strong_match:
                continue

            score = notable_article_score(item)
            score += len(sector_hits) * 12
            score += keyword_hits * 24
            score += len(related_hits) * 18
            score += len(portfolio_hits) * 12
            score += len(watchlist_hits) * 8

            if score < min_confidence_score:
                continue

            article = compact_news_item(item)
            article["interest_match_reasons"] = {
                "sector_terms": sorted(sector_hits)[:8],
                "keyword_matches": keyword_hits,
                "theme_term_matches": loose_theme_hits,
                "related_tickers": related_hits,
                "portfolio_tickers": portfolio_hits,
                "watchlist_tickers": watchlist_hits,
                "confidence_score": round(score, 2),
            }
            scored_matches.append(
                {
                    "score": score,
                    "interest_name": name,
                    "sectors": sectors,
                    "keywords": keywords,
                    "related_tickers": related_tickers,
                    "portfolio_matches": portfolio_matches,
                    "watchlist_matches": watchlist_matches,
                    "article": article,
                }
            )

    scored_matches.sort(key=lambda item: item["score"], reverse=True)

    selected_by_interest: dict[str, dict[str, Any]] = {}
    used_urls: set[str] = set()
    total_selected = 0
    for match in scored_matches:
        if total_selected >= max_total_articles:
            break
        article = match["article"]
        if article["url"] in used_urls:
            continue
        interest_name = match["interest_name"]
        bucket = selected_by_interest.setdefault(
            interest_name,
            {
                "theme_hint": interest_name,
                "theme_type": "market_interest",
                "interest": {
                    "name": interest_name,
                    "sectors": match["sectors"],
                    "keywords": match["keywords"],
                    "related_tickers": match["related_tickers"],
                    "portfolio_tickers": match["portfolio_matches"],
                    "watchlist_tickers": match["watchlist_matches"],
                },
                "why_you_see_this": why_you_see_interest(
                    interest_name,
                    match["portfolio_matches"],
                    match["watchlist_matches"],
                ),
                "supporting_articles": [],
                "article_count": 0,
                "candidate_score": 0.0,
            },
        )
        if len(bucket["supporting_articles"]) >= max_articles_per_interest:
            continue
        bucket["supporting_articles"].append(article)
        bucket["article_count"] += 1
        bucket["candidate_score"] = round(float(bucket["candidate_score"]) + match["score"], 2)
        used_urls.add(article["url"])
        total_selected += 1

    return sorted(selected_by_interest.values(), key=lambda item: item["candidate_score"], reverse=True)


def broad_market_theme_candidates(items: list[NewsItem], max_themes: int = 4, max_articles: int = 3) -> list[dict[str, Any]]:
    buckets: dict[str, list[tuple[float, NewsItem]]] = {theme: [] for theme in MARKET_THEME_KEYWORDS}
    other: list[tuple[float, NewsItem]] = []

    for item in items:
        text_terms = market_theme_terms(f"{item.title} {item.text}")
        best_theme = None
        best_hits: set[str] = set()
        for theme, keywords in MARKET_THEME_KEYWORDS.items():
            hits = text_terms.intersection(keywords)
            if len(hits) > len(best_hits):
                best_theme = theme
                best_hits = hits

        min_hits = 1 if best_theme == "AI infrastructure and cloud" and "ai" in best_hits else 2
        if best_theme and len(best_hits) >= min_hits:
            buckets[best_theme].append((len(best_hits) * 25 + item.score, item))
        else:
            other.append((item.score, item))

    candidates = []
    for theme, scored_items in buckets.items():
        if not scored_items:
            continue
        scored_items.sort(key=lambda pair: pair[0], reverse=True)
        articles = [compact_news_item(item) for _, item in scored_items[:max_articles]]
        candidate_type = "theme" if len(scored_items) >= 2 else "notable_article"
        candidates.append(
            {
                "theme_hint": theme,
                "candidate_type": candidate_type,
                "supporting_articles": articles,
                "article_count": len(scored_items),
                "candidate_score": round(sum(score for score, _ in scored_items[:max_articles]), 2),
            }
        )

    if other:
        other.sort(key=lambda pair: pair[0], reverse=True)
        candidates.append(
            {
                "theme_hint": "Other notable market news",
                "candidate_type": "notable_article" if len(other) < 2 else "theme",
                "supporting_articles": [compact_news_item(item) for _, item in other[:max_articles]],
                "article_count": len(other),
                "candidate_score": round(sum(score for score, _ in other[:max_articles]), 2),
            }
        )

    candidates.sort(key=lambda candidate: candidate["candidate_score"], reverse=True)
    return candidates[:max_themes]


def compact_context(
    report_date: dt.date,
    window_start: dt.datetime,
    window_end: dt.datetime,
    portfolio: dict[str, Holding],
    watchlist: dict[str, Holding],
    items: list[NewsItem],
    max_items: int,
    config: dict[str, Any],
) -> dict[str, Any]:
    excluded_tickers = set(portfolio) | set(watchlist)
    sorted_items = sorted(items, key=lambda item: item.score, reverse=True)
    top_items = [item for item in sorted_items if item.ticker in excluded_tickers][:max_items]
    personalized_urls = {item.url for item in top_items if item.ticker in excluded_tickers and item.url}
    broad_candidates = [
        item
        for item in sorted_items
        if item.url not in personalized_urls
    ]
    interest_config = config.get("market_interests") or {}
    market_interests_enabled = bool(interest_config.get("enabled", True))
    if market_interests_enabled:
        fmp_article_items = [item for item in broad_candidates if item.item_type == "fmp_article"]
        fallback_broad_items = [item for item in broad_candidates if item.item_type != "fmp_article"]
        broad_market_items = (fmp_article_items + fallback_broad_items)[:20]
    else:
        broad_market_items = []
    interests = interest_config.get("interests", [])
    if not isinstance(interests, list):
        interests = []
    max_interest_articles = int(
        interest_config.get("max_articles_per_interest", interest_config.get("max_articles_per_sector", 3))
    )
    max_total_interest_articles = int(interest_config.get("max_total_articles", 5))
    min_interest_confidence = float(interest_config.get("min_confidence_score", 110))
    if market_interests_enabled and interests:
        market_theme_candidates = market_interest_candidates(
            broad_market_items,
            interests,
            portfolio,
            watchlist,
            max_interest_articles,
            max_total_interest_articles,
            min_interest_confidence,
        )
    elif not market_interests_enabled:
        market_theme_candidates = []
    else:
        sector_config = config.get("sector_reads", {})
        selected_sectors = sector_config.get("sectors", [])
        if not isinstance(selected_sectors, list):
            selected_sectors = []
        max_sector_articles = int(sector_config.get("max_articles_per_sector", 3))
        market_theme_candidates = (
            sector_article_candidates(broad_market_items, selected_sectors, max_sector_articles)
            if sector_config.get("enabled", True)
            else notable_market_article_candidates(broad_market_items)
        )
    portfolio_tickers = set(portfolio)
    watchlist_tickers = set(watchlist) - portfolio_tickers
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
        "broad_market_news": [compact_news_item(item) for item in broad_market_items],
        "market_theme_candidates": market_theme_candidates,
        "market_interests_config": {
            "enabled": market_interests_enabled,
            "max_articles_per_interest": max_interest_articles,
            "max_total_articles": max_total_interest_articles,
            "min_confidence_score": min_interest_confidence,
            "interest_names": [interest.get("name") for interest in interests if isinstance(interest, dict)],
        },
        "candidate_counts": {
            "portfolio_news": sum(1 for item in top_items if item.ticker in portfolio_tickers),
            "watchlist_news": sum(1 for item in top_items if item.ticker in watchlist_tickers),
        },
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


def get_nested_attr_or_key(value: Any, *path: str, default: Any = None) -> Any:
    current = value
    for key in path:
        if current is None:
            return default
        if isinstance(current, dict):
            current = current.get(key)
        else:
            current = getattr(current, key, None)
    return default if current is None else current


def model_pricing(config: dict[str, Any], model: str) -> dict[str, float]:
    pricing = config.get("openai", {}).get("pricing_per_1m_tokens", {})
    if not isinstance(pricing, dict):
        pricing = {}
    model_rates = pricing.get(model) or pricing.get("default") or {}
    return {
        "input": float(model_rates.get("input", 0)),
        "cached_input": float(model_rates.get("cached_input", model_rates.get("input", 0))),
        "output": float(model_rates.get("output", 0)),
    }


def openai_usage_summary(response: Any, model: str, config: dict[str, Any]) -> dict[str, Any]:
    usage = get_nested_attr_or_key(response, "usage", default={})
    input_tokens = int(get_nested_attr_or_key(usage, "input_tokens", default=0) or 0)
    output_tokens = int(get_nested_attr_or_key(usage, "output_tokens", default=0) or 0)
    total_tokens = int(get_nested_attr_or_key(usage, "total_tokens", default=input_tokens + output_tokens) or 0)
    cached_input_tokens = int(
        get_nested_attr_or_key(usage, "input_tokens_details", "cached_tokens", default=0) or 0
    )
    billable_input_tokens = max(input_tokens - cached_input_tokens, 0)
    rates = model_pricing(config, model)
    input_cost = billable_input_tokens * rates["input"] / 1_000_000
    cached_input_cost = cached_input_tokens * rates["cached_input"] / 1_000_000
    output_cost = output_tokens * rates["output"] / 1_000_000
    total_cost = input_cost + cached_input_cost + output_cost
    return {
        "provider": "openai",
        "model": model,
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_input_tokens,
        "billable_input_tokens": billable_input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "pricing_per_1m_tokens_usd": rates,
        "cost_usd": {
            "input": round(input_cost, 8),
            "cached_input": round(cached_input_cost, 8),
            "output": round(output_cost, 8),
            "total": round(total_cost, 8),
        },
    }


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
            "article_summary": [
                item.get("snippet", "No article summary available."),
            ],
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
        "top_market_themes": build_default_market_themes(context),
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


def generate_report_with_openai(context: dict[str, Any], config: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
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
        "task": (
            "Create a daily investment morning report from this prefiltered context. "
            "For the top_market_themes section, create a short list of notable market reads from context.market_theme_candidates. "
            "Each item must use exactly one candidate and exactly that candidate's single supporting article. "
            "Do not turn a single article into a broad trend."
        ),
        "writing_guidance": [
            "Write for beginner investors: explain financial implications plainly and avoid unexplained jargon.",
            "For portfolio_news and watchlist_news, keep why_it_matters short, then add article_summary with 3-5 factual bullet points based only on the supplied snippet/title/source metadata.",
            "For portfolio_news and watchlist_news, include only articles whose context.ranked_news ticker exactly matches that section item ticker.",
            "Never include portfolio tickers in watchlist_news.",
            "For thesis_impact, explain how the news could affect the user's stated thesis, key metrics, red flags, and action triggers.",
            "Only include portfolio holdings in thesis_impact; do not include watchlist-only companies there.",
            "Use top_market_themes as notable market reads outside the user's portfolio and watchlist.",
            "For top_market_themes, do not combine articles from different market_theme_candidates into one item.",
            "Do not reuse the same source article URL across multiple top_market_themes.",
            "For top_market_themes, set theme_type to notable_article, use the article title or a very close paraphrase as theme, and summarize only that article's actual topic.",
            "Do not add macro, geopolitical, regulatory, or sector claims to a notable market read unless directly supported by its single source article.",
            "When impact is uncertain, say what is unknown and what evidence would clarify it.",
            "Do not give buy, sell, hold, position sizing, price target, or trading advice.",
        ],
        "market_interest_guidance": [
            "Treat top_market_themes as personalized market interests, not generic sector reads.",
            "Use context.market_theme_candidates only; each candidate is one configured market interest from config.market_interests.",
            "For each item, set theme to the market interest name exactly as configured, such as AI Infrastructure.",
            "Use why_you_see_this from the candidate and summarize why this interest is relevant to the user's portfolio/watchlist.",
            "Create articles from the supplied source_articles for that interest. For each article, write a concise two-sentence summary based only on that article's title and snippet.",
            "If a supplied article's interest_match_reasons do not clearly support the interest, omit that article rather than forcing it in.",
            "Fill today_signals with 2-4 short bullets based on the selected articles.",
            "Fill read_through with a cautious beginner-friendly explanation of what these signals may imply for the interest, without buy/sell advice.",
            "Do not combine different market interests and do not add claims that are not supported by the supplied articles.",
        ],
        "output_schema": {
            "report_date": "YYYY-MM-DD",
            "executive_summary": ["string"],
            "portfolio_news": [
                {
                    "ticker": "string",
                    "headline": "string",
                    "why_it_matters": "string",
                    "article_summary": [
                        "bullet point with the most important facts from the article, written for a beginner investor"
                    ],
                    "attention_label": "no_action|monitor|review_thesis|review_valuation|deeper_analysis_needed",
                    "source": "string",
                    "source_url": "string",
                }
            ],
            "thesis_impact": [
                {
                    "ticker": "string",
                    "impact": "supports|challenges|mixed|unclear",
                    "rationale": "beginner-friendly explanation of how the news relates to the user's thesis",
                    "portfolio_relevance": "explain in practical terms why this may matter for an existing holder, without buy/sell advice",
                    "thesis_points_affected": ["specific thesis, metric, red flag, or action trigger affected by the news"],
                    "possible_positive_readthrough": "string",
                    "possible_negative_readthrough": "string",
                    "monitor_next": "concrete metric, filing, management comment, or follow-up event to watch",
                }
            ],
            "watchlist_news": [
                {
                    "ticker": "string",
                    "headline": "string",
                    "why_it_matters": "string",
                    "article_summary": [
                        "bullet point with the most important facts from the article, written for a beginner investor"
                    ],
                    "attention_label": "no_action|monitor|review_thesis|review_valuation|deeper_analysis_needed",
                    "source": "string",
                    "source_url": "string",
                }
            ],
            "top_market_themes": [
                {
                    "theme": "string",
                    "theme_type": "market_interest",
                    "why_you_see_this": "string",
                    "today_signals": ["short bullet about what the selected articles signal today"],
                    "read_through": "beginner-friendly explanation of the broader read-through for this interest",
                    "summary": "string",
                    "articles": [
                        {
                            "headline": "string",
                            "summary": "2 sentence beginner-friendly article summary",
                            "source": "string",
                            "source_url": "string",
                        }
                    ],
                    "source_articles": [
                        {
                            "title": "string",
                            "source": "string",
                            "url": "string",
                        }
                    ],
                }
            ],
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
    if not context.get("market_theme_candidates"):
        user["task"] = "Create a daily investment morning report from this prefiltered context. Return top_market_themes as an empty list."
        user["writing_guidance"] = [
            item for item in user["writing_guidance"] if "top_market_themes" not in item
        ]
        user.pop("market_interest_guidance", None)
        user["output_schema"]["top_market_themes"] = []
    response = client.responses.create(
        model=model,
        input=[
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
        ],
    )
    report = parse_model_json(response.output_text)
    report.setdefault("report_date", context["report_date"])
    return validate_report(report, context), openai_usage_summary(response, model, config)


def skipped_openai_usage(config: dict[str, Any]) -> dict[str, Any]:
    model = config.get("openai", {}).get("model", "gpt-4.1-mini")
    return {
        "provider": "openai",
        "model": model,
        "skipped": True,
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "billable_input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "pricing_per_1m_tokens_usd": model_pricing(config, model),
        "cost_usd": {
            "input": 0,
            "cached_input": 0,
            "output": 0,
            "total": 0,
        },
    }


def validate_label(value: str | None) -> str:
    if value in ATTENTION_LABELS:
        return value
    return "monitor"


def human_label(value: Any) -> str:
    return str(value or "").replace("_", " ").strip().upper()


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


def filter_news_sections_to_context(report: dict[str, Any], context: dict[str, Any]) -> None:
    portfolio_tickers = {str(item.get("ticker") or "").upper() for item in context.get("portfolio", [])}
    watchlist_tickers = {str(item.get("ticker") or "").upper() for item in context.get("watchlist", [])} - portfolio_tickers
    news_by_url = {
        str(item.get("url") or ""): item
        for item in context.get("ranked_news", [])
        if item.get("url")
    }

    for section, allowed_tickers in (
        ("portfolio_news", portfolio_tickers),
        ("watchlist_news", watchlist_tickers),
    ):
        filtered = []
        for item in report.get(section, []):
            ticker = str(item.get("ticker") or "").upper()
            if ticker not in allowed_tickers:
                continue
            source_url = str(item.get("source_url") or item.get("url") or "")
            matching_news = news_by_url.get(source_url)
            if not matching_news:
                continue
            if str(matching_news.get("ticker") or "").upper() != ticker:
                continue
            filtered.append(item)
        report[section] = filtered


def default_news_entry_from_context_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "ticker": item.get("ticker") or "MARKET",
        "headline": item.get("title", ""),
        "why_it_matters": "This article directly mentions a company on the watchlist and may be relevant to monitor.",
        "article_summary": [item.get("snippet") or "No article summary available."],
        "attention_label": validate_label("monitor"),
        "source": item.get("source", ""),
        "source_url": item.get("url", ""),
    }


def fill_missing_watchlist_news(report: dict[str, Any], context: dict[str, Any], limit: int = 3) -> None:
    if report.get("watchlist_news"):
        return

    portfolio_tickers = {str(item.get("ticker") or "").upper() for item in context.get("portfolio", [])}
    watchlist_tickers = {str(item.get("ticker") or "").upper() for item in context.get("watchlist", [])} - portfolio_tickers
    used_urls = {
        str(item.get("source_url") or item.get("url") or "")
        for section in ("portfolio_news", "watchlist_news")
        for item in report.get(section, [])
        if item.get("source_url") or item.get("url")
    }

    fallback = []
    for item in context.get("ranked_news", []):
        ticker = str(item.get("ticker") or "").upper()
        url = str(item.get("url") or "")
        if ticker not in watchlist_tickers or not url or url in used_urls:
            continue
        fallback.append(default_news_entry_from_context_item(item))
        used_urls.add(url)
        if len(fallback) >= limit:
            break

    report["watchlist_news"] = fallback


def article_from_news(news: dict[str, Any]) -> dict[str, str]:
    return {
        "headline": clean_text(news.get("headline") or news.get("title") or ""),
        "title": clean_text(news.get("title") or news.get("headline") or ""),
        "summary": clean_text(news.get("summary") or news.get("snippet") or ""),
        "source": clean_text(news.get("source") or ""),
        "source_url": clean_url(news.get("source_url") or news.get("url") or ""),
        "url": clean_url(news.get("url") or news.get("source_url") or ""),
    }


def configured_tickers(context: dict[str, Any]) -> set[str]:
    tickers = set()
    for section in ("portfolio", "watchlist"):
        for item in context.get(section, []):
            ticker = item.get("ticker")
            if ticker:
                tickers.add(str(ticker).upper())
    return tickers


def news_mentions_configured_ticker(news: dict[str, Any], tickers: set[str]) -> bool:
    ticker = str(news.get("ticker") or "").upper()
    symbols = {str(symbol).upper() for symbol in news.get("symbols", []) if symbol}
    return ticker in tickers or bool(symbols.intersection(tickers))


def matching_articles_for_theme(theme: dict[str, Any], context: dict[str, Any], limit: int = 3) -> list[dict[str, str]]:
    theme_terms = normalize_match_text(f"{theme.get('theme', '')} {theme.get('summary', '')}")
    excluded_tickers = configured_tickers(context)
    scored_articles = []
    for news in context.get("broad_market_news", []):
        if not news.get("url"):
            continue
        if news_mentions_configured_ticker(news, excluded_tickers):
            continue
        article_terms = normalize_match_text(f"{news.get('title', '')} {news.get('snippet', '')}")
        overlap = len(theme_terms.intersection(article_terms))
        relevance = float(news.get("relevance_score") or 0)
        score = overlap * 10 + relevance
        scored_articles.append((score, article_from_news(news)))
    scored_articles.sort(key=lambda item: item[0], reverse=True)
    return [article for score, article in scored_articles[:limit] if score > 0 and article["url"]]


def build_default_market_themes(context: dict[str, Any]) -> list[dict[str, Any]]:
    themes = []
    used_urls: set[str] = set()
    for candidate in context.get("market_theme_candidates", []):
        if len(themes) >= 3:
            break
        articles = [
            article_from_news(article)
            for article in candidate.get("supporting_articles", [])
            if article.get("url") and article.get("url") not in used_urls
        ][:3]
        if not articles:
            continue
        used_urls.update(article["url"] for article in articles if article.get("url"))
        themes.append(
            {
                "theme": candidate.get("theme_hint", "Notable market article"),
                "theme_type": candidate.get("theme_type", "market_interest"),
                "why_you_see_this": candidate.get("why_you_see_this", ""),
                "today_signals": [],
                "read_through": "",
                "summary": "Notable market article selected from broad market news outside the configured portfolio and watchlist.",
                "source_articles": articles,
            }
        )
    return themes


def normalize_market_themes(report: dict[str, Any], context: dict[str, Any]) -> None:
    if report.get("top_market_themes_v2") and not report.get("top_market_themes"):
        report["top_market_themes"] = report["top_market_themes_v2"]

    normalized = []
    excluded_tickers = configured_tickers(context)
    used_urls: set[str] = set()
    for section in ("portfolio_news", "watchlist_news"):
        for existing_item in report.get(section, []):
            existing_url = existing_item.get("source_url") or existing_item.get("url")
            if existing_url:
                used_urls.add(str(existing_url))
    for item in report.get("top_market_themes", []):
        if isinstance(item, str):
            theme = {"theme": item, "theme_type": "theme", "summary": "", "source_articles": []}
        elif isinstance(item, dict):
            theme = {
                "theme": str(item.get("theme") or item.get("title") or "Market theme"),
                "theme_type": str(item.get("theme_type") or item.get("candidate_type") or "theme"),
                "summary": str(item.get("summary") or item.get("why_it_matters") or ""),
                "source_articles": item.get("source_articles") or item.get("articles") or item.get("sources") or [],
            }
        else:
            continue

        source_articles = []
        for article in theme.get("source_articles", []):
            if not isinstance(article, dict):
                continue
            url = article.get("url") or article.get("source_url")
            if not url:
                continue
            all_news = context.get("ranked_news", []) + context.get("broad_market_news", [])
            matching_news = next((news for news in all_news if news.get("url") == url), None)
            if matching_news and news_mentions_configured_ticker(matching_news, excluded_tickers):
                continue
            if url in used_urls:
                continue
            source_articles.append(
                {
                    "title": str(article.get("title") or article.get("headline") or url),
                    "source": str(article.get("source") or ""),
                    "url": str(url),
                }
            )
            used_urls.add(str(url))
            if len(source_articles) >= 3:
                break

        best_candidate = best_candidate_for_theme(theme, context)
        if best_candidate:
            theme["theme"] = best_candidate.get("theme_hint", theme.get("theme", "Market Interest"))
            theme["theme_type"] = best_candidate.get("theme_type", theme.get("theme_type", "market_interest"))
            theme["why_you_see_this"] = theme.get("why_you_see_this") or best_candidate.get("why_you_see_this", "")
        candidate_articles = candidate_articles_for_theme(theme, context)
        candidate_articles = [
            article for article in candidate_articles if article.get("url") and article["url"] not in used_urls
        ]
        if not source_articles:
            source_articles = candidate_articles
        elif candidate_articles and not theme_articles_fit_candidate(source_articles, candidate_articles):
            used_urls.difference_update(article["url"] for article in source_articles if article.get("url"))
            source_articles = candidate_articles
        used_urls.update(article["url"] for article in source_articles if article.get("url"))
        theme["source_articles"] = source_articles[:3]
        theme["summary"] = ""
        normalize_interest_label(theme)
        if isinstance(theme.get("today_signals"), str):
            theme["today_signals"] = [theme["today_signals"]]
        elif not isinstance(theme.get("today_signals"), list):
            theme["today_signals"] = []
        normalize_sector_read_articles(theme)
        if not theme.get("articles"):
            continue
        normalized.append(theme)

    report["top_market_themes"] = normalized


def filter_thesis_impact_to_portfolio(report: dict[str, Any], context: dict[str, Any]) -> None:
    portfolio_tickers = {str(item.get("ticker") or "").upper() for item in context.get("portfolio", [])}
    report["thesis_impact"] = [
        item
        for item in report.get("thesis_impact", [])
        if str(item.get("ticker") or "").upper() in portfolio_tickers
    ]


def best_candidate_for_theme(theme: dict[str, Any], context: dict[str, Any]) -> dict[str, Any] | None:
    candidates = context.get("market_theme_candidates", [])
    if not candidates:
        return None

    theme_terms = normalize_match_text(f"{theme.get('theme', '')} {theme.get('summary', '')}")
    best_candidate = None
    best_score = -1
    for candidate in candidates:
        if str(candidate.get("theme_hint") or "").lower() == str(theme.get("theme") or "").lower():
            return candidate
        candidate_text = candidate.get("theme_hint", "")
        for article in candidate.get("supporting_articles", []):
            candidate_text += f" {article.get('title', '')} {article.get('snippet', '')}"
        candidate_terms = normalize_match_text(candidate_text)
        overlap = len(theme_terms.intersection(candidate_terms))
        score = overlap * 10 + float(candidate.get("candidate_score") or 0)
        if score > best_score:
            best_score = score
            best_candidate = candidate

    return best_candidate


def candidate_articles_for_theme(theme: dict[str, Any], context: dict[str, Any]) -> list[dict[str, str]]:
    best_candidate = best_candidate_for_theme(theme, context)
    if not best_candidate:
        return matching_articles_for_theme(theme, context, limit=3)

    if not best_candidate:
        return []
    return [
        article_from_news(article)
        for article in best_candidate.get("supporting_articles", [])
        if article.get("url")
    ][:3]


def theme_articles_fit_candidate(source_articles: list[dict[str, str]], candidate_articles: list[dict[str, str]]) -> bool:
    candidate_urls = {article["url"] for article in candidate_articles if article.get("url")}
    if not candidate_urls:
        return False
    source_urls = {article["url"] for article in source_articles if article.get("url")}
    return bool(source_urls.intersection(candidate_urls))


def normalize_sector_read_articles(theme: dict[str, Any]) -> None:
    raw_articles = theme.get("articles") or theme.get("source_articles") or []
    normalized = []
    for article in raw_articles[:3]:
        if not isinstance(article, dict):
            continue
        source_url = clean_url(article.get("source_url") or article.get("url"))
        if not source_url:
            continue
        headline = clean_text(article.get("headline") or article.get("title") or source_url)
        summary = clean_text(article.get("summary") or article.get("snippet") or "")
        normalized.append(
            {
                "headline": headline,
                "summary": summary,
                "source": clean_text(article.get("source") or ""),
                "source_url": str(source_url),
            }
        )
    theme["articles"] = normalized


def normalize_interest_label(theme: dict[str, Any]) -> None:
    interest = theme.get("interest")
    if isinstance(interest, dict) and interest.get("name"):
        theme["theme"] = str(interest["name"])
        return
    if theme.get("theme_type") == "market_interest":
        theme["theme"] = str(theme.get("theme") or "").strip() or "Market Interest"
        return
    sector = theme.get("sector")
    raw_theme = str(theme.get("theme") or "")
    if sector:
        theme["theme"] = sector_label(str(sector))
        return
    normalized_key = raw_theme.strip().lower().replace(" ", "_").replace("-", "_")
    if normalized_key in SECTOR_KEYWORDS:
        theme["theme"] = sector_label(normalized_key)
    else:
        theme["theme"] = sector_label(raw_theme)


def validate_report(report: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    report["report_date"] = str(report.get("report_date") or context["report_date"])
    for key in ("executive_summary", "portfolio_news", "thesis_impact", "watchlist_news", "top_market_themes", "attention_flags", "sources"):
        if not isinstance(report.get(key), list):
            report[key] = []
    if context.get("market_theme_candidates"):
        normalize_market_themes(report, context)
    else:
        report["top_market_themes"] = []
    filter_thesis_impact_to_portfolio(report, context)
    for section in ("portfolio_news", "watchlist_news"):
        for item in report[section]:
            item["attention_label"] = validate_label(item.get("attention_label"))
            if isinstance(item.get("article_summary"), str):
                item["article_summary"] = [item["article_summary"]]
            elif not isinstance(item.get("article_summary"), list):
                item["article_summary"] = []
        enrich_report_item_sources(report[section], context)
    filter_news_sections_to_context(report, context)
    fill_missing_watchlist_news(report, context)
    for item in report["thesis_impact"]:
        if isinstance(item.get("thesis_points_affected"), str):
            item["thesis_points_affected"] = [item["thesis_points_affected"]]
        elif not isinstance(item.get("thesis_points_affected"), list):
            item["thesis_points_affected"] = []
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
    env.filters["human_label"] = human_label
    template = env.get_template("email_report.html")
    return template.render(
        report=report,
        subject=subject,
        generated_at=dt.datetime.now(tz=PRAGUE_TZ).date().isoformat(),
        logo_src=email_asset_src("ma-logo.png"),
        badge_src=email_asset_src("ma-badge.png"),
        icon_src=email_asset_src("ma-icon.png"),
    )


def email_asset_src(filename: str) -> str | None:
    base_url = os.getenv("EMAIL_ASSET_BASE_URL")
    if base_url:
        return f"{base_url.rstrip('/')}/{filename}"

    path = ROOT / "assets" / filename
    if not path.is_file():
        return None
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def send_email(subject: str, html: str, recipient_email: str | None = None) -> None:
    resend = require_dependency("resend")

    api_key = os.getenv("RESEND_API_KEY")
    from_address = os.getenv("RESEND_FROM", "onboarding@resend.dev")
    if recipient_email:
        recipient = recipient_email.strip()
        to_addresses = [recipient] if recipient else []
    else:
        recipients_raw = os.getenv("RESEND_TO") or ""
        to_addresses = [item.strip() for item in recipients_raw.split(",") if item.strip()]
    if not api_key or not from_address or not to_addresses:
        raise SystemExit("RESEND_API_KEY, RESEND_FROM, and a recipient email must be set to send email.")

    resend.api_key = api_key
    resend.Emails.send(
        {
            "from": from_address,
            "to": to_addresses,
            "subject": subject,
            "html": html,
        }
    )


def get_user_email(user_id: str) -> str | None:
    try:
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise RuntimeError("Missing dependency 'psycopg'. Install dependencies with: pip install -r requirements.txt") from exc

    from database import connection

    with connection(row_factory=dict_row) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                select email
                from public.users
                where id = %(id)s
                """,
                {"id": user_id},
            )
            row = cursor.fetchone()

    email = str(row["email"]).strip() if row and row.get("email") else ""
    return email or None


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
    typed_raw_items: list[tuple[dict[str, Any], str]] = []
    typed_raw_items.extend(
        (item, "stock_news")
        for item in client.stock_news(
            symbols=symbols,
            start=window_start.date(),
            end=window_end.date(),
            limit=int(fmp_config.get("news_limit_per_ticker", 30)) * max(1, len(symbols)),
        )
    )
    typed_raw_items.extend(
        (item, "general_news")
        for item in client.general_news(limit=int(fmp_config.get("general_news_limit", 40)))
    )
    typed_raw_items.extend(
        (item, "fmp_article")
        for item in client.fmp_articles(limit=int(fmp_config.get("fmp_articles_limit", 30)))
    )

    normalized = [
        item
        for item in (normalize_news_item(raw, item_type=item_type) for raw, item_type in typed_raw_items)
        if item is not None
    ]
    filtered = []
    for item in normalized:
        if source_domain_is_excluded(item, config):
            continue
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
    return prefix


def resolve_report_date(date_arg: str) -> dt.date:
    if date_arg == "latest":
        return latest_completed_us_trading_day()

    report_date = dt.date.fromisoformat(date_arg)
    if not is_us_trading_day(report_date):
        raise SystemExit(f"{report_date} is not a regular US trading day.")
    return report_date


def write_report_outputs(
    *,
    context: dict[str, Any],
    report: dict[str, Any],
    usage: dict[str, Any],
    html: str,
    context_json: str | Path,
    output_json: str | Path,
    usage_json: str | Path,
    output_html: str | Path,
) -> None:
    for output_path, payload, is_json in (
        (Path(context_json), context, True),
        (Path(output_json), report, True),
        (Path(usage_json), usage, True),
        (Path(output_html), html, False),
    ):
        path = output_path if output_path.is_absolute() else ROOT / output_path
        path.parent.mkdir(parents=True, exist_ok=True)
        if is_json:
            path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        else:
            path.write_text(str(payload), encoding="utf-8")


def run_report_for_user(
    *,
    user_id: str,
    recipient_email: str | None = None,
    date_arg: str = "latest",
    config_path: str | Path = "config.yaml",
    send_email_report: bool = False,
    skip_openai: bool = False,
    output_html: str | Path = "out/report.html",
    output_json: str | Path = "out/report.json",
    context_json: str | Path = "out/context.json",
    usage_json: str | Path = "out/usage.json",
) -> dict[str, Any]:
    config_file = Path(config_path)
    config = load_yaml(config_file if config_file.is_absolute() else ROOT / config_file)
    portfolio = load_portfolio_from_db(user_id)
    watchlist = load_watchlist_from_db(user_id)

    report_date = resolve_report_date(date_arg)

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
        config=config,
    )

    if skip_openai:
        report = validate_report(default_report(context), context)
        usage = skipped_openai_usage(config)
    else:
        if not os.getenv("OPENAI_API_KEY"):
            raise SystemExit("OPENAI_API_KEY is required unless --skip-openai is used.")
        report, usage = generate_report_with_openai(context, config)

    subject = build_subject(config, report_date)
    html = render_email(report, subject)

    write_report_outputs(
        context=context,
        report=report,
        usage=usage,
        html=html,
        context_json=context_json,
        output_json=output_json,
        usage_json=usage_json,
        output_html=output_html,
    )

    if send_email_report:
        recipient_email = recipient_email or get_user_email(user_id)
        if not recipient_email:
            raise SystemExit(f"User {user_id} does not have an email address.")
        send_email(subject, html, recipient_email=recipient_email)

    return {
        "subject": subject,
        "report_date": report_date.isoformat(),
        "usage": usage,
        "output_html": str(output_html),
        "output_json": str(output_json),
        "context_json": str(context_json),
        "usage_json": str(usage_json),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a personalized investment morning report.")
    parser.add_argument("--date", default="latest", help="'latest' or an explicit YYYY-MM-DD US trading date.")
    parser.add_argument("--config", default="config.yaml", help="Path to config YAML.")
    parser.add_argument("--user-id", help="User ID whose portfolio should be used for the report.")
    parser.add_argument("--check-db", action="store_true", help="Verify the configured Neon/Postgres connection and exit.")
    parser.add_argument(
        "--check-auth-config",
        action="store_true",
        help="Verify Neon Auth environment configuration and exit.",
    )
    parser.add_argument("--send-email", action="store_true", help="Send the generated report through Resend.")
    parser.add_argument("--recipient-email", help="Send the report to this email instead of the user's DB email.")
    parser.add_argument("--skip-openai", action="store_true", help="Use deterministic fallback report generation.")
    parser.add_argument("--output-html", default="out/report.html", help="Where to write the rendered HTML report.")
    parser.add_argument("--output-json", default="out/report.json", help="Where to write the structured report JSON.")
    parser.add_argument("--context-json", default="out/context.json", help="Where to write the compact OpenAI input JSON.")
    parser.add_argument("--usage-json", default="out/usage.json", help="Where to write OpenAI token usage and cost JSON.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_dotenv_if_available()

    if args.check_db or args.check_auth_config:
        ok = True
        if args.check_db:
            try:
                from database import check_connection

                info = check_connection()
                version = info.get("version", "").splitlines()[0]
                print(
                    "Database connection OK: "
                    f"database={info.get('database')} role={info.get('role')} host={info.get('host')}"
                )
                print(f"Postgres: {version}")
            except Exception as exc:
                ok = False
                print(f"Database connection failed: {exc}", file=sys.stderr)

        if args.check_auth_config:
            from neon_auth import load_settings

            settings = load_settings()
            missing = settings.missing_required()
            if missing:
                ok = False
                print(f"Neon Auth config incomplete. Missing: {', '.join(missing)}", file=sys.stderr)
            else:
                providers = []
                if settings.email_password_enabled:
                    providers.append("email/password")
                if settings.google_oauth_enabled:
                    providers.append("Google OAuth")
                print(f"Neon Auth config OK: url={settings.auth_url} providers={', '.join(providers) or 'none'}")

        return 0 if ok else 1

    if not args.user_id:
        raise SystemExit("--user-id is required when generating a report.")

    result = run_report_for_user(
        user_id=args.user_id,
        recipient_email=args.recipient_email,
        date_arg=args.date,
        config_path=args.config,
        send_email_report=args.send_email,
        skip_openai=args.skip_openai,
        output_html=args.output_html,
        output_json=args.output_json,
        context_json=args.context_json,
        usage_json=args.usage_json,
    )
    subject = str(result["subject"])
    usage = result["usage"]

    if args.send_email:
        print(f"Sent report email: {subject}")
    else:
        print(f"Generated report: {subject}")
        print(f"HTML: {Path(args.output_html)}")
    if usage.get("skipped"):
        print("OpenAI usage: skipped")
    else:
        print(
            "OpenAI usage: "
            f"input={usage.get('input_tokens', 0)} "
            f"cached_input={usage.get('cached_input_tokens', 0)} "
            f"output={usage.get('output_tokens', 0)} "
            f"total={usage.get('total_tokens', 0)} "
            f"cost=${float(usage.get('cost_usd', {}).get('total', 0)):.6f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
