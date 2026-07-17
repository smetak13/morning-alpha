from __future__ import annotations

import datetime as dt
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo


INTRADAY_PRICE_SOURCES = ("1min", "5min", "15min")
AFTERMARKET_PRICE_SOURCE = "aftermarket-quote"
PRICE_SOURCES = (*INTRADAY_PRICE_SOURCES, AFTERMARKET_PRICE_SOURCE)
US_MARKET_TZ = ZoneInfo("America/New_York")


def fmp_items(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict):
        items = data.get("historical") or data.get("historicalStockList") or data.get("data") or []
    elif isinstance(data, list):
        items = data
    else:
        return []
    return [item for item in items if isinstance(item, dict)]


def parse_price_datetime(value: Any) -> dt.datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for candidate in (text, text.replace(" ", "T")):
        try:
            parsed = dt.datetime.fromisoformat(candidate[:19])
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=US_MARKET_TZ).astimezone(dt.timezone.utc)
            return parsed.astimezone(dt.timezone.utc)
        except ValueError:
            continue
    try:
        parsed_date = dt.date.fromisoformat(text[:10])
        return dt.datetime.combine(parsed_date, dt.time.min, tzinfo=dt.timezone.utc)
    except ValueError:
        return None


def decimal_price(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        price = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if price <= 0:
        return None
    return price.quantize(Decimal("0.0001"))


def us_market_session(now: dt.datetime | None = None) -> str:
    current = now or dt.datetime.now(dt.timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=dt.timezone.utc)
    local = current.astimezone(US_MARKET_TZ)
    regular_open = dt.time(9, 30)
    regular_close = dt.time(16, 0)
    local_time = local.time()
    if local.weekday() < 5 and regular_open <= local_time < regular_close:
        return "regular"
    return "aftermarket"


def first_item(data: Any) -> dict[str, Any]:
    items = fmp_items(data)
    if items:
        return items[0]
    return data if isinstance(data, dict) else {}


def parse_aftermarket_price_at(row: dict[str, Any]) -> dt.datetime | None:
    raw_value = (
        row.get("timestamp")
        or row.get("bidTimestamp")
        or row.get("bidTime")
        or row.get("askTimestamp")
        or row.get("askTime")
        or row.get("lastSaleTimestamp")
        or row.get("lastTradeTimestamp")
        or row.get("time")
        or row.get("date")
        or row.get("updatedAt")
        or row.get("updated_at")
    )
    if raw_value in (None, ""):
        return None
    if isinstance(raw_value, (int, float)):
        value = float(raw_value)
        if value > 10_000_000_000:
            value = value / 1000
        try:
            return dt.datetime.fromtimestamp(value, tz=dt.timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    return parse_price_datetime(raw_value)


def latest_aftermarket_price(client: Any, symbol: str) -> dict[str, Any] | None:
    cleaned_symbol = str(symbol or "").upper().strip()
    if not cleaned_symbol:
        return None
    try:
        row = first_item(client.get(AFTERMARKET_PRICE_SOURCE, {"symbol": cleaned_symbol}))
    except Exception:
        return None
    if not row:
        return None

    bid = decimal_price(row.get("bid") or row.get("bidPrice"))
    ask = decimal_price(row.get("ask") or row.get("askPrice"))
    midpoint = ((bid + ask) / Decimal("2")).quantize(Decimal("0.0001")) if bid is not None and ask is not None else None
    price = (
        midpoint
        or ask
        or bid
        or decimal_price(row.get("last") or row.get("lastPrice") or row.get("lastSalePrice") or row.get("lastTradePrice"))
        or decimal_price(row.get("price"))
    )
    if price is None:
        return None
    return {
        "price": price,
        "source": AFTERMARKET_PRICE_SOURCE,
        "price_at": parse_aftermarket_price_at(row),
        "checked_at": dt.datetime.now(dt.timezone.utc),
    }


def latest_intraday_price(client: Any, symbol: str) -> dict[str, Any] | None:
    cleaned_symbol = str(symbol or "").upper().strip()
    if not cleaned_symbol:
        return None

    for source in INTRADAY_PRICE_SOURCES:
        for endpoint, params in (
            (f"historical-chart/{source}", {"symbol": cleaned_symbol}),
            (f"historical-chart/{source}/{cleaned_symbol}", {}),
        ):
            try:
                rows = fmp_items(client.get(endpoint, params))
            except Exception:
                continue
            candidates: list[tuple[dt.datetime, Decimal]] = []
            for row in rows:
                price_at = parse_price_datetime(row.get("date"))
                price = decimal_price(row.get("close") or row.get("adjClose") or row.get("price"))
                if price_at is None or price is None:
                    continue
                candidates.append((price_at, price))
            if candidates:
                price_at, price = max(candidates, key=lambda item: item[0])
                return {
                    "price": price,
                    "source": source,
                    "price_at": price_at,
                    "checked_at": dt.datetime.now(dt.timezone.utc),
                }
    return None


def latest_market_price(client: Any, symbol: str, now: dt.datetime | None = None) -> dict[str, Any] | None:
    if us_market_session(now) != "regular":
        latest = latest_aftermarket_price(client, symbol)
        if latest is not None:
            return latest
    return latest_intraday_price(client, symbol)
