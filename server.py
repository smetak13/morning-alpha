from __future__ import annotations

import os
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from database import connection
from neon_auth import load_settings


ROOT = Path(__file__).resolve().parent
ASSETS_DIR = ROOT / "assets"
FRONTEND_DIST = ROOT / "frontend" / "dist"
FRONTEND_INDEX = FRONTEND_DIST / "index.html"
DEFAULT_TIMEZONE = "Europe/Prague"

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


if load_dotenv is not None:
    load_dotenv()


def parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def run_alembic_migrations() -> None:
    try:
        from alembic import command
        from alembic.config import Config
    except ImportError as exc:
        raise RuntimeError("Missing dependency 'alembic'. Install dependencies with: pip install -r requirements.txt") from exc

    config = Config(str(ROOT / "alembic.ini"))
    command.upgrade(config, "head")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    if parse_bool(os.getenv("API_RUN_MIGRATIONS_ON_STARTUP"), default=True):
        run_alembic_migrations()
    yield


class RegisterRequest(BaseModel):
    provider: str = "email"
    email: str | None = None
    password: str | None = None
    name: str | None = None
    display_name: str | None = None
    timezone: str | None = None
    id_token: str | None = None
    access_token: str | None = None


class LoginRequest(BaseModel):
    provider: str = "email"
    email: str | None = None
    password: str | None = None
    remember_me: bool = True
    id_token: str | None = None
    access_token: str | None = None


class GoogleIdTokenRequest(BaseModel):
    id_token: str
    access_token: str | None = None
    timezone: str | None = None


class StockSearchResult(BaseModel):
    symbol: str
    company_name: str
    exchange: str | None = None
    logo_url: str | None = None


class DraftThesisRequest(BaseModel):
    item_type: Literal["portfolio", "watchlist"]
    symbol: str
    company_name: str


class PortfolioItemCreateRequest(BaseModel):
    symbol: str
    company_name: str
    position_size_pct: float = 10
    why_i_own_it: list[str] = Field(default_factory=list)
    bull_case: list[str] = Field(default_factory=list)
    bear_case: list[str] = Field(default_factory=list)
    key_metrics: list[str] = Field(default_factory=list)
    red_flags: list[str] = Field(default_factory=list)
    action_triggers: list[str] = Field(default_factory=list)


class PortfolioItemUpdateRequest(BaseModel):
    position_size_pct: float | None = None
    why_i_own_it: list[str] | None = None
    bull_case: list[str] | None = None
    bear_case: list[str] | None = None
    key_metrics: list[str] | None = None
    red_flags: list[str] | None = None
    action_triggers: list[str] | None = None


class WatchlistItemCreateRequest(BaseModel):
    symbol: str
    company_name: str
    why_i_watch_it: list[str] = Field(default_factory=list)
    bull_case: list[str] = Field(default_factory=list)
    bear_case: list[str] = Field(default_factory=list)
    key_metrics: list[str] = Field(default_factory=list)
    red_flags: list[str] = Field(default_factory=list)
    action_triggers: list[str] = Field(default_factory=list)


class WatchlistItemUpdateRequest(BaseModel):
    why_i_watch_it: list[str] | None = None
    bull_case: list[str] | None = None
    bear_case: list[str] | None = None
    key_metrics: list[str] | None = None
    red_flags: list[str] | None = None
    action_triggers: list[str] | None = None


def create_app() -> FastAPI:
    app = FastAPI(title="Morning Alpha API", lifespan=lifespan)

    allowed_origins = [origin.strip() for origin in os.getenv("API_CORS_ORIGINS", "").split(",") if origin.strip()]
    if allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=allowed_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    if ASSETS_DIR.is_dir():
        app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")

    return app


app = create_app()


def neon_auth_url(path: str) -> str:
    settings = load_settings()
    missing = settings.missing_required()
    if missing:
        raise RuntimeError(f"Neon Auth config incomplete. Missing: {', '.join(missing)}")
    return f"{settings.auth_url.rstrip('/')}/{path.lstrip('/')}"


def copy_set_cookie_headers(upstream: httpx.Response, response: Response) -> None:
    for cookie in upstream.headers.get_list("set-cookie"):
        response.raw_headers.append((b"set-cookie", cookie.encode("latin-1")))


