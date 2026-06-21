from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
from typing import Any, Callable

from report import FmpClient, load_yaml, log_openai_usage, openai_usage_summary, parse_model_json


ROOT = Path(__file__).resolve().parent
DEEP_RESEARCH_MODEL = "gpt-5.4"


def safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def first_number(*values: Any) -> float | None:
    for value in values:
        number = safe_float(value)
        if number is not None:
            return number
    return None


def first_number_from_rows(rows: list[dict[str, Any]], *names: str) -> float | None:
    for row in rows:
        value = first_number(get_any(row, *names))
        if value is not None:
            return value
    return None


def get_any(data: dict[str, Any], *names: str) -> Any:
    if not isinstance(data, dict):
        return None
    lower_map = {str(key).lower(): value for key, value in data.items()}
    for name in names:
        if name in data:
            value = data.get(name)
            if value not in (None, "", []):
                return value
        value = lower_map.get(str(name).lower())
        if value not in (None, "", []):
            return value
    return None


def deep_get_any(data: Any, *names: str) -> Any:
    if isinstance(data, dict):
        value = get_any(data, *names)
        if value not in (None, "", []):
            return value
        for child in data.values():
            value = deep_get_any(child, *names)
            if value not in (None, "", []):
                return value
    elif isinstance(data, list):
        for child in data:
            value = deep_get_any(child, *names)
            if value not in (None, "", []):
                return value
    return None


def ratio_to_percent(value: Any) -> float | None:
    number = safe_float(value)
    if number is None:
        return None
    return number * 100 if abs(number) <= 1 else number


def divide_or_none(numerator: Any, denominator: Any) -> float | None:
    numerator_value = safe_float(numerator)
    denominator_value = safe_float(denominator)
    if numerator_value is None or denominator_value in (None, 0):
        return None
    return numerator_value / denominator_value


def percent_growth(newer: Any, older: Any) -> float | None:
    older_value = safe_float(older)
    newer_value = safe_float(newer)
    if older_value in (None, 0) or newer_value is None:
        return None
    return ((newer_value / older_value) - 1) * 100


def cagr(newer: Any, older: Any, periods: int) -> float | None:
    newer_value = safe_float(newer)
    older_value = safe_float(older)
    if newer_value is None or older_value in (None, 0) or periods <= 0 or newer_value <= 0 or older_value <= 0:
        return None
    return ((newer_value / older_value) ** (1 / periods) - 1) * 100


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def fmp_error_row(item: dict[str, Any]) -> bool:
    keys = {str(key).strip().lower() for key in item}
    return bool(keys & {"error", "error message"})


def fmp_items(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict):
        items = data.get("historical") or data.get("historicalStockList") or data.get("data") or []
        if not items and data:
            items = [data]
    elif isinstance(data, list):
        items = data
    else:
        return []
    return [item for item in items if isinstance(item, dict) and not fmp_error_row(item)]


