from __future__ import annotations

import datetime as dt
from decimal import Decimal, InvalidOperation
from typing import Any


INTRADAY_PRICE_SOURCES = ("1min", "5min", "15min")


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
                return parsed.replace(tzinfo=dt.timezone.utc)
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