def forwarded_headers(request: Request) -> dict[str, str]:
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
    }
    origin = (
        os.getenv("API_PUBLIC_URL")
        or f"http://{os.getenv('API_HOST', '127.0.0.1')}:{os.getenv('API_PORT', '8000')}"
    )
    headers["origin"] = origin
    if request.headers.get("cookie"):
        headers["cookie"] = request.headers["cookie"]
    if request.headers.get("user-agent"):
        headers["user-agent"] = request.headers["user-agent"]
    return headers


def parse_upstream_json(upstream: httpx.Response) -> Any:
    try:
        return upstream.json()
    except ValueError:
        return {"detail": upstream.text}


def extract_user(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None

    user = payload.get("user")
    if isinstance(user, dict):
        return user

    data_user = extract_user(payload.get("data"))
    if data_user:
        return data_user

    session = payload.get("session")
    if isinstance(session, dict):
        session_user = session.get("user")
        if isinstance(session_user, dict):
            return session_user

    return None


def user_display_name(user: dict[str, Any]) -> str | None:
    value = user.get("name") or user.get("displayName") or user.get("display_name")
    return str(value) if value else None


def normalize_timezone(value: str | None) -> str:
    timezone = (value or "").strip()
    if not timezone:
        return DEFAULT_TIMEZONE
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError:
        return DEFAULT_TIMEZONE
    return timezone


def get_user_profile(user_id: Any) -> dict[str, Any] | None:
    try:
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise RuntimeError("Missing dependency 'psycopg'. Install dependencies with: pip install -r requirements.txt") from exc

    with connection(row_factory=dict_row) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                select
                    id,
                    email,
                    display_name,
                    timezone,
                    locale,
                    report_scheduled_at,
                    created_at,
                    updated_at
                from public.users
                where id = %(id)s
                """,
                {"id": str(user_id)},
            )
            row = cursor.fetchone()

    return dict(row) if row else None


def create_user_profile_if_missing(user: dict[str, Any], timezone: str | None = None) -> dict[str, Any] | None:
    user_id = user.get("id")
    if not user_id:
        raise RuntimeError("Neon Auth response does not contain user.id.")

    try:
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise RuntimeError("Missing dependency 'psycopg'. Install dependencies with: pip install -r requirements.txt") from exc

    params = {
        "id": str(user_id),
        "email": str(user["email"]) if user.get("email") else None,
        "display_name": user_display_name(user),
        "timezone": normalize_timezone(timezone),
    }

    with connection(row_factory=dict_row) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                insert into public.users (id, email, display_name, timezone)
                values (%(id)s, %(email)s, %(display_name)s, %(timezone)s)
                on conflict (id) do nothing
                returning
                    id,
                    email,
                    display_name,
                    timezone,
                    locale,
                    report_scheduled_at,
                    created_at,
                    updated_at
                """,
                params,
            )
            row = cursor.fetchone()

    return dict(row) if row else get_user_profile(user_id)


def upstream_json_response(upstream: httpx.Response, response: Response, payload: Any) -> dict[str, Any]:
    copy_set_cookie_headers(upstream, response)
    response.status_code = upstream.status_code
    if isinstance(payload, dict):
        return payload
    return {"data": payload}


def post_to_neon_auth(path: str, body: dict[str, Any], request: Request) -> httpx.Response:
    timeout = float(os.getenv("NEON_AUTH_TIMEOUT_SECONDS", "15"))
    with httpx.Client(timeout=timeout, follow_redirects=False) as client:
        return client.post(neon_auth_url(path), json=body, headers=forwarded_headers(request))


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/register")
def register(payload: RegisterRequest, request: Request, response: Response) -> dict[str, Any]:
    provider = payload.provider.lower()
    if provider == "google":
        if not payload.id_token:
            raise HTTPException(status_code=422, detail="id_token is required for Google auth.")
        return authenticate_google_id_token(
            GoogleIdTokenRequest(
                id_token=payload.id_token,
                access_token=payload.access_token,
                timezone=payload.timezone,
            ),
            request,
            response,
            create_profile=True,
        )
    if provider != "email":
        raise HTTPException(status_code=422, detail="provider must be 'email' or 'google'.")
    if not payload.email or not payload.password:
        raise HTTPException(status_code=422, detail="email and password are required for email auth.")

    name = payload.name or payload.display_name or payload.email.split("@", 1)[0]
    upstream = post_to_neon_auth(
        "/sign-up/email",
        {
            "email": payload.email,
            "password": payload.password,
            "name": name,
        },
        request,
    )
    auth_payload = parse_upstream_json(upstream)
    if upstream.status_code >= 400:
        return upstream_json_response(upstream, response, auth_payload)

    user = extract_user(auth_payload)
    profile = create_user_profile_if_missing(user, timezone=payload.timezone) if user else None
    response.status_code = upstream.status_code
    copy_set_cookie_headers(upstream, response)
    return {"auth": auth_payload, "user": profile}