def unique_rows(rows: list[dict[str, Any]], keys: tuple[str, ...]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for row in rows:
        marker = "|".join(str(row.get(key) or "") for key in keys)
        if marker in seen:
            continue
        seen.add(marker)
        unique.append(row)
    return unique


def symbol_aliases(symbol: str) -> set[str]:
    cleaned = str(symbol or "").strip().upper()
    if not cleaned:
        return set()
    return {cleaned, cleaned.replace(".", "-"), cleaned.replace("-", ".")}


def row_matches_symbol(row: dict[str, Any], symbol: str) -> bool:
    aliases = symbol_aliases(symbol)
    if not aliases:
        return False
    values = [
        get_any(row, "symbol", "ticker", "securitySymbol", "issuerTradingSymbol", "companyTicker", "issuerTicker"),
        get_any(row, "stockSymbol", "issuerSymbol", "tradingSymbol"),
    ]
    for value in values:
        if value in (None, "", []):
            continue
        candidate = str(value).strip().upper()
        candidate = candidate.split(":")[-1]
        if candidate in aliases or candidate.replace(".", "-") in aliases or candidate.replace("-", ".") in aliases:
            return True
    return False


def filter_rows_for_symbol(rows: list[dict[str, Any]], symbol: str) -> list[dict[str, Any]]:
    return [row for row in rows if row_matches_symbol(row, symbol)]


def rows_for_symbol_or_without_symbol(rows: list[dict[str, Any]], symbol: str) -> list[dict[str, Any]]:
    filtered = []
    symbol_keys = ("symbol", "ticker", "securitySymbol", "issuerTradingSymbol", "companyTicker", "issuerTicker", "stockSymbol", "issuerSymbol", "tradingSymbol")
    for row in rows:
        if row_matches_symbol(row, symbol):
            filtered.append(row)
            continue
        if not any(get_any(row, key) not in (None, "", []) for key in symbol_keys):
            filtered.append(row)
    return filtered


def first_item(data: Any) -> dict[str, Any]:
    items = fmp_items(data)
    return items[0] if items else {}


def try_fmp_get(client: FmpClient, endpoint: str, params: dict[str, Any]) -> Any:
    try:
        return client.get(endpoint, params)
    except Exception:
        return None


def normalize_price_history(data: Any) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for item in fmp_items(data):
        date_value = item.get("date")
        close = first_number(item.get("close"), item.get("adjClose"), item.get("price"))
        if not date_value or close is None:
            continue
        points.append({"date": str(date_value)[:10], "close": close})
    return sorted(points, key=lambda point: point["date"])


def parse_fmp_date(value: Any) -> dt.date | None:
    if not value:
        return None
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def fiscal_quarter_number(row: dict[str, Any]) -> int | None:
    value = get_any(row, "quarter", "fiscalQuarter", "fiscal_quarter", "fiscalQ", "q")
    if value in (None, "", []):
        value = get_any(row, "period")
    if value in (None, "", []):
        return None
    text = str(value).strip().upper()
    if not text or text in {"FY", "ANNUAL"}:
        return None
    if text.startswith("Q"):
        text = text[1:].split()[0]
    number = safe_float(text)
    if number is None:
        return None
    quarter = int(number)
    return quarter if 1 <= quarter <= 4 else None


def fiscal_year_value(row: dict[str, Any]) -> str | None:
    year = get_any(row, "calendarYear", "fiscalYear", "fiscal_year", "year")
    if year not in (None, "", []):
        number = safe_float(year)
        return str(int(number)) if number else str(year)
    date_value = get_any(row, "fiscalDateEnding", "date", "publishedDate")
    if date_value:
        return str(date_value)[:4]
    return None


def fiscal_quarter_label(row: dict[str, Any]) -> str | None:
    quarter = fiscal_quarter_number(row)
    if not quarter:
        return None
    year = fiscal_year_value(row)
    return f"Q{quarter} {year}" if year else f"Q{quarter}"


def normalize_earnings_report(row: dict[str, Any], report_type: str) -> dict[str, Any]:
    return {
        "symbol": row.get("symbol"),
        "date": row.get("date") or row.get("fiscalDateEnding"),
        "report_type": report_type,
        "fiscal_quarter": fiscal_quarter_label(row),
        "fiscal_year": fiscal_year_value(row),
        "eps_actual": row.get("epsActual") or row.get("eps"),
        "eps_estimated": row.get("epsEstimated") or row.get("epsEstimate"),
        "revenue_actual": row.get("revenueActual") or row.get("revenue"),
        "revenue_estimated": row.get("revenueEstimated"),
        "last_updated": row.get("lastUpdated") or row.get("updatedFromDate"),
    }


def enrich_earnings_row_with_statement_period(row: dict[str, Any], quarter_rows: list[dict[str, Any]]) -> dict[str, Any]:
    if fiscal_quarter_label(row):
        return row
    report_date = parse_fmp_date(row.get("date"))
    fiscal_date = parse_fmp_date(row.get("fiscalDateEnding"))
    matches: list[tuple[int, dict[str, Any]]] = []
    for statement in quarter_rows:
        statement_date = parse_fmp_date(statement.get("date") or statement.get("fiscalDateEnding"))
        if not statement_date:
            continue
        if fiscal_date and statement_date == fiscal_date:
            matches.append((0, statement))
            continue
        if report_date and statement_date <= report_date:
            days = (report_date - statement_date).days
            if 0 <= days <= 140:
                matches.append((days, statement))
    if not matches:
        return row
    statement = sorted(matches, key=lambda item: item[0])[0][1]
    enriched = dict(row)
    for key in ("period", "quarter", "calendarYear", "fiscalYear"):
        if enriched.get(key) in (None, "", []):
            enriched[key] = statement.get(key)
    if enriched.get("fiscalDateEnding") in (None, "", []):
        enriched["fiscalDateEnding"] = statement.get("fiscalDateEnding") or statement.get("date")
    return enriched


def advance_fiscal_quarter(row: dict[str, Any]) -> tuple[int, str | None] | None:
    quarter = fiscal_quarter_number(row)
    year = fiscal_year_value(row)
    if not quarter:
        return None
    next_quarter = 1 if quarter == 4 else quarter + 1
    next_year = year
    if quarter == 4 and year:
        year_number = safe_float(year)
        next_year = str(int(year_number) + 1) if year_number else year
    return next_quarter, next_year


def apply_fiscal_quarter(row: dict[str, Any], quarter: int, year: str | None) -> dict[str, Any]:
    enriched = dict(row)
    enriched["quarter"] = quarter
    enriched["period"] = f"Q{quarter}"
    if year:
        enriched["calendarYear"] = year
        enriched["fiscalYear"] = year
    return enriched


def unique_earnings_reports(reports: list[dict[str, Any]], limit: int | None = None) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for report in reports:
        marker = report.get("fiscal_quarter") or report.get("date") or str(len(unique))
        if marker in seen:
            continue
        seen.add(marker)
        unique.append(report)
        if limit and len(unique) >= limit:
            break
    return unique


def build_earnings_reports(context: dict[str, Any], today: dt.date) -> dict[str, Any]:
    quarter_rows = context.get("income_quarter") or []
    dated_rows = [
        (parsed_date, row)
        for row in (context.get("earnings_calendar") or [])
        if (parsed_date := parse_fmp_date(row.get("date") or row.get("fiscalDateEnding"))) is not None
    ]
    dated_rows.sort(key=lambda item: item[0], reverse=True)
    actual_quarters = unique_earnings_reports(
        [
            normalize_earnings_report(enrich_earnings_row_with_statement_period(row, quarter_rows), "quarter")
            for report_date, row in dated_rows
            if report_date <= today
        ],
        limit=5,
    )
    if len(actual_quarters) < 5:
        supplemental = [
            normalize_earnings_report(row, "quarter")
            for row in sorted(
                quarter_rows,
                key=lambda item: str(item.get("date") or item.get("fiscalDateEnding") or ""),
                reverse=True,
            )
            if (parse_fmp_date(row.get("date") or row.get("fiscalDateEnding")) or today) <= today
        ]
        actual_quarters = unique_earnings_reports([*actual_quarters, *supplemental], limit=5)
    next_earnings_date = next(
        (report_date.isoformat() for report_date, _ in sorted(dated_rows, key=lambda item: item[0]) if report_date > today),
        None,
    )
    upcoming = None
    future_rows = [(report_date, row) for report_date, row in sorted(dated_rows, key=lambda item: item[0]) if report_date > today]
    if future_rows:
        _, future_row = future_rows[0]
        enriched_future = dict(future_row)
        if not fiscal_quarter_label(enriched_future) and actual_quarters:
            next_period = advance_fiscal_quarter(actual_quarters[0])
            if next_period:
                enriched_future = apply_fiscal_quarter(enriched_future, *next_period)
        upcoming = normalize_earnings_report(enriched_future, "upcoming")
    return {
        "next_earnings_date": next_earnings_date,
        "reports": [*([upcoming] if upcoming else []), *actual_quarters],
    }


def compact_rows(rows: list[dict[str, Any]], keys: list[str], limit: int = 8) -> list[dict[str, Any]]:
    compacted = []
    for row in rows[:limit]:
        item = {}
        for key in keys:
            value = row.get(key)
            if value in (None, "", []):
                continue
            if isinstance(value, str) and len(value) > 1800:
                value = f"{value[:1800]}..."
            item[key] = value
        compacted.append(item)
    return compacted


def compact_json_text(value: Any, max_chars: int = 18_000) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= max_chars else f"{text[:max_chars]}..."


def source_entry(source_key: str, source_type: str, title: str, **extra: Any) -> dict[str, Any]:
    return {
        "source_key": source_key,
        "source_type": source_type,
        "title": title,
        "url": extra.get("url"),
        "publisher": extra.get("publisher") or "Financial Modeling Prep",
        "published_at": extra.get("published_at"),
        "metadata": extra.get("metadata") or {},
        "excerpt": extra.get("excerpt"),
    }


def filing_url(item: dict[str, Any]) -> str | None:
    return item.get("finalLink") or item.get("link") or item.get("url") or item.get("filingUrl")


def transcript_title(symbol: str, item: dict[str, Any], fallback_index: int) -> str:
    quarter_label = fiscal_quarter_label(item)
    date_value = item.get("date") or item.get("publishedDate")
    if quarter_label:
        return f"{symbol} {quarter_label} earnings call transcript"
    if date_value:
        return f"{symbol} earnings call transcript {str(date_value)[:10]}"
    return f"{symbol} earnings call transcript {fallback_index}"


def fetch_transcripts(client: FmpClient, symbol: str, earnings_calendar: list[dict[str, Any]]) -> list[dict[str, Any]]:
    transcripts: list[dict[str, Any]] = []
    for endpoint, params in (
        ("earning-call-transcript-latest", {"symbol": symbol, "limit": 6}),
        ("earning-call-transcript", {"symbol": symbol, "limit": 6}),
        (f"earning-call-transcript/{symbol}", {"limit": 6}),
    ):
        transcripts.extend(fmp_items(try_fmp_get(client, endpoint, params)))
    quarter_candidates: list[tuple[int, int]] = []
    for item in earnings_calendar[:8]:
        year = safe_float(fiscal_year_value(item))
        quarter = safe_float(fiscal_quarter_number(item))
        if year and quarter:
            quarter_candidates.append((int(year), int(quarter)))
    current_year = dt.date.today().year
    for year in range(current_year, current_year - 3, -1):
        for quarter in range(4, 0, -1):
            quarter_candidates.append((year, quarter))
    for candidate in unique_rows([{"year": year, "quarter": quarter} for year, quarter in quarter_candidates], ("year", "quarter"))[:10]:
        transcripts.extend(
            fmp_items(
                try_fmp_get(
                    client,
                    "earning-call-transcript",
                    {"symbol": symbol, "year": candidate["year"], "quarter": candidate["quarter"]},
                )
            )
        )
    cleaned = []
    for item in transcripts:
        content = str(item.get("content") or item.get("transcript") or item.get("text") or "").strip()
        if not content:
            continue
        normalized = dict(item)
        normalized["content"] = content
        cleaned.append(normalized)
    return unique_rows(cleaned, ("date", "quarter", "year", "content"))[:6]


def fetch_sec_filings(client: FmpClient, symbol: str) -> list[dict[str, Any]]:
    filings: list[dict[str, Any]] = []
    for endpoint, params in (
        ("sec-filings-search/form-type", {"symbol": symbol, "formType": "10-K", "page": 0, "limit": 10}),
        ("sec-filings-search/form-type", {"symbol": symbol, "formType": "10-Q", "page": 0, "limit": 10}),
        ("sec-filings-search", {"symbol": symbol, "type": "10-K", "page": 0, "limit": 10}),
        ("sec-filings-search/symbol", {"symbol": symbol, "page": 0, "limit": 30}),
        ("sec-filings-search", {"symbol": symbol, "page": 0, "limit": 30}),
        ("sec-filings-company-search", {"symbol": symbol, "page": 0, "limit": 30}),
        ("sec_filings", {"symbol": symbol, "limit": 30}),
        ("sec-filings", {"symbol": symbol, "limit": 30}),
    ):
        filings.extend(fmp_items(try_fmp_get(client, endpoint, params)))
    return unique_rows(filings, ("fillingDate", "acceptedDate", "type", "formType", "finalLink", "link"))[:30]


def fetch_first_non_empty(client: FmpClient, candidates: list[tuple[str, dict[str, Any]]]) -> list[dict[str, Any]]:
    for endpoint, params in candidates:
        rows = fmp_items(try_fmp_get(client, endpoint, params))
        if rows:
            return rows
    return []


def filter_rows_since(rows: list[dict[str, Any]], cutoff: dt.date, *date_keys: str) -> list[dict[str, Any]]:
    recent = []
    for row in rows:
        raw_date = next((row.get(key) for key in date_keys if row.get(key)), None)
        if not raw_date:
            continue
        try:
            parsed = dt.date.fromisoformat(str(raw_date)[:10])
        except ValueError:
            continue
        if parsed >= cutoff:
            recent.append(row)
    return recent


def fetch_annual_report_json(client: FmpClient, symbol: str) -> list[dict[str, Any]]:
    date_rows = fetch_first_non_empty(
        client,
        [
            ("financial-reports-dates", {"symbol": symbol}),
            ("financial-reports-dates", {"symbol": symbol, "period": "FY"}),
        ],
    )
    years = []
    for row in date_rows:
        year = safe_float(str(row.get("date") or row.get("year") or row.get("fillingDate") or "")[:4])
        period = row.get("period") or row.get("form") or "FY"
        if year:
            years.append({"year": int(year), "period": "FY" if str(period).upper() in {"FY", "10-K", "ANNUAL"} else period})
    if not years:
        current_year = dt.date.today().year
        years = [{"year": year, "period": "FY"} for year in range(current_year - 1, current_year - 4, -1)]
    reports = []
    for item in unique_rows(years, ("year", "period"))[:3]:
        for endpoint, params in (
            ("financial-reports-json", {"symbol": symbol, "year": item["year"], "period": item["period"]}),
            ("financial-reports-json", {"symbol": symbol, "year": item["year"], "period": "FY"}),
        ):
            rows = fmp_items(try_fmp_get(client, endpoint, params))
            if rows:
                report = dict(rows[0])
                report.setdefault("year", item["year"])
                report.setdefault("period", item["period"])
                reports.append(report)
                break
    return reports


def fetch_deep_research_context(client: FmpClient, symbol: str, progress: Callable[[str, int], None] | None = None) -> dict[str, Any]:
    today = dt.date.today()
    one_year_ago = today - dt.timedelta(days=365)
    six_months_ago = today - dt.timedelta(days=183)
    five_years_ago = today - dt.timedelta(days=365 * 5 + 10)
    progress = progress or (lambda _step, _pct: None)

    progress("Fetching company profile and market data", 10)
    profile = first_item(try_fmp_get(client, "profile", {"symbol": symbol}))
    quote = first_item(try_fmp_get(client, "quote", {"symbol": symbol}))
    market_cap = first_item(try_fmp_get(client, "market-capitalization", {"symbol": symbol}))
    enterprise_values = fmp_items(try_fmp_get(client, "enterprise-values", {"symbol": symbol, "period": "annual", "limit": 10}))
    fmp_dcf = fetch_first_non_empty(
        client,
        [
            ("custom-discounted-cash-flow", {"symbol": symbol}),
            ("discounted-cash-flow", {"symbol": symbol}),
            ("dcf", {"symbol": symbol}),
            ("advanced-dcf", {"symbol": symbol}),
        ],
    )

    progress("Fetching financial statements", 22)
    income_annual = fmp_items(try_fmp_get(client, "income-statement", {"symbol": symbol, "period": "annual", "limit": 10}))
    income_quarter = fmp_items(try_fmp_get(client, "income-statement", {"symbol": symbol, "period": "quarter", "limit": 12}))
    balance_annual = fmp_items(try_fmp_get(client, "balance-sheet-statement", {"symbol": symbol, "period": "annual", "limit": 10}))
    balance_quarter = fmp_items(try_fmp_get(client, "balance-sheet-statement", {"symbol": symbol, "period": "quarter", "limit": 12}))
    cashflow_annual = fmp_items(try_fmp_get(client, "cash-flow-statement", {"symbol": symbol, "period": "annual", "limit": 10}))
    cashflow_quarter = fmp_items(try_fmp_get(client, "cash-flow-statement", {"symbol": symbol, "period": "quarter", "limit": 12}))
    income_as_reported = fetch_first_non_empty(
        client,
        [
            ("income-statement-as-reported", {"symbol": symbol, "period": "annual", "limit": 5}),
            ("financial-statement-full-as-reported", {"symbol": symbol, "period": "annual", "limit": 5}),
        ],
    )

    progress("Fetching ratios, metrics, and estimates", 34)
    metrics_ttm = first_item(try_fmp_get(client, "key-metrics-ttm", {"symbol": symbol}))
    ratios_annual_latest = fmp_items(try_fmp_get(client, "ratios", {"symbol": symbol, "limit": 20}))
    ratios_annual_period = fmp_items(try_fmp_get(client, "ratios", {"symbol": symbol, "period": "annual", "limit": 20}))
    ratios_annual = unique_rows(ratios_annual_latest + ratios_annual_period, ("date", "calendarYear", "period"))
    ratios_ttm = first_item(try_fmp_get(client, "ratios-ttm", {"symbol": symbol})) or first_item(ratios_annual)
    metrics_annual = fmp_items(try_fmp_get(client, "key-metrics", {"symbol": symbol, "period": "annual", "limit": 20}))
    metrics_quarter = fmp_items(try_fmp_get(client, "key-metrics", {"symbol": symbol, "period": "quarter", "limit": 32}))
    ratios_quarter = fmp_items(try_fmp_get(client, "ratios", {"symbol": symbol, "period": "quarter", "limit": 32}))
    growth_annual = fmp_items(try_fmp_get(client, "financial-growth", {"symbol": symbol, "period": "annual", "limit": 10}))
    growth_quarter = fmp_items(try_fmp_get(client, "financial-growth", {"symbol": symbol, "period": "quarter", "limit": 16}))
    analyst_estimates = fmp_items(try_fmp_get(client, "analyst-estimates", {"symbol": symbol, "period": "annual", "limit": 6}))
    analyst_recommendations = fetch_first_non_empty(
        client,
        [
            ("price-target-summary", {"symbol": symbol}),
            ("price-target-consensus", {"symbol": symbol}),
            ("price-target-news", {"symbol": symbol, "limit": 20}),
            ("analyst-stock-recommendations", {"symbol": symbol, "limit": 12}),
            ("upgrades-downgrades", {"symbol": symbol, "limit": 20}),
            ("upgrades-downgrades-consensus", {"symbol": symbol}),
            ("stock-grades", {"symbol": symbol, "limit": 20}),
            ("analyst-estimates", {"symbol": symbol, "limit": 12}),
            ("analyst-ratings", {"symbol": symbol, "limit": 12}),
        ],
    )
    stock_grades = rows_for_symbol_or_without_symbol(
        fmp_items(try_fmp_get(client, "grades", {"symbol": symbol, "limit": 20})),
        symbol,
    )[:10]

    progress("Fetching filings, transcripts, and news", 48)
    earnings_calendar = fmp_items(try_fmp_get(client, "earnings", {"symbol": symbol, "limit": 8}))
    transcripts = fetch_transcripts(client, symbol, earnings_calendar)
    sec_filings = filter_rows_since(fetch_sec_filings(client, symbol), one_year_ago, "fillingDate", "acceptedDate", "date", "periodOfReport")
    annual_reports = fetch_annual_report_json(client, symbol)
    insider_trading = filter_rows_for_symbol(
        fetch_first_non_empty(
            client,
            [
                ("insider-trading", {"symbol": symbol, "limit": 100}),
            ],
        ),
        symbol,
    )
    if not insider_trading:
        insider_trading = filter_rows_for_symbol(
            fetch_first_non_empty(
                client,
                [
                    ("insider-trading/latest", {"symbol": symbol, "limit": 100}),
                ],
            ),
            symbol,
        )
    news = fmp_items(try_fmp_get(client, "news/stock", {"symbols": symbol, "from": six_months_ago.isoformat(), "to": today.isoformat(), "limit": 80}))

    progress("Fetching price history", 58)
    price_history = normalize_price_history(
        try_fmp_get(client, "historical-price-eod/full", {"symbol": symbol, "from": five_years_ago.isoformat(), "to": today.isoformat()})
    )
    if not price_history:
        price_history = normalize_price_history(
            try_fmp_get(client, f"historical-price-full/{symbol}", {"from": five_years_ago.isoformat(), "to": today.isoformat()})
        )

    sources = []
    for key, title, statement_type, period, rows in (
        ("income_annual", f"{symbol} income statement, annual", "income", "annual", income_annual),
        ("income_quarter", f"{symbol} income statement, quarterly", "income", "quarter", income_quarter),
        ("balance_annual", f"{symbol} balance sheet, annual", "balance", "annual", balance_annual),
        ("balance_quarter", f"{symbol} balance sheet, quarterly", "balance", "quarter", balance_quarter),
        ("cashflow_annual", f"{symbol} cash flow statement, annual", "cashflow", "annual", cashflow_annual),
        ("cashflow_quarter", f"{symbol} cash flow statement, quarterly", "cashflow", "quarter", cashflow_quarter),
    ):
        if rows:
            sources.append(
                source_entry(
                    key,
                    "financial_statement",
                    title,
                    metadata={"statement_type": statement_type, "period": period, "rows": rows[:12]},
                )
            )
    for index, item in enumerate(sec_filings[:12], start=1):
        title = item.get("type") or item.get("formType") or item.get("title") or "SEC filing"
        sources.append(
            source_entry(
                f"sec_filing_{index}",
                "sec_filing",
                f"{symbol} {title}",
                url=filing_url(item),
                published_at=item.get("fillingDate") or item.get("acceptedDate") or item.get("date"),
                metadata={key: item.get(key) for key in ("type", "formType", "periodOfReport", "fillingDate") if item.get(key)},
            )
        )
    for index, item in enumerate(annual_reports[:3], start=1):
        title = f"{symbol} annual report JSON {item.get('year') or index}"
        sources.append(
            source_entry(
                f"annual_report_{index}",
                "annual_report_json",
                title,
                published_at=item.get("date") or item.get("fillingDate"),
                metadata={"report": item},
                excerpt=str(item)[:900],
            )
        )
    for index, item in enumerate(transcripts[:6], start=1):
        title = transcript_title(symbol, item, index)
        sources.append(
            source_entry(
                f"transcript_{index}",
                "earnings_transcript",
                title,
                published_at=item.get("date"),
                metadata={
                    "date": item.get("date"),
                    "quarter": item.get("quarter"),
                    "year": item.get("year"),
                    "content": item.get("content"),
                },
                excerpt=str(item.get("content") or "")[:900],
            )
        )
    for index, item in enumerate(news[:20], start=1):
        sources.append(
            source_entry(
                f"news_{index}",
                "news",
                item.get("title") or item.get("headline") or f"{symbol} news {index}",
                url=item.get("url") or item.get("link"),
                publisher=item.get("site") or item.get("publisher") or item.get("source"),
                published_at=item.get("publishedDate") or item.get("date"),
                excerpt=str(item.get("text") or item.get("summary") or item.get("content") or "")[:700],
            )
        )

    return {
        "profile": profile,
        "quote": quote,
        "market_cap": market_cap,
        "enterprise_values": enterprise_values,
        "fmp_dcf": fmp_dcf,
        "income_annual": income_annual,
        "income_quarter": income_quarter,
        "balance_annual": balance_annual,
        "balance_quarter": balance_quarter,
        "cashflow_annual": cashflow_annual,
        "cashflow_quarter": cashflow_quarter,
        "income_as_reported": income_as_reported,
        "metrics_ttm": metrics_ttm,
        "ratios_ttm": ratios_ttm,
        "metrics_annual": metrics_annual,
        "ratios_annual": ratios_annual,
        "metrics_quarter": metrics_quarter,
        "ratios_quarter": ratios_quarter,
        "growth_annual": growth_annual,
        "growth_quarter": growth_quarter,
        "analyst_estimates": analyst_estimates,
        "analyst_recommendations": analyst_recommendations,
        "stock_grades": stock_grades,
        "earnings_calendar": earnings_calendar,
        "transcripts": transcripts,
        "sec_filings": sec_filings,
        "annual_reports": annual_reports,
        "insider_trading": insider_trading,
        "news": news,
        "price_history": price_history[-1300:],
        "sources": sources,
    }


def chart_series(
    rows: list[dict[str, Any]],
    field: str | list[str],
    label: str,
    scale: float = 1.0,
    *,
    period: str = "annual",
    chart_type: str = "bar",
    value_suffix: str = "",
) -> dict[str, Any] | None:
    points = []
    for row in reversed(rows):
        value = safe_float(get_any(row, *field) if isinstance(field, list) else row.get(field))
        date_value = row.get("date") or row.get("calendarYear") or row.get("fiscalDateEnding")
        if value is None or not date_value:
            continue
        point = {"date": str(date_value)[:10], "value": value / scale}
        if period == "quarter":
            label = fiscal_quarter_label(row)
            if label:
                point["label"] = label
        points.append(point)
    if len(points) < 2:
        return None
    values = [point["value"] for point in points]
    return {
        "artifact_type": "chart",
        "title": label,
        "data": {
            "series": points,
            "field": field[0] if isinstance(field, list) else field,
            "period": period,
            "chart_type": chart_type,
            "value_suffix": value_suffix,
            "min": min(values),
            "max": max(values),
            "average": sum(values) / len(values),
        },
    }


def add_current_point(artifact: dict[str, Any] | None, value: Any, date_value: Any | None = None) -> dict[str, Any] | None:
    current = safe_float(value)
    if not artifact or current is None:
        return artifact
    data = artifact.get("data") or {}
    series = list(data.get("series") or [])
    if not series:
        return artifact
    latest_date = str(date_value or dt.date.today().isoformat())[:10]
    if series[-1].get("date") == latest_date and series[-1].get("label") == "Current":
        return artifact
    series.append({"date": latest_date, "value": current, "label": "Current"})
    values = [point["value"] for point in series if safe_float(point.get("value")) is not None]
    if not values:
        return artifact
    next_artifact = dict(artifact)
    next_data = dict(data)
    next_data["series"] = series
    next_data["min"] = min(values)
    next_data["max"] = max(values)
    next_data["average"] = sum(values) / len(values)
    next_artifact["data"] = next_data
    return next_artifact


def build_artifacts(context: dict[str, Any]) -> list[dict[str, Any]]:
    income = context["income_annual"]
    income_q = context["income_quarter"]
    cashflow = context["cashflow_annual"]
    metrics = context["metrics_annual"]
    metrics_q = context["metrics_quarter"]
    ratios = context["ratios_annual"]
    ratios_q = context["ratios_quarter"]
    growth = context["growth_annual"]
    growth_q = context["growth_quarter"]
    metric_snapshot = build_metric_snapshot(context)
    current_date = (context.get("quote") or {}).get("date") or dt.date.today().isoformat()
    artifacts = [
        chart_series(income, "revenue", "Revenue", 1_000_000, period="annual"),
        chart_series(income_q, "revenue", "Revenue", 1_000_000, period="quarter"),
        chart_series(growth, "revenueGrowth", "Revenue growth", 0.01, period="annual", value_suffix="%"),
        chart_series(growth_q, "revenueGrowth", "Revenue growth", 0.01, period="quarter", value_suffix="%"),
        chart_series(income, "ebitda", "EBITDA", 1_000_000, period="annual"),
        chart_series(income_q, "ebitda", "EBITDA", 1_000_000, period="quarter"),
        chart_series(growth, "ebitdagrowth", "EBITDA growth", 0.01, period="annual", value_suffix="%"),
        chart_series(growth_q, "ebitdagrowth", "EBITDA growth", 0.01, period="quarter", value_suffix="%"),
        chart_series(income, "netIncome", "Net income", 1_000_000, period="annual"),
        chart_series(income_q, "netIncome", "Net income", 1_000_000, period="quarter"),
        chart_series(income, "eps", "EPS", period="annual"),
        chart_series(income_q, "eps", "EPS", period="quarter"),
        chart_series(cashflow, "freeCashFlow", "Free cash flow", 1_000_000, period="annual"),
        chart_series(context["cashflow_quarter"], "freeCashFlow", "Free cash flow", 1_000_000, period="quarter"),
        chart_series(ratios, "grossProfitMargin", "Gross margin", 0.01, period="annual", value_suffix="%"),
        chart_series(ratios_q, "grossProfitMargin", "Gross margin", 0.01, period="quarter", value_suffix="%"),
        chart_series(ratios, "operatingProfitMargin", "Operating margin", 0.01, period="annual", value_suffix="%"),
        chart_series(ratios_q, "operatingProfitMargin", "Operating margin", 0.01, period="quarter", value_suffix="%"),
        chart_series(ratios, "netProfitMargin", "Net margin", 0.01, period="annual", value_suffix="%"),
        chart_series(ratios_q, "netProfitMargin", "Net margin", 0.01, period="quarter", value_suffix="%"),
        add_current_point(
            chart_series(ratios, ["priceToEarningsRatio", "priceToEarningsRatioTTM", "priceEarningsRatio", "priceEarningsRatioTTM", "peRatio", "peRatioTTM"], "P/E ratio", period="annual", chart_type="line")
            or chart_series(metrics, ["peRatio", "peRatioTTM", "priceToEarningsRatio", "priceEarningsRatio"], "P/E ratio", period="annual", chart_type="line"),
            metric_snapshot.get("pe"),
            current_date,
        ),
        chart_series(ratios_q, ["priceToEarningsRatio", "priceToEarningsRatioTTM", "priceEarningsRatio", "priceEarningsRatioTTM", "peRatio", "peRatioTTM"], "P/E ratio", period="quarter", chart_type="line")
        or chart_series(metrics_q, ["peRatio", "peRatioTTM", "priceToEarningsRatio", "priceEarningsRatio"], "P/E ratio", period="quarter", chart_type="line"),
        add_current_point(
            chart_series(metrics, ["enterpriseValueOverEBITDA", "enterpriseValueOverEBITDATTM", "evToEBITDA"], "EV/EBITDA", period="annual", chart_type="line"),
            metric_snapshot.get("ev_to_ebitda"),
            current_date,
        ),
        chart_series(metrics_q, ["enterpriseValueOverEBITDA", "enterpriseValueOverEBITDATTM", "evToEBITDA"], "EV/EBITDA", period="quarter", chart_type="line"),
        add_current_point(
            chart_series(metrics, ["freeCashFlowYield", "freeCashFlowYieldTTM"], "FCF yield", 0.01, period="annual", chart_type="line", value_suffix="%"),
            safe_float(metric_snapshot.get("fcf_yield_pct")),
            current_date,
        ),
        chart_series(metrics_q, ["freeCashFlowYield", "freeCashFlowYieldTTM"], "FCF yield", 0.01, period="quarter", chart_type="line", value_suffix="%"),
        chart_series(metrics, ["pbRatio", "pbRatioTTM", "priceToBookRatio"], "P/B ratio", period="annual", chart_type="line"),
        chart_series(metrics_q, ["pbRatio", "pbRatioTTM", "priceToBookRatio"], "P/B ratio", period="quarter", chart_type="line"),
    ]
    return [artifact for artifact in artifacts if artifact]


def find_artifact_series(artifacts: list[dict[str, Any]], title: str, period: str = "annual") -> list[dict[str, Any]]:
    for artifact in artifacts:
        if artifact.get("title") != title:
            continue
        data = artifact.get("data") or {}
        if data.get("period") == period:
            return data.get("series") or []
    return []


def find_artifact_period(artifacts: list[dict[str, Any]], title: str, preferred_period: str = "annual") -> str | None:
    for period in (preferred_period, "quarter"):
        if find_artifact_series(artifacts, title, period):
            return period
    return None


def latest_annual_value(rows: list[dict[str, Any]], field: str) -> float | None:
    return first_number(*[row.get(field) for row in rows[:2]])


def estimate_revenue_growth(context: dict[str, Any]) -> dict[str, Any]:
    estimates = context.get("analyst_estimates") or []
    income = context.get("income_annual") or []
    latest_revenue = latest_annual_value(income, "revenue")
    historical = None
    if len(income) >= 4:
        historical = cagr(income[0].get("revenue"), income[3].get("revenue"), 3)
    if latest_revenue:
        candidates = []
        latest_year = safe_float(str(income[0].get("date") or income[0].get("calendarYear") or "")[:4]) if income else None
        for row in estimates[:6]:
            estimate_revenue = first_number(row.get("estimatedRevenueAvg"), row.get("revenueAvg"), row.get("estimatedRevenueLow"), row.get("estimatedRevenueHigh"))
            estimate_year = safe_float(str(row.get("date") or row.get("calendarYear") or row.get("year") or "")[:4])
            years = max(1, int(estimate_year - latest_year)) if estimate_year and latest_year and estimate_year > latest_year else 1
            growth = cagr(estimate_revenue, latest_revenue, years)
            if growth is not None:
                candidates.append({"growth": growth, "years": years, "date": row.get("date") or row.get("calendarYear") or row.get("year")})
        if candidates:
            nearest = sorted(candidates, key=lambda item: item["years"])[0]
            max_growth = 25.0
            if historical is not None and historical > 0:
                max_growth = min(25.0, max(8.0, historical + 6.0))
            return {
                "value": clamp(nearest["growth"], -15.0, max_growth),
                "source": "analyst_estimate",
                "source_label": f"Nearest analyst revenue estimate ({nearest['date'] or 'next fiscal period'})",
                "raw_value": nearest["growth"],
                "historical_3y": historical,
            }
    if historical is not None:
        return {
            "value": clamp(historical, -12.0, 20.0),
            "source": "historical_cagr",
            "source_label": "Three-year historical revenue CAGR",
            "raw_value": historical,
            "historical_3y": historical,
        }
    return {"value": 4.0, "source": "fallback", "source_label": "Fallback assumption", "raw_value": 4.0, "historical_3y": None}


def implied_revenue_growth_for_price(
    *,
    current_price: float | None,
    latest_revenue: float | None,
    shares: float | None,
    net_debt: float | None,
    assumptions: dict[str, Any],
) -> float | None:
    if current_price in (None, 0) or latest_revenue is None or shares in (None, 0):
        return None
    target_equity_value = current_price * shares
    low = -30.0
    high = 50.0
    for _ in range(48):
        mid = (low + high) / 2
        result = compute_dcf(
            latest_revenue=latest_revenue,
            shares=shares,
            net_debt=net_debt,
            current_price=current_price,
            revenue_growth_pct=mid,
            fcf_margin_pct=float(assumptions["fcf_margin_pct"]),
            operating_margin_pct=float(assumptions.get("operating_margin_pct") or 0),
            tax_rate_pct=float(assumptions.get("tax_rate_pct") or 21),
            wacc_pct=float(assumptions["wacc_pct"]),
            terminal_growth_pct=float(assumptions["terminal_growth_pct"]),
            projection_years=int(assumptions.get("projection_years") or 5),
        )
        equity_value = result.get("equity_value")
        if equity_value is None:
            return None
        if equity_value < target_equity_value:
            low = mid
        else:
            high = mid
    return (low + high) / 2


def build_dcf(context: dict[str, Any]) -> dict[str, Any]:
    income = context.get("income_annual") or []
    cashflow = context.get("cashflow_annual") or []
    quote = context.get("quote") or {}
    fmp_dcf_rows = context.get("fmp_dcf") or []
    fmp_dcf_row = next(
        (
            row
            for row in fmp_dcf_rows
            if first_number(
                deep_get_any(
                    row,
                    "dcf",
                    "DCF",
                    "finalDCF",
                    "dcfPerShare",
                    "DCF Per Share",
                    "fairValue",
                    "intrinsicValue",
                    "intrinsicValuePerShare",
                    "equityValuePerShare",
                    "presentShareValue",
                )
            )
            is not None
        ),
        first_item(fmp_dcf_rows),
    )
    metrics_ttm = context.get("metrics_ttm") or {}
    ratios_ttm = context.get("ratios_ttm") or {}
    latest_revenue = latest_annual_value(income, "revenue") or first_number((context.get("profile") or {}).get("revenue"))
    latest_fcf = latest_annual_value(cashflow, "freeCashFlow")
    current_price = first_number(quote.get("price"), quote.get("previousClose"))
    shares = first_number(
        quote.get("sharesOutstanding"),
        metrics_ttm.get("weightedAverageShsOutTTM"),
        latest_annual_value(income, "weightedAverageShsOutDil"),
    )
    net_debt = first_number(metrics_ttm.get("netDebtTTM"), metrics_ttm.get("netDebt"))
    if net_debt is None:
        latest_balance = first_item(context.get("balance_annual") or [])
        net_debt = (first_number(latest_balance.get("totalDebt")) or 0) - (first_number(latest_balance.get("cashAndCashEquivalents")) or 0)

    revenue_growth = estimate_revenue_growth(context)
    fcf_margin = divide_or_none(latest_fcf, latest_revenue)
    if fcf_margin is None:
        fcf_margin = divide_or_none(metrics_ttm.get("freeCashFlowPerShareTTM"), metrics_ttm.get("revenuePerShareTTM"))
    if fcf_margin is None:
        fcf_margin = 0.08
    fcf_margin_pct = clamp(fcf_margin * 100, -10, 35)
    operating_margin_pct = ratio_to_percent(ratios_ttm.get("operatingProfitMarginTTM") or ratios_ttm.get("operatingProfitMargin")) or fcf_margin_pct
    assumptions = {
        "revenue_growth_pct": round(float(revenue_growth["value"]), 2),
        "fcf_margin_pct": round(fcf_margin_pct, 2),
        "operating_margin_pct": round(operating_margin_pct, 2),
        "tax_rate_pct": 21.0,
        "wacc_pct": 9.0,
        "terminal_growth_pct": 2.5,
        "projection_years": 5,
    }
    analyst_growth_pct = float(revenue_growth["value"]) if revenue_growth["source"] == "analyst_estimate" else None
    implied_growth_pct = implied_revenue_growth_for_price(
        current_price=current_price,
        latest_revenue=latest_revenue,
        shares=shares,
        net_debt=net_debt,
        assumptions=assumptions,
    )
    projections = compute_dcf(
        latest_revenue=latest_revenue,
        shares=shares,
        net_debt=net_debt,
        current_price=current_price,
        **assumptions,
    )
    provider_dcf_value = first_number(
        deep_get_any(
            fmp_dcf_row,
            "dcf",
            "DCF",
            "finalDCF",
            "dcfPerShare",
            "DCF Per Share",
            "fairValue",
            "value",
            "intrinsicValue",
            "intrinsicValuePerShare",
            "equityValuePerShare",
            "presentShareValue",
        )
    )
    provider_stock_price = first_number(deep_get_any(fmp_dcf_row, "stockPrice", "Stock Price", "price", "marketPrice"))
    provider_reference_price = current_price or provider_stock_price
    return {
        "base": {
            "latest_revenue": latest_revenue,
            "latest_free_cash_flow": latest_fcf,
            "shares_outstanding": shares,
            "net_debt": net_debt,
            "current_price": current_price,
        },
        "provider_dcf": {
            "date": deep_get_any(fmp_dcf_row, "date"),
            "dcf": provider_dcf_value,
            "stock_price": provider_stock_price,
            "upside_downside_pct": ((provider_dcf_value / provider_reference_price) - 1) * 100
            if provider_dcf_value is not None and provider_reference_price not in (None, 0)
            else None,
        }
        if fmp_dcf_row
        else None,
        "assumptions": assumptions,
        "assumption_sources": {
            "revenue_growth_pct": revenue_growth,
            "analyst_revenue_growth_pct": analyst_growth_pct,
            "historical_revenue_growth_3y_pct": revenue_growth.get("historical_3y"),
            "market_implied_revenue_growth_pct": implied_growth_pct,
        },
        **projections,
        "methodology": "Five-year revenue-to-FCF DCF. Initial growth uses analyst estimates when available, otherwise recent historical revenue CAGR.",
    }


def compute_dcf(
    *,
    latest_revenue: float | None,
    shares: float | None,
    net_debt: float | None,
    current_price: float | None,
    revenue_growth_pct: float,
    fcf_margin_pct: float,
    operating_margin_pct: float,
    tax_rate_pct: float,
    wacc_pct: float,
    terminal_growth_pct: float,
    projection_years: int,
) -> dict[str, Any]:
    if latest_revenue is None or shares in (None, 0):
        return {"projection": [], "intrinsic_value_per_share": None, "upside_downside_pct": None}
    growth = revenue_growth_pct / 100
    fcf_margin = fcf_margin_pct / 100
    discount = max(wacc_pct / 100, 0.001)
    terminal_growth = min(terminal_growth_pct / 100, discount - 0.001)
    projection = []
    present_value_sum = 0.0
    revenue = latest_revenue
    for year in range(1, int(projection_years) + 1):
        revenue *= 1 + growth
        fcf = revenue * fcf_margin
        present_value = fcf / ((1 + discount) ** year)
        present_value_sum += present_value
        projection.append({"year": year, "revenue": revenue, "free_cash_flow": fcf, "present_value": present_value})
    terminal_fcf = projection[-1]["free_cash_flow"] * (1 + terminal_growth) if projection else 0
    terminal_value = terminal_fcf / max(discount - terminal_growth, 0.001)
    terminal_present_value = terminal_value / ((1 + discount) ** int(projection_years))
    enterprise_value = present_value_sum + terminal_present_value
    equity_value = enterprise_value - (net_debt or 0)
    intrinsic = equity_value / shares if shares else None
    upside = ((intrinsic / current_price) - 1) * 100 if intrinsic is not None and current_price not in (None, 0) else None
    return {
        "projection": projection,
        "terminal_value": terminal_value,
        "enterprise_value": enterprise_value,
        "equity_value": equity_value,
        "intrinsic_value_per_share": intrinsic,
        "upside_downside_pct": upside,
    }


def build_model_context(symbol: str, company_name: str, relationship: str, context: dict[str, Any], artifacts: list[dict[str, Any]], dcf: dict[str, Any]) -> dict[str, Any]:
    return {
        "company": {"symbol": symbol, "company_name": company_name, "relationship": relationship},
        "profile": {
            key: (context.get("profile") or {}).get(key)
            for key in ("companyName", "description", "sector", "industry", "ceo", "country", "website", "exchange", "mktCap")
        },
        "quote": {key: (context.get("quote") or {}).get(key) for key in ("price", "marketCap", "yearHigh", "yearLow", "eps", "pe", "sharesOutstanding")},
        "financials": {
            "income_annual": compact_rows(context["income_annual"], ["date", "revenue", "grossProfit", "operatingIncome", "netIncome", "eps", "ebitda"], 8),
            "cashflow_annual": compact_rows(context["cashflow_annual"], ["date", "operatingCashFlow", "capitalExpenditure", "freeCashFlow"], 8),
            "balance_annual": compact_rows(context["balance_annual"], ["date", "cashAndCashEquivalents", "totalDebt", "totalAssets", "totalLiabilities", "totalStockholdersEquity"], 8),
            "balance_quarter": compact_rows(context.get("balance_quarter") or [], ["date", "cashAndCashEquivalents", "totalDebt", "totalAssets", "totalLiabilities", "totalStockholdersEquity"], 8),
            "ratios_annual": compact_rows(context["ratios_annual"], ["date", "priceToEarningsRatio", "priceEarningsRatio", "priceToSalesRatio", "priceToBookRatio", "grossProfitMargin", "operatingProfitMargin", "netProfitMargin", "returnOnEquity", "returnOnInvestedCapital", "debtToEquityRatio", "debtEquityRatio"], 8),
            "ratios_quarter": compact_rows(context["ratios_quarter"], ["date", "priceToEarningsRatio", "priceEarningsRatio", "priceToSalesRatio", "priceToBookRatio", "grossProfitMargin", "operatingProfitMargin", "netProfitMargin", "returnOnEquity", "returnOnInvestedCapital", "debtToEquityRatio", "debtEquityRatio"], 8),
            "metrics_annual": compact_rows(context["metrics_annual"], ["date", "peRatio", "pbRatio", "evToSales", "enterpriseValueOverEBITDA", "freeCashFlowYield"], 8),
            "metrics_quarter": compact_rows(context["metrics_quarter"], ["date", "peRatio", "pbRatio", "evToSales", "enterpriseValueOverEBITDA", "freeCashFlowYield"], 8),
            "growth_annual": compact_rows(context["growth_annual"], ["date", "revenueGrowth", "epsgrowth", "freeCashFlowGrowth", "operatingIncomeGrowth"], 8),
            "growth_quarter": compact_rows(context["growth_quarter"], ["date", "revenueGrowth", "epsgrowth", "freeCashFlowGrowth", "operatingIncomeGrowth"], 8),
        },
        "analyst_estimates": compact_rows(context["analyst_estimates"], ["date", "estimatedRevenueAvg", "estimatedEpsAvg", "estimatedEbitdaAvg"], 6),
        "analyst_recommendations": compact_rows(context["analyst_recommendations"], ["date", "rating", "ratingRecommendation", "analystRatingsBuy", "analystRatingsHold", "analystRatingsSell"], 8),
        "stock_grades": compact_rows(
            context.get("stock_grades") or [],
            [
                "date",
                "gradingCompany",
                "previousGrade",
                "newGrade",
                "action",
                "symbol",
                "price",
                "priceTarget",
                "targetPrice",
                "newPriceTarget",
                "priceWhenPosted",
            ],
            10,
        ),
        "insider_trading": compact_rows(context["insider_trading"], ["transactionDate", "reportingName", "transactionType", "securitiesTransacted", "price", "typeOfOwner"], 20),
        "earnings": compact_rows(context["earnings_calendar"], ["date", "eps", "epsEstimated", "revenue", "revenueEstimated"], 8),
        "filings": compact_rows(context["sec_filings"], ["fillingDate", "acceptedDate", "type", "formType", "finalLink", "link"], 10),
        "annual_report_json": compact_rows(context["annual_reports"], ["year", "period", "date", "fillingDate", "acceptedDate", "content", "data"], 3),
        "annual_report_extracts": context.get("annual_report_extracts") or [],
        "news": compact_rows(context["news"], ["publishedDate", "title", "site", "url", "text"], 20),
        "transcript_samples": compact_rows(context["transcripts"], ["date", "quarter", "year", "content"], 6),
        "artifact_titles": [artifact["title"] for artifact in artifacts],
        "dcf": dcf,
        "openable_source_keys": [
            {
                "source_key": source["source_key"],
                "source_type": source["source_type"],
                "title": source["title"],
                "has_url": bool(source.get("url")),
                "has_modal_data": source["source_type"] in {"financial_statement", "earnings_transcript", "annual_report_json"},
            }
            for source in context["sources"][:45]
        ],
    }


def build_metric_snapshot(context: dict[str, Any]) -> dict[str, Any]:
    quote = context.get("quote") or {}
    metrics_ttm = context.get("metrics_ttm") or {}
    ratios_ttm = context.get("ratios_ttm") or {}
    ratios_rows = [ratios_ttm] + (context.get("ratios_annual") or [])
    metrics_latest = first_item(context.get("metrics_annual") or [])
    ratios_latest = first_item(context.get("ratios_annual") or [])
    income = context.get("income_annual") or []
    cashflow = context.get("cashflow_annual") or []
    growth = first_item(context.get("growth_annual") or [])
    latest_income = first_item(income)
    latest_cashflow = first_item(cashflow)
    latest_balance = first_item(context.get("balance_annual") or [])
    revenue = first_number(latest_income.get("revenue"))
    ebitda = first_number(get_any(latest_income, "ebitda", "EBITDA"))
    fcf = first_number(latest_cashflow.get("freeCashFlow"))
    market_cap = first_number(quote.get("marketCap"), (context.get("market_cap") or {}).get("marketCap"))
    shares = first_number(
        get_any(quote, "sharesOutstanding"),
        get_any(metrics_ttm, "weightedAverageShsOutTTM", "weightedAverageShsOut"),
        get_any(metrics_latest, "weightedAverageShsOut", "weightedAverageShsOutDil"),
        get_any(latest_income, "weightedAverageShsOutDil", "weightedAverageShsOut"),
    )
    total_debt = first_number(get_any(latest_balance, "totalDebt", "shortTermDebt", "longTermDebt"))
    cash = first_number(get_any(latest_balance, "cashAndCashEquivalents", "cashAndShortTermInvestments"))
    net_debt = first_number(get_any(metrics_ttm, "netDebtTTM", "netDebt"), (total_debt or 0) - (cash or 0) if total_debt is not None or cash is not None else None)
    return {
        "price": first_number(quote.get("price"), quote.get("previousClose")),
        "market_cap": market_cap,
        "pe": first_number(
            first_number_from_rows(ratios_rows, "priceToEarningsRatioTTM", "priceToEarningsRatio", "priceEarningsRatioTTM", "priceEarningsRatio", "peRatioTTM", "peRatio"),
            get_any(quote, "pe", "peRatio"),
            get_any(metrics_ttm, "peRatioTTM", "peRatio", "priceToEarningsRatioTTM", "priceToEarningsRatio"),
            get_any(metrics_latest, "peRatio", "priceToEarningsRatio", "priceEarningsRatio"),
        ),
        "ps": first_number(get_any(ratios_ttm, "priceToSalesRatioTTM", "priceToSalesRatio"), get_any(ratios_latest, "priceToSalesRatio"), get_any(metrics_ttm, "priceToSalesRatioTTM", "priceToSalesRatio"), get_any(metrics_latest, "priceToSalesRatio"), divide_or_none(market_cap, revenue)),
        "pb": first_number(get_any(ratios_ttm, "priceToBookRatioTTM", "priceToBookRatio", "pbRatioTTM", "pbRatio"), get_any(ratios_latest, "priceToBookRatio", "pbRatio"), get_any(metrics_ttm, "pbRatioTTM", "pbRatio"), get_any(metrics_latest, "pbRatio", "priceToBookRatio")),
        "ev_to_ebitda": first_number(get_any(metrics_ttm, "enterpriseValueOverEBITDATTM", "enterpriseValueOverEBITDA"), get_any(metrics_latest, "enterpriseValueOverEBITDA", "evToEBITDA")),
        "ev_to_sales": first_number(get_any(metrics_ttm, "evToSalesTTM", "enterpriseValueOverRevenueTTM"), get_any(metrics_latest, "evToSales", "enterpriseValueOverRevenue")),
        "fcf_yield_pct": ratio_to_percent(first_number(get_any(metrics_ttm, "freeCashFlowYieldTTM", "freeCashFlowYield"), get_any(metrics_latest, "freeCashFlowYield"), divide_or_none(fcf, market_cap))),
        "eps": first_number(quote.get("eps"), latest_income.get("eps"), latest_income.get("epsdiluted")),
        "revenue": revenue,
        "gross_profit": first_number(latest_income.get("grossProfit")),
        "ebitda": ebitda,
        "operating_income": first_number(latest_income.get("operatingIncome")),
        "net_income": first_number(latest_income.get("netIncome")),
        "free_cash_flow": fcf,
        "revenue_growth_pct": ratio_to_percent(get_any(growth, "revenueGrowth", "growthRevenue")),
        "eps_growth_pct": ratio_to_percent(get_any(growth, "epsgrowth", "epsGrowth")),
        "ebitda_growth_pct": ratio_to_percent(get_any(growth, "ebitdagrowth", "ebitdaGrowth")),
        "fcf_growth_pct": ratio_to_percent(get_any(growth, "freeCashFlowGrowth", "freecashflowGrowth")),
        "revenue_per_share": first_number(get_any(metrics_ttm, "revenuePerShareTTM", "revenuePerShare"), get_any(metrics_latest, "revenuePerShare"), divide_or_none(revenue, shares)),
        "fcf_per_share": first_number(get_any(metrics_ttm, "freeCashFlowPerShareTTM", "freeCashFlowPerShare"), get_any(metrics_latest, "freeCashFlowPerShare"), divide_or_none(fcf, shares)),
        "gross_margin_pct": ratio_to_percent(first_number(get_any(ratios_ttm, "grossProfitMarginTTM", "grossProfitMargin"), get_any(ratios_latest, "grossProfitMargin"), divide_or_none(latest_income.get("grossProfit"), revenue))),
        "operating_margin_pct": ratio_to_percent(first_number(get_any(ratios_ttm, "operatingProfitMarginTTM", "operatingProfitMargin"), get_any(ratios_latest, "operatingProfitMargin"), divide_or_none(latest_income.get("operatingIncome"), revenue))),
        "net_margin_pct": ratio_to_percent(first_number(get_any(ratios_ttm, "netProfitMarginTTM", "netProfitMargin"), get_any(ratios_latest, "netProfitMargin"), divide_or_none(latest_income.get("netIncome"), revenue))),
        "roe_pct": ratio_to_percent(first_number(first_number_from_rows(ratios_rows, "returnOnEquityTTM", "returnOnEquity", "roeTTM", "roe"), get_any(metrics_ttm, "roeTTM", "returnOnEquityTTM"))),
        "roic_pct": ratio_to_percent(first_number(get_any(ratios_ttm, "returnOnInvestedCapitalTTM", "returnOnInvestedCapital", "roicTTM", "roic"), get_any(ratios_latest, "returnOnInvestedCapital", "roic"), get_any(metrics_ttm, "roicTTM", "roic"), get_any(metrics_latest, "roic", "returnOnInvestedCapital"))),
        "debt_to_equity": first_number(first_number_from_rows(ratios_rows, "debtToEquityRatioTTM", "debtToEquityRatio", "debtEquityRatioTTM", "debtEquityRatio", "debtToEquityTTM", "debtToEquity"), get_any(metrics_ttm, "debtToEquityRatioTTM", "debtToEquityRatio", "debtToEquityTTM", "debtToEquity")),
        "current_ratio": first_number(get_any(ratios_ttm, "currentRatioTTM", "currentRatio"), get_any(ratios_latest, "currentRatio")),
        "net_debt": net_debt,
        "shares_outstanding": shares,
        "enterprise_value": first_number(get_any(metrics_ttm, "enterpriseValueTTM", "enterpriseValue"), get_any(metrics_latest, "enterpriseValue")),
        "year_high": first_number(quote.get("yearHigh")),
        "year_low": first_number(quote.get("yearLow")),
    }


def build_financial_statement_payload(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "income_annual": context.get("income_annual") or [],
        "income_quarter": context.get("income_quarter") or [],
        "balance_annual": context.get("balance_annual") or [],
        "balance_quarter": context.get("balance_quarter") or [],
        "cashflow_annual": context.get("cashflow_annual") or [],
        "cashflow_quarter": context.get("cashflow_quarter") or [],
        "as_reported": context.get("income_as_reported") or [],
    }


def summarize_annual_reports(
    *,
    reports: list[dict[str, Any]],
    symbol: str,
    user_id: str,
    config: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not reports or not os.getenv("OPENAI_API_KEY"):
        return [], []
    from openai import OpenAI

    model = config.get("openai", {}).get("annual_report_extract_model") or config.get("openai", {}).get("model") or "gpt-4.1-mini"
    payload = [
        {
            "source_key": f"annual_report_{index}",
            "year": report.get("year") or str(report.get("date") or report.get("fillingDate") or "")[:4],
            "period": report.get("period") or "FY",
            "report": compact_json_text(report, 12_000),
        }
        for index, report in enumerate(reports[:3], start=1)
    ]
    instructions = {
        "task": "Extract the most useful investor-readable 10-K / annual report summary from the supplied structured annual report JSON.",
        "requirements": [
            "Return JSON only.",
            "Do not mention the data provider.",
            "Do not describe missing data or source inconsistencies.",
            "Prefer concrete disclosures, segment details, risk factors, capital allocation, liquidity, contractual obligations, and management discussion.",
            "Use clear section headings and concise but substantive bullets.",
        ],
        "output_schema": {
            "reports": [
                {
                    "source_key": "annual_report_1",
                    "title": "string",
                    "summary": "string",
                    "sections": [{"title": "string", "bullets": ["string"]}],
                }
            ]
        },
        "company": {"symbol": symbol},
        "reports": payload,
    }
    response = OpenAI(timeout=180).responses.create(
        model=model,
        input=[
            {"role": "system", "content": "You write clean investor research extracts as JSON only."},
            {"role": "user", "content": json.dumps(instructions, ensure_ascii=False)},
        ],
    )
    usage = openai_usage_summary(response, model, config)
    usage_id = log_openai_usage(user_id, "research_annual_report_extract", usage)
    if usage_id:
        usage["usage_id"] = usage_id
    parsed = parse_model_json(response.output_text)
    if not isinstance(parsed, dict):
        return [], [usage]
    extracts = parsed.get("reports") if isinstance(parsed.get("reports"), list) else []
    clean_extracts = [item for item in extracts if isinstance(item, dict)]
    return clean_extracts, [usage]


def attach_annual_report_extracts(context: dict[str, Any], extracts: list[dict[str, Any]]) -> None:
    by_key = {str(item.get("source_key")): item for item in extracts if item.get("source_key")}
    if not by_key:
        return
    for source in context.get("sources") or []:
        source_key = source.get("source_key")
        if source.get("source_type") == "annual_report_json" and source_key in by_key:
            metadata = dict(source.get("metadata") or {})
            metadata["extract"] = by_key[source_key]
            source["metadata"] = metadata


def fallback_research(context: dict[str, Any], dcf: dict[str, Any]) -> dict[str, Any]:
    profile = context.get("profile") or {}
    return {
        "signal": "needs_review",
        "executive_summary": [
            f"{profile.get('companyName') or 'The company'} operates in {profile.get('industry') or profile.get('sector') or 'its reported industry'}.",
            "The generated research uses available statements, ratios, estimates, filings, transcripts, and news, but the narrative model output was unavailable.",
        ],
        "business_overview": [profile.get("description") or "Company description was unavailable in FMP profile data."],
        "financial_analysis": ["Review the included historical revenue, earnings, cash flow, margin, and valuation artifacts."],
        "valuation": [
            f"Base DCF intrinsic value per share: {dcf.get('intrinsic_value_per_share')!r}.",
            f"Base DCF upside/downside versus current price: {dcf.get('upside_downside_pct')!r}%.",
        ],
        "risks": ["Model narrative was unavailable, so risk analysis should be reviewed manually."],
        "catalysts": [],
        "watch_items": [],
        "source_notes": [],
        "sections": [],
    }


def generate_deep_research(
    *,
    user_id: str,
    stock_id: str,
    symbol: str,
    company_name: str,
    relationship: str,
    model: str | None = None,
    progress: Callable[[str, int], None] | None = None,
) -> dict[str, Any]:
    config = load_yaml(ROOT / "config.yaml")
    fmp_api_key = os.getenv("FMP_API_KEY")
    if not fmp_api_key:
        raise RuntimeError("FMP_API_KEY is not configured.")
    selected_model = model or config.get("openai", {}).get("deep_research_model", DEEP_RESEARCH_MODEL)
    fmp_config = config.get("fmp", {})
    client = FmpClient(
        api_key=fmp_api_key,
        base_url=fmp_config.get("base_url", "https://financialmodelingprep.com/stable"),
        timeout_seconds=int(fmp_config.get("request_timeout_seconds", 20)),
    )
    progress = progress or (lambda _step, _pct: None)

    context = fetch_deep_research_context(client, symbol, progress)
    progress("Preparing valuation and chart artifacts", 66)
    artifacts = build_artifacts(context)
    dcf = build_dcf(context)
    try:
        progress("Summarizing annual report disclosures", 70)
        annual_report_extracts, annual_report_usage = summarize_annual_reports(
            reports=context.get("annual_reports") or [],
            symbol=symbol,
            user_id=user_id,
            config=config,
        )
        context["annual_report_extracts"] = annual_report_extracts
        context["annual_report_usage"] = annual_report_usage
        attach_annual_report_extracts(context, annual_report_extracts)
    except Exception:
        context["annual_report_extracts"] = []
        context["annual_report_usage"] = []
    model_context = build_model_context(symbol, company_name, relationship, context, artifacts, dcf)

    research: dict[str, Any]
    usage: dict[str, Any]
    usage_id: str | None = None
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not configured.")

    progress("Writing deep research narrative", 76)
    from openai import OpenAI

    system = (
        "You produce institutional-quality investment research as JSON only. "
        "Use only the supplied structured context. Do not invent facts. "
        "Prefer concrete numbers, historical context, structured source keys, and direct synthesis. "
        "Do not write bracketed source references like [fmp_quote] inside prose. "
        "Put openable source keys only in section.source_keys. "
        "Do not mention the data provider, source conflicts, or internal data availability problems in prose. "
        "Do not recommend buying, selling, holding, or position sizing."
    )
    user = {
        "task": "Create a comprehensive deep research report for one public company.",
        "requirements": [
            "Return one coherent report in sections only; do not duplicate sections or create primer-style top-level summaries.",
            "Use this exact section order when applicable: Business overview; Products and segments; Revenue model and customers; Competitive position; Recent developments; Financial statements and profitability; Balance sheet and cash flow; Valuation and DCF; Risks; Catalysts and monitoring checklist.",
            "Start broad and then go deeper: explain what the company does before analyzing the financials.",
            "Use earnings transcripts, filings, financial statements, analyst estimates, stock grades, and news when they are supplied.",
            "Do not say transcripts or filings are missing if transcript_samples, filings, or annual_report_extracts contain data.",
            "For each section, put relevant openable source keys into source_keys instead of inline bracket citations.",
            "Do not write about source inconsistencies, data conflicts, or internal limitations. Choose the most relevant values from the supplied structured context.",
            "Write premium long-form analysis. Each major section should be useful on its own, with a substantial paragraph summary and detailed subpoints.",
            "Use fewer one-sentence bullets. For products and segments, use product/segment names followed by deeper explanatory paragraphs.",
            "Synthesize source material directly in the report; sources are for verification, not a substitute for analysis.",
            "Discuss transcript commentary, annual report / 10-K disclosures, financial statement trends, stock grades, analyst context, and recent news wherever relevant.",
            "Create a substantial Recent developments section from the last six months of news and current company context. Cover what the company is dealing with now: opportunities, pressure points, customer or product momentum, major contracts, regulatory issues, strategic changes, and near-term monitoring items.",
            "Do not mention the name of the data provider in prose.",
            "Return detailed JSON that can be rendered into a multi-section report.",
        ],
        "output_schema": {
            "signal": "positive_signal | neutral_signal | negative_signal | needs_review",
            "sections": [{"title": "string", "summary": "string", "bullets": ["string"], "source_keys": ["string"]}],
        },
        "context": model_context,
    }
    response = OpenAI(timeout=300).responses.create(
        model=selected_model,
        input=[
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
        ],
    )
    usage = openai_usage_summary(response, selected_model, config)
    usage_id = log_openai_usage(user_id, "research_deep_research", usage)
    if usage_id:
        usage["usage_id"] = usage_id
    try:
        parsed_research = parse_model_json(response.output_text)
        research = parsed_research if isinstance(parsed_research, dict) else fallback_research(context, dcf)
    except Exception:
        research = fallback_research(context, dcf)

    progress("Finalizing deep research", 92)
    signal = str(research.get("signal") or "needs_review")
    earnings_reports = build_earnings_reports(context, dt.date.today())
    body = {
        "mode": "deep_research",
        "relationship": relationship,
        "stock": {
            "stock_id": stock_id,
            "symbol": symbol,
            "company_name": company_name,
            "logo_url": f"https://financialmodelingprep.com/image-stock/{symbol.upper()}.png",
        },
        "research": research,
        "market_data": {
            "price_history": context.get("price_history") or [],
            "pe_history": find_artifact_series(artifacts, "P/E ratio", "annual") or find_artifact_series(artifacts, "P/E ratio", "quarter"),
            "pe_history_period": find_artifact_period(artifacts, "P/E ratio", "annual"),
            "earnings_reports": earnings_reports.get("reports") or [],
            "next_earnings_date": earnings_reports.get("next_earnings_date"),
            "metrics": build_metric_snapshot(context),
        },
        "deep_research": {
            "dcf": dcf,
            "artifacts": artifacts,
            "sources": context["sources"],
            "statements": build_financial_statement_payload(context),
            "transcripts": context.get("transcripts") or [],
            "filings": context.get("sec_filings") or [],
            "annual_reports": context.get("annual_reports") or [],
            "annual_report_extracts": context.get("annual_report_extracts") or [],
            "analyst_estimates": context.get("analyst_estimates") or [],
            "analyst_recommendations": context.get("analyst_recommendations") or [],
            "stock_grades": context.get("stock_grades") or [],
            "insider_trading": context.get("insider_trading") or [],
            "news": context.get("news") or [],
        },
        "usage": usage,
    }
    return {
        "body": body,
        "signal": signal,
        "sources": context["sources"],
        "artifacts": artifacts,
        "usage": usage,
        "usage_id": usage_id,
    }