@app.post("/login")
def login(payload: LoginRequest, request: Request, response: Response) -> dict[str, Any]:
    provider = payload.provider.lower()
    if provider == "google":
        if not payload.id_token:
            raise HTTPException(status_code=422, detail="id_token is required for Google auth.")
        return authenticate_google_id_token(
            GoogleIdTokenRequest(id_token=payload.id_token, access_token=payload.access_token),
            request,
            response,
            create_profile=False,
        )
    if provider != "email":
        raise HTTPException(status_code=422, detail="provider must be 'email' or 'google'.")
    if not payload.email or not payload.password:
        raise HTTPException(status_code=422, detail="email and password are required for email auth.")

    upstream = post_to_neon_auth(
        "/sign-in/email",
        {
            "email": payload.email,
            "password": payload.password,
            "rememberMe": payload.remember_me,
        },
        request,
    )
    auth_payload = parse_upstream_json(upstream)
    if upstream.status_code >= 400:
        return upstream_json_response(upstream, response, auth_payload)

    user = extract_user(auth_payload)
    profile = get_user_profile(user["id"]) if user and user.get("id") else None
    response.status_code = upstream.status_code
    copy_set_cookie_headers(upstream, response)
    return {"auth": auth_payload, "user": profile}


@app.post("/login/google/id-token")
def login_google_id_token(payload: GoogleIdTokenRequest, request: Request, response: Response) -> dict[str, Any]:
    return authenticate_google_id_token(payload, request, response, create_profile=False)


@app.post("/register/google/id-token")
def register_google_id_token(payload: GoogleIdTokenRequest, request: Request, response: Response) -> dict[str, Any]:
    return authenticate_google_id_token(payload, request, response, create_profile=True)


def authenticate_google_id_token(
    payload: GoogleIdTokenRequest,
    request: Request,
    response: Response,
    create_profile: bool,
) -> dict[str, Any]:
    id_token: dict[str, str] = {"token": payload.id_token}
    if payload.access_token:
        id_token["accessToken"] = payload.access_token

    upstream = post_to_neon_auth(
        "/sign-in/social",
        {
            "provider": "google",
            "idToken": id_token,
        },
        request,
    )
    auth_payload = parse_upstream_json(upstream)
    if upstream.status_code >= 400:
        return upstream_json_response(upstream, response, auth_payload)

    user = extract_user(auth_payload)
    if create_profile and user:
        profile = create_user_profile_if_missing(user, timezone=payload.timezone)
    elif user and user.get("id"):
        profile = get_user_profile(user["id"])
    else:
        profile = None

    response.status_code = upstream.status_code
    copy_set_cookie_headers(upstream, response)
    return {"auth": auth_payload, "user": profile}


@app.get("/me")
def me(request: Request, response: Response) -> dict[str, Any]:
    timeout = float(os.getenv("NEON_AUTH_TIMEOUT_SECONDS", "15"))
    with httpx.Client(timeout=timeout, follow_redirects=False) as client:
        upstream = client.get(neon_auth_url("/get-session"), headers=forwarded_headers(request))

    auth_payload = parse_upstream_json(upstream)
    if upstream.status_code >= 400:
        return upstream_json_response(upstream, response, auth_payload)

    user = extract_user(auth_payload)
    profile = get_user_profile(user["id"]) if user and user.get("id") else None
    response.status_code = upstream.status_code
    copy_set_cookie_headers(upstream, response)
    return {"auth": auth_payload, "user": profile}


@app.post("/logout")
def logout(request: Request, response: Response) -> dict[str, Any]:
    upstream = post_to_neon_auth("/sign-out", {}, request)
    return upstream_json_response(upstream, response, parse_upstream_json(upstream))


def current_auth_user(request: Request) -> dict[str, Any]:
    timeout = float(os.getenv("NEON_AUTH_TIMEOUT_SECONDS", "15"))
    with httpx.Client(timeout=timeout, follow_redirects=False) as client:
        upstream = client.get(neon_auth_url("/get-session"), headers=forwarded_headers(request))

    auth_payload = parse_upstream_json(upstream)
    if upstream.status_code >= 400:
        raise HTTPException(status_code=401, detail="Not authenticated.")

    user = extract_user(auth_payload)
    if not user or not user.get("id"):
        raise HTTPException(status_code=401, detail="Not authenticated.")
    return user


def current_user_id(request: Request) -> str:
    return str(current_auth_user(request)["id"])


def stock_logo_url(symbol: str) -> str:
    return f"https://financialmodelingprep.com/image-stock/{symbol.upper()}.png"


def clean_symbol(value: str) -> str:
    symbol = value.upper().strip()
    symbol = "".join(char for char in symbol if char.isalnum() or char in {".", "-"})
    if not symbol:
        raise HTTPException(status_code=422, detail="Stock symbol is required.")
    return symbol


def clean_bullets(values: list[str] | None) -> list[str]:
    if not values:
        return []
    return [str(value).strip() for value in values if str(value).strip()]


def fmp_client_from_env() -> Any:
    from report import FmpClient, load_yaml

    api_key = os.getenv("FMP_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="FMP_API_KEY is not configured.")

    config = load_yaml(ROOT / "config.yaml")
    fmp_config = config.get("fmp", {})
    return FmpClient(
        api_key=api_key,
        base_url=fmp_config.get("base_url", "https://financialmodelingprep.com/stable"),
        timeout_seconds=int(fmp_config.get("request_timeout_seconds", 20)),
    )


def normalize_stock_search_item(item: dict[str, Any]) -> StockSearchResult | None:
    symbol = str(item.get("symbol") or item.get("ticker") or "").upper().strip()
    company_name = str(
        item.get("name") or item.get("companyName") or item.get("company_name") or item.get("securityName") or ""
    ).strip()
    if not symbol or not company_name:
        return None
    exchange = str(
        item.get("exchangeShortName") or item.get("exchange") or item.get("stockExchange") or ""
    ).strip() or None
    return StockSearchResult(
        symbol=symbol,
        company_name=company_name,
        exchange=exchange,
        logo_url=stock_logo_url(symbol),
    )


@app.get("/api/stocks/search")
def search_stocks(q: str, request: Request) -> dict[str, Any]:
    current_user_id(request)
    query = q.strip()
    if len(query) < 1:
        return {"results": []}

    client = fmp_client_from_env()
    results_by_symbol: dict[str, StockSearchResult] = {}
    for endpoint in ("search-symbol", "search-name"):
        try:
            data = client.get(endpoint, {"query": query, "limit": 8})
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"FMP search failed: {exc}") from exc
        if not isinstance(data, list):
            continue
        for item in data:
            if not isinstance(item, dict):
                continue
            result = normalize_stock_search_item(item)
            if result:
                results_by_symbol.setdefault(result.symbol, result)

    return {"results": [result.model_dump() for result in list(results_by_symbol.values())[:12]]}


def draft_thesis_schema(item_type: str) -> dict[str, Any]:
    first_field = "why_i_own_it" if item_type == "portfolio" else "why_i_watch_it"
    return {
        first_field: ["string"],
        "bull_case": ["string"],
        "bear_case": ["string"],
        "key_metrics": ["string"],
        "red_flags": ["string"],
        "action_triggers": ["string"],
    }


def normalize_draft_thesis(payload: dict[str, Any], item_type: str) -> dict[str, list[str]]:
    schema = draft_thesis_schema(item_type)
    normalized: dict[str, list[str]] = {}
    for key in schema:
        value = payload.get(key)
        if isinstance(value, str):
            normalized[key] = clean_bullets([value])
        elif isinstance(value, list):
            normalized[key] = clean_bullets([str(item) for item in value])
        else:
            normalized[key] = []
    return normalized


@app.post("/api/thesis/draft")
def draft_thesis(payload: DraftThesisRequest, request: Request) -> dict[str, Any]:
    current_user_id(request)
    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY is not configured.")

    from openai import OpenAI
    from report import load_yaml, parse_model_json

    symbol = clean_symbol(payload.symbol)
    company_name = payload.company_name.strip() or symbol
    config = load_yaml(ROOT / "config.yaml")
    model = config.get("openai", {}).get("model", "gpt-4.1-mini")
    schema = draft_thesis_schema(payload.item_type)
    first_label = "why_i_own_it" if payload.item_type == "portfolio" else "why_i_watch_it"
    first_guidance = (
        "possible reasons a long-term investor might own this company"
        if payload.item_type == "portfolio"
        else "possible reasons a long-term investor might watch this company"
    )

    prompt = {
        "task": "Generate a neutral draft investment thesis for a user to review and edit.",
        "company": {"symbol": symbol, "company_name": company_name},
        "item_type": payload.item_type,
        "required_json_schema": schema,
        "field_guidance": {
            first_label: first_guidance,
            "bull_case": "3 concise bullets for what could go right",
            "bear_case": "3 concise bullets for what could go wrong",
            "key_metrics": "3 concise metrics or signals to monitor",
            "red_flags": "3 concise warning signs",
            "action_triggers": "3 concise events or evidence that would justify reviewing the thesis",
        },
        "constraints": [
            "Return valid JSON only.",
            "Each field must be an array of 2 to 4 short bullets.",
            "Do not recommend buying, selling, holding, position sizing, or trading.",
            "Use cautious language because this is only an AI draft.",
            "Do not claim to know the user's personal reason; phrase personal-looking fields as possible reasons.",
        ],
    }
    try:
        response = OpenAI().responses.create(
            model=model,
            input=[
                {"role": "system", "content": "You generate concise, neutral investment thesis drafts as JSON only."},
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
        )
        draft = parse_model_json(response.output_text)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Thesis generation failed: {exc}") from exc

    return {
        "stock": {
            "symbol": symbol,
            "company_name": company_name,
            "logo_url": stock_logo_url(symbol),
        },
        "item_type": payload.item_type,
        "thesis": normalize_draft_thesis(draft, payload.item_type),
    }


def get_or_create_stock(cursor: Any, symbol: str, company_name: str) -> str:
    cursor.execute(
        """
        insert into public.stocks (symbol, company_name, is_actively_trading)
        values (%(symbol)s, %(company_name)s, true)
        on conflict (symbol) do update
        set company_name = excluded.company_name,
            is_actively_trading = true
        returning id::text
        """,
        {"symbol": symbol, "company_name": company_name},
    )
    return str(cursor.fetchone()["id"])


def portfolio_total_pct(cursor: Any, user_id: str, exclude_item_id: str | None = None) -> float:
    if exclude_item_id:
        cursor.execute(
            """
            select coalesce(sum(position_size_pct), 0) as total
            from public.portfolio_items
            where user_id = %(user_id)s
              and id::text <> %(exclude_item_id)s
            """,
            {"user_id": user_id, "exclude_item_id": exclude_item_id},
        )
    else:
        cursor.execute(
            """
            select coalesce(sum(position_size_pct), 0) as total
            from public.portfolio_items
            where user_id = %(user_id)s
            """,
            {"user_id": user_id},
        )
    return float(cursor.fetchone()["total"] or 0)


def validate_position_size(value: float, existing_total: float) -> float:
    try:
        position = float(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="position_size_pct must be a number.")
    if position < 0 or position > 100:
        raise HTTPException(status_code=422, detail="position_size_pct must be between 0 and 100.")
    if existing_total + position > 100.00001:
        remaining = max(0, 100 - existing_total)
        raise HTTPException(
            status_code=422,
            detail=f"Portfolio positions cannot exceed 100%. Remaining allocation is {remaining:.2f}%.",
        )
    return position


def serialize_portfolio_row(row: dict[str, Any]) -> dict[str, Any]:
    symbol = str(row["symbol"]).upper()
    return {
        "id": str(row["id"]),
        "stock_id": str(row["stock_id"]),
        "symbol": symbol,
        "company_name": row["company_name"],
        "logo_url": stock_logo_url(symbol),
        "position_size_pct": float(row["position_size_pct"] or 0),
        "why_i_own_it": row["why_i_own_it"] or [],
        "bull_case": row["bull_case"] or [],
        "bear_case": row["bear_case"] or [],
        "key_metrics": row["key_metrics"] or [],
        "red_flags": row["red_flags"] or [],
        "action_triggers": row["action_triggers"] or [],
    }


def serialize_watchlist_row(row: dict[str, Any]) -> dict[str, Any]:
    symbol = str(row["symbol"]).upper()
    return {
        "id": str(row["id"]),
        "stock_id": str(row["stock_id"]),
        "symbol": symbol,
        "company_name": row["company_name"],
        "logo_url": stock_logo_url(symbol),
        "why_i_watch_it": row["why_i_watch_it"] or [],
        "bull_case": row["bull_case"] or [],
        "bear_case": row["bear_case"] or [],
        "key_metrics": row["key_metrics"] or [],
        "red_flags": row["red_flags"] or [],
        "action_triggers": row["action_triggers"] or [],
    }


PORTFOLIO_SELECT = """
    select
        portfolio_items.id::text as id,
        portfolio_items.stock_id::text as stock_id,
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
"""


WATCHLIST_SELECT = """
    select
        watchlist_items.id::text as id,
        watchlist_items.stock_id::text as stock_id,
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
"""


@app.get("/api/portfolio-items")
def list_portfolio_items(request: Request) -> dict[str, Any]:
    user_id = current_user_id(request)
    from psycopg.rows import dict_row

    with connection(row_factory=dict_row) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                PORTFOLIO_SELECT
                + """
                where portfolio_items.user_id = %(user_id)s
                order by portfolio_items.position_size_pct desc nulls last, stocks.symbol
                """,
                {"user_id": user_id},
            )
            rows = cursor.fetchall()

    items = [serialize_portfolio_row(dict(row)) for row in rows]
    return {"items": items, "total_position_size_pct": sum(item["position_size_pct"] for item in items)}


@app.post("/api/portfolio-items")
def create_portfolio_item(payload: PortfolioItemCreateRequest, request: Request) -> dict[str, Any]:
    user_id = current_user_id(request)
    from psycopg.rows import dict_row

    symbol = clean_symbol(payload.symbol)
    company_name = payload.company_name.strip() or symbol
    with connection(row_factory=dict_row) as conn:
        with conn.cursor() as cursor:
            position = validate_position_size(payload.position_size_pct, portfolio_total_pct(cursor, user_id))
            stock_id = get_or_create_stock(cursor, symbol, company_name)
            cursor.execute(
                """
                insert into public.portfolio_items (
                    user_id,
                    stock_id,
                    position_size_pct,
                    why_i_own_it,
                    bull_case,
                    bear_case,
                    key_metrics,
                    red_flags,
                    action_triggers
                )
                values (
                    %(user_id)s,
                    %(stock_id)s,
                    %(position_size_pct)s,
                    %(why_i_own_it)s,
                    %(bull_case)s,
                    %(bear_case)s,
                    %(key_metrics)s,
                    %(red_flags)s,
                    %(action_triggers)s
                )
                on conflict (user_id, stock_id) do nothing
                returning id::text
                """,
                {
                    "user_id": user_id,
                    "stock_id": stock_id,
                    "position_size_pct": position,
                    "why_i_own_it": clean_bullets(payload.why_i_own_it),
                    "bull_case": clean_bullets(payload.bull_case),
                    "bear_case": clean_bullets(payload.bear_case),
                    "key_metrics": clean_bullets(payload.key_metrics),
                    "red_flags": clean_bullets(payload.red_flags),
                    "action_triggers": clean_bullets(payload.action_triggers),
                },
            )
            inserted = cursor.fetchone()
            if not inserted:
                raise HTTPException(status_code=409, detail=f"{symbol} is already in the portfolio.")
            cursor.execute(PORTFOLIO_SELECT + " where portfolio_items.id = %(id)s", {"id": inserted["id"]})
            row = cursor.fetchone()

    return {"item": serialize_portfolio_row(dict(row))}


@app.put("/api/portfolio-items/{item_id}")
def update_portfolio_item(item_id: str, payload: PortfolioItemUpdateRequest, request: Request) -> dict[str, Any]:
    user_id = current_user_id(request)
    from psycopg.rows import dict_row

    updates = payload.model_dump(exclude_unset=True)
    with connection(row_factory=dict_row) as conn:
        with conn.cursor() as cursor:
            cursor.execute(PORTFOLIO_SELECT + " where portfolio_items.id::text = %(id)s and portfolio_items.user_id = %(user_id)s", {"id": item_id, "user_id": user_id})
            current = cursor.fetchone()
            if not current:
                raise HTTPException(status_code=404, detail="Portfolio item not found.")
            current_dict = dict(current)
            position = float(current_dict["position_size_pct"] or 0)
            if "position_size_pct" in updates and updates["position_size_pct"] is not None:
                position = validate_position_size(
                    updates["position_size_pct"],
                    portfolio_total_pct(cursor, user_id, exclude_item_id=item_id),
                )
            params = {
                "id": item_id,
                "user_id": user_id,
                "position_size_pct": position,
                "why_i_own_it": clean_bullets(updates.get("why_i_own_it", current_dict["why_i_own_it"])),
                "bull_case": clean_bullets(updates.get("bull_case", current_dict["bull_case"])),
                "bear_case": clean_bullets(updates.get("bear_case", current_dict["bear_case"])),
                "key_metrics": clean_bullets(updates.get("key_metrics", current_dict["key_metrics"])),
                "red_flags": clean_bullets(updates.get("red_flags", current_dict["red_flags"])),
                "action_triggers": clean_bullets(updates.get("action_triggers", current_dict["action_triggers"])),
            }
            cursor.execute(
                """
                update public.portfolio_items
                set
                    position_size_pct = %(position_size_pct)s,
                    why_i_own_it = %(why_i_own_it)s,
                    bull_case = %(bull_case)s,
                    bear_case = %(bear_case)s,
                    key_metrics = %(key_metrics)s,
                    red_flags = %(red_flags)s,
                    action_triggers = %(action_triggers)s
                where id::text = %(id)s and user_id = %(user_id)s
                """,
                params,
            )
            cursor.execute(PORTFOLIO_SELECT + " where portfolio_items.id::text = %(id)s", {"id": item_id})
            row = cursor.fetchone()

    return {"item": serialize_portfolio_row(dict(row))}


@app.delete("/api/portfolio-items/{item_id}")
def delete_portfolio_item(item_id: str, request: Request) -> dict[str, Any]:
    user_id = current_user_id(request)
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "delete from public.portfolio_items where id::text = %s and user_id = %s",
                (item_id, user_id),
            )
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="Portfolio item not found.")
    return {"deleted": True}


@app.get("/api/watchlist-items")
def list_watchlist_items(request: Request) -> dict[str, Any]:
    user_id = current_user_id(request)
    from psycopg.rows import dict_row

    with connection(row_factory=dict_row) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                WATCHLIST_SELECT
                + """
                where watchlist_items.user_id = %(user_id)s
                order by stocks.symbol
                """,
                {"user_id": user_id},
            )
            rows = cursor.fetchall()

    return {"items": [serialize_watchlist_row(dict(row)) for row in rows]}


@app.post("/api/watchlist-items")
def create_watchlist_item(payload: WatchlistItemCreateRequest, request: Request) -> dict[str, Any]:
    user_id = current_user_id(request)
    from psycopg.rows import dict_row

    symbol = clean_symbol(payload.symbol)
    company_name = payload.company_name.strip() or symbol
    with connection(row_factory=dict_row) as conn:
        with conn.cursor() as cursor:
            stock_id = get_or_create_stock(cursor, symbol, company_name)
            cursor.execute(
                """
                insert into public.watchlist_items (
                    user_id,
                    stock_id,
                    why_i_watch_it,
                    bull_case,
                    bear_case,
                    key_metrics,
                    red_flags,
                    action_triggers
                )
                values (
                    %(user_id)s,
                    %(stock_id)s,
                    %(why_i_watch_it)s,
                    %(bull_case)s,
                    %(bear_case)s,
                    %(key_metrics)s,
                    %(red_flags)s,
                    %(action_triggers)s
                )
                on conflict (user_id, stock_id) do nothing
                returning id::text
                """,
                {
                    "user_id": user_id,
                    "stock_id": stock_id,
                    "why_i_watch_it": clean_bullets(payload.why_i_watch_it),
                    "bull_case": clean_bullets(payload.bull_case),
                    "bear_case": clean_bullets(payload.bear_case),
                    "key_metrics": clean_bullets(payload.key_metrics),
                    "red_flags": clean_bullets(payload.red_flags),
                    "action_triggers": clean_bullets(payload.action_triggers),
                },
            )
            inserted = cursor.fetchone()
            if not inserted:
                raise HTTPException(status_code=409, detail=f"{symbol} is already in the watchlist.")
            cursor.execute(WATCHLIST_SELECT + " where watchlist_items.id = %(id)s", {"id": inserted["id"]})
            row = cursor.fetchone()

    return {"item": serialize_watchlist_row(dict(row))}


@app.put("/api/watchlist-items/{item_id}")
def update_watchlist_item(item_id: str, payload: WatchlistItemUpdateRequest, request: Request) -> dict[str, Any]:
    user_id = current_user_id(request)
    from psycopg.rows import dict_row

    updates = payload.model_dump(exclude_unset=True)
    with connection(row_factory=dict_row) as conn:
        with conn.cursor() as cursor:
            cursor.execute(WATCHLIST_SELECT + " where watchlist_items.id::text = %(id)s and watchlist_items.user_id = %(user_id)s", {"id": item_id, "user_id": user_id})
            current = cursor.fetchone()
            if not current:
                raise HTTPException(status_code=404, detail="Watchlist item not found.")
            current_dict = dict(current)
            params = {
                "id": item_id,
                "user_id": user_id,
                "why_i_watch_it": clean_bullets(updates.get("why_i_watch_it", current_dict["why_i_watch_it"])),
                "bull_case": clean_bullets(updates.get("bull_case", current_dict["bull_case"])),
                "bear_case": clean_bullets(updates.get("bear_case", current_dict["bear_case"])),
                "key_metrics": clean_bullets(updates.get("key_metrics", current_dict["key_metrics"])),
                "red_flags": clean_bullets(updates.get("red_flags", current_dict["red_flags"])),
                "action_triggers": clean_bullets(updates.get("action_triggers", current_dict["action_triggers"])),
            }
            cursor.execute(
                """
                update public.watchlist_items
                set
                    why_i_watch_it = %(why_i_watch_it)s,
                    bull_case = %(bull_case)s,
                    bear_case = %(bear_case)s,
                    key_metrics = %(key_metrics)s,
                    red_flags = %(red_flags)s,
                    action_triggers = %(action_triggers)s
                where id::text = %(id)s and user_id = %(user_id)s
                """,
                params,
            )
            cursor.execute(WATCHLIST_SELECT + " where watchlist_items.id::text = %(id)s", {"id": item_id})
            row = cursor.fetchone()

    return {"item": serialize_watchlist_row(dict(row))}


@app.delete("/api/watchlist-items/{item_id}")
def delete_watchlist_item(item_id: str, request: Request) -> dict[str, Any]:
    user_id = current_user_id(request)
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "delete from public.watchlist_items where id::text = %s and user_id = %s",
                (item_id, user_id),
            )
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="Watchlist item not found.")
    return {"deleted": True}


def frontend_dist_file(path: str) -> Path | None:
    try:
        candidate = (FRONTEND_DIST / path).resolve()
        candidate.relative_to(FRONTEND_DIST.resolve())
    except ValueError:
        return None

    if candidate.is_file():
        return candidate
    return None


def serve_frontend(path: str = "") -> Response:
    if path:
        static_file = frontend_dist_file(path)
        if static_file:
            return FileResponse(static_file)
        if "." in Path(path).name:
            raise HTTPException(status_code=404, detail="Frontend asset not found.")

    if FRONTEND_INDEX.is_file():
        return FileResponse(FRONTEND_INDEX)

    return HTMLResponse(
        """
        <!doctype html>
        <html lang="en">
          <head><meta charset="utf-8"><title>Morning Alpha</title></head>
          <body>
            <h1>Morning Alpha frontend is not built</h1>
            <p>Run <code>npm install</code> and <code>npm run build</code> in the <code>frontend</code> directory.</p>
          </body>
        </html>
        """,
        status_code=503,
    )


@app.get("/", include_in_schema=False, response_model=None)
def frontend_root() -> Response:
    return serve_frontend()


@app.get("/{path:path}", include_in_schema=False, response_model=None)
def frontend_fallback(path: str) -> Response:
    return serve_frontend(path)


if __name__ == "__main__":
    try:
        import uvicorn
    except ImportError as exc:
        raise RuntimeError("Missing dependency 'uvicorn'. Install dependencies with: pip install -r requirements.txt") from exc

    host = os.getenv("API_HOST", "127.0.0.1")
    port = int(os.getenv("API_PORT", "8000"))
    migrations_enabled = parse_bool(os.getenv("API_RUN_MIGRATIONS_ON_STARTUP"), default=True)
    print(f"Starting Morning Alpha API on http://{host}:{port} (startup migrations: {migrations_enabled})")
    uvicorn.run(app, host=host, port=port)
