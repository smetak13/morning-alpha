from __future__ import annotations

import os
import json
import datetime as dt
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
    include_in_report: bool = True
    why_i_own_it: list[str] = Field(default_factory=list)
    bull_case: list[str] = Field(default_factory=list)
    bear_case: list[str] = Field(default_factory=list)
    key_metrics: list[str] = Field(default_factory=list)
    red_flags: list[str] = Field(default_factory=list)
    action_triggers: list[str] = Field(default_factory=list)


class PortfolioItemUpdateRequest(BaseModel):
    position_size_pct: float | None = None
    include_in_report: bool | None = None
    why_i_own_it: list[str] | None = None
    bull_case: list[str] | None = None
    bear_case: list[str] | None = None
    key_metrics: list[str] | None = None
    red_flags: list[str] | None = None
    action_triggers: list[str] | None = None


class WatchlistItemCreateRequest(BaseModel):
    symbol: str
    company_name: str
    include_in_report: bool = True
    why_i_watch_it: list[str] = Field(default_factory=list)
    bull_case: list[str] = Field(default_factory=list)
    bear_case: list[str] = Field(default_factory=list)
    key_metrics: list[str] = Field(default_factory=list)
    red_flags: list[str] = Field(default_factory=list)
    entry_conditions: list[str] = Field(default_factory=list)


class WatchlistItemUpdateRequest(BaseModel):
    include_in_report: bool | None = None
    why_i_watch_it: list[str] | None = None
    bull_case: list[str] | None = None
    bear_case: list[str] | None = None
    key_metrics: list[str] | None = None
    red_flags: list[str] | None = None
    entry_conditions: list[str] | None = None


class UserSettingsUpdateRequest(BaseModel):
    report_scheduled_at: str | None = None
    timezone: str | None = None


class NoteCreateRequest(BaseModel):
    stock_id: str
    report_id: str | None = None
    research_item_id: str | None = None
    body: str
    is_resolved: bool = False


class NoteUpdateRequest(BaseModel):
    body: str | None = None
    is_resolved: bool | None = None


class CompanyResearchRequest(BaseModel):
    symbol: str
    company_name: str | None = None
    date_from: str | None = None
    date_to: str | None = None


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


def validate_timezone(value: str | None) -> str:
    timezone = (value or "").strip()
    if not timezone:
        raise HTTPException(status_code=422, detail="Timezone is required.")
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError:
        raise HTTPException(status_code=422, detail="Invalid timezone.")
    return timezone


def parse_report_scheduled_at(value: str | None) -> dt.time:
    scheduled_at = (value or "").strip()
    if not scheduled_at:
        raise HTTPException(status_code=422, detail="Report time is required.")
    try:
        parsed = dt.time.fromisoformat(scheduled_at)
    except ValueError:
        raise HTTPException(status_code=422, detail="Report time must use HH:MM format.")
    if parsed.tzinfo is not None:
        raise HTTPException(status_code=422, detail="Report time must not include a timezone.")
    return dt.time(hour=parsed.hour, minute=parsed.minute)


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


@app.put("/api/user/settings")
def update_user_settings(payload: UserSettingsUpdateRequest, request: Request) -> dict[str, Any]:
    user_id = current_user_id(request)
    from psycopg.rows import dict_row

    updates = payload.model_dump(exclude_unset=True)
    set_clauses: list[str] = []
    params: dict[str, Any] = {"id": user_id}

    if "report_scheduled_at" in updates and updates["report_scheduled_at"] is not None:
        params["report_scheduled_at"] = parse_report_scheduled_at(updates["report_scheduled_at"])
        set_clauses.append("report_scheduled_at = %(report_scheduled_at)s")
    if "timezone" in updates and updates["timezone"] is not None:
        params["timezone"] = validate_timezone(updates["timezone"])
        set_clauses.append("timezone = %(timezone)s")

    if not set_clauses:
        profile = get_user_profile(user_id)
        if not profile:
            raise HTTPException(status_code=404, detail="User profile not found.")
        return {"user": profile}

    with connection(row_factory=dict_row) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                update public.users
                set {", ".join(set_clauses)}
                where id = %(id)s
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

    if not row:
        raise HTTPException(status_code=404, detail="User profile not found.")
    return {"user": dict(row)}


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
    results_by_listing: dict[str, StockSearchResult] = {}
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
                listing_key = f"{result.symbol}:{result.exchange or ''}"
                results_by_listing.setdefault(listing_key, result)

    return {"results": [result.model_dump() for result in list(results_by_listing.values())[:12]]}


def draft_thesis_schema(item_type: str) -> dict[str, Any]:
    first_field = "why_i_own_it" if item_type == "portfolio" else "why_i_watch_it"
    schema = {
        first_field: ["string"],
        "bull_case": ["string"],
        "bear_case": ["string"],
        "key_metrics": ["string"],
        "red_flags": ["string"],
    }
    schema["action_triggers" if item_type == "portfolio" else "entry_conditions"] = ["string"]
    return schema


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
    user_id = current_user_id(request)
    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY is not configured.")

    from openai import OpenAI
    from report import load_yaml, log_openai_usage, openai_usage_summary, parse_model_json

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
            "entry_conditions": "3 concise pieces of evidence that would make this watchlist company more attractive as a portfolio candidate",
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
        usage = openai_usage_summary(response, model, config)
        log_openai_usage(user_id, f"{payload.item_type}_draft", usage)
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
        "include_in_report": bool(row["include_in_report"]),
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
        "include_in_report": bool(row["include_in_report"]),
        "why_i_watch_it": row["why_i_watch_it"] or [],
        "bull_case": row["bull_case"] or [],
        "bear_case": row["bear_case"] or [],
        "key_metrics": row["key_metrics"] or [],
        "red_flags": row["red_flags"] or [],
        "entry_conditions": row["entry_conditions"] or [],
    }


PORTFOLIO_SELECT = """
    select
        portfolio_items.id::text as id,
        portfolio_items.stock_id::text as stock_id,
        stocks.symbol,
        stocks.company_name,
        portfolio_items.position_size_pct,
        portfolio_items.include_in_report,
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
        watchlist_items.include_in_report,
        watchlist_items.why_i_watch_it,
        watchlist_items.bull_case,
        watchlist_items.bear_case,
        watchlist_items.key_metrics,
        watchlist_items.red_flags,
        watchlist_items.entry_conditions
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
                    include_in_report,
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
                    %(include_in_report)s,
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
                    "include_in_report": payload.include_in_report,
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
            include_in_report = current_dict["include_in_report"]
            if "include_in_report" in updates and updates["include_in_report"] is not None:
                include_in_report = updates["include_in_report"]
            params = {
                "id": item_id,
                "user_id": user_id,
                "position_size_pct": position,
                "include_in_report": include_in_report,
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
                    include_in_report = %(include_in_report)s,
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
                    include_in_report,
                    why_i_watch_it,
                    bull_case,
                    bear_case,
                    key_metrics,
                    red_flags,
                    entry_conditions
                )
                values (
                    %(user_id)s,
                    %(stock_id)s,
                    %(include_in_report)s,
                    %(why_i_watch_it)s,
                    %(bull_case)s,
                    %(bear_case)s,
                    %(key_metrics)s,
                    %(red_flags)s,
                    %(entry_conditions)s
                )
                on conflict (user_id, stock_id) do nothing
                returning id::text
                """,
                {
                    "user_id": user_id,
                    "stock_id": stock_id,
                    "include_in_report": payload.include_in_report,
                    "why_i_watch_it": clean_bullets(payload.why_i_watch_it),
                    "bull_case": clean_bullets(payload.bull_case),
                    "bear_case": clean_bullets(payload.bear_case),
                    "key_metrics": clean_bullets(payload.key_metrics),
                    "red_flags": clean_bullets(payload.red_flags),
                    "entry_conditions": clean_bullets(payload.entry_conditions),
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
            include_in_report = current_dict["include_in_report"]
            if "include_in_report" in updates and updates["include_in_report"] is not None:
                include_in_report = updates["include_in_report"]
            params = {
                "id": item_id,
                "user_id": user_id,
                "include_in_report": include_in_report,
                "why_i_watch_it": clean_bullets(updates.get("why_i_watch_it", current_dict["why_i_watch_it"])),
                "bull_case": clean_bullets(updates.get("bull_case", current_dict["bull_case"])),
                "bear_case": clean_bullets(updates.get("bear_case", current_dict["bear_case"])),
                "key_metrics": clean_bullets(updates.get("key_metrics", current_dict["key_metrics"])),
                "red_flags": clean_bullets(updates.get("red_flags", current_dict["red_flags"])),
                "entry_conditions": clean_bullets(updates.get("entry_conditions", current_dict["entry_conditions"])),
            }
            cursor.execute(
                """
                update public.watchlist_items
                set
                    include_in_report = %(include_in_report)s,
                    why_i_watch_it = %(why_i_watch_it)s,
                    bull_case = %(bull_case)s,
                    bear_case = %(bear_case)s,
                    key_metrics = %(key_metrics)s,
                    red_flags = %(red_flags)s,
                    entry_conditions = %(entry_conditions)s
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


def try_fmp_get(client: Any, endpoint: str, params: dict[str, Any]) -> Any:
    try:
        return client.get(endpoint, params)
    except Exception:
        return None


def first_item(data: Any) -> dict[str, Any]:
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data[0]
    if isinstance(data, dict):
        return data
    return {}


def compact_fmp_item(item: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    return {key: item.get(key) for key in keys if item.get(key) not in (None, "", [])}


def compact_news_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": item.get("title") or item.get("headline") or "",
        "published_at": item.get("publishedDate") or item.get("date") or item.get("published_at") or "",
        "source": item.get("site") or item.get("publisher") or item.get("source") or "",
        "url": item.get("url") or item.get("link") or "",
        "text": str(item.get("text") or item.get("summary") or item.get("content") or "")[:700],
    }


def is_blocked_research_source(item: dict[str, Any]) -> bool:
    source = str(item.get("site") or item.get("publisher") or item.get("source") or "").lower().replace(" ", "")
    url = str(item.get("url") or item.get("link") or "").lower()
    return "seekingalpha" in source or "seekingalpha.com" in url


def fmp_items(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict):
        items = data.get("historical") or data.get("historicalStockList") or data.get("data") or []
    elif isinstance(data, list):
        items = data
    else:
        return []
    return [item for item in items if isinstance(item, dict)]


def normalize_price_history(data: Any, *, include_time: bool = False) -> list[dict[str, Any]]:
    items = fmp_items(data)
    if not items and isinstance(data, dict) and data:
        items = [data]
    points = []
    for item in items:
        if not isinstance(item, dict):
            continue
        date_value = item.get("date")
        close = item.get("close") or item.get("adjClose") or item.get("price")
        if not date_value or close in (None, ""):
            continue
        try:
            point_date = str(date_value) if include_time else str(date_value)[:10]
            points.append({"date": point_date, "close": float(close)})
        except (TypeError, ValueError):
            continue
    return sorted(points, key=lambda point: point["date"])


def fetch_price_history(client: Any, symbol: str, end: dt.date) -> list[dict[str, Any]]:
    start = end - dt.timedelta(days=365 * 5 + 10)
    for endpoint, params in (
        ("historical-price-eod/full", {"symbol": symbol, "from": start.isoformat(), "to": end.isoformat()}),
        (f"historical-price-full/{symbol}", {"from": start.isoformat(), "to": end.isoformat()}),
        ("historical-price-eod/light", {"symbol": symbol, "from": start.isoformat(), "to": end.isoformat()}),
    ):
        data = try_fmp_get(client, endpoint, params)
        points = normalize_price_history(data)
        if points:
            return points[-1300:]
    return []


def fetch_intraday_history(client: Any, symbol: str) -> list[dict[str, Any]]:
    for endpoint in (f"historical-chart/5min/{symbol}", f"historical-chart/15min/{symbol}", f"historical-chart/1hour/{symbol}"):
        points = normalize_price_history(try_fmp_get(client, endpoint, {}), include_time=True)
        if points:
            return points[-120:]
    return []


def fetch_first_available(client: Any, candidates: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    for endpoint, params in candidates:
        item = first_item(try_fmp_get(client, endpoint, params))
        if item:
            return item
    return {}


def parse_fmp_date(value: Any) -> dt.date | None:
    if not value:
        return None
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def fetch_latest_actual_earnings(client: Any, symbol: str, today: dt.date) -> dict[str, Any]:
    for endpoint, params in (
        ("earnings", {"symbol": symbol, "limit": 12}),
        ("historical/earning_calendar", {"symbol": symbol, "limit": 12}),
        ("earnings-calendar", {"symbol": symbol, "limit": 12}),
    ):
        rows = fmp_items(try_fmp_get(client, endpoint, params))
        actual_rows = [
            row
            for row in rows
            if (parse_fmp_date(row.get("date") or row.get("fiscalDateEnding")) or today) <= today
        ]
        if actual_rows:
            return sorted(actual_rows, key=lambda row: str(row.get("date") or row.get("fiscalDateEnding") or ""), reverse=True)[0]
    return {}


def percent_growth(newer: Any, older: Any) -> float | None:
    try:
        newer_value = float(newer)
        older_value = float(older)
    except (TypeError, ValueError):
        return None
    if older_value == 0:
        return None
    return ((newer_value / older_value) - 1) * 100


def safe_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def first_number(*values: Any) -> float | None:
    for value in values:
        number = safe_float(value)
        if number is not None:
            return number
    return None


def divide_or_none(numerator: Any, denominator: Any) -> float | None:
    numerator_value = safe_float(numerator)
    denominator_value = safe_float(denominator)
    if numerator_value is None or denominator_value in (None, 0):
        return None
    return numerator_value / denominator_value


def calculate_eps_growth(income_rows: Any, years: int) -> float | None:
    if not isinstance(income_rows, list) or len(income_rows) <= years:
        return None
    latest = income_rows[0].get("eps") or income_rows[0].get("epsdiluted")
    previous = income_rows[years].get("eps") or income_rows[years].get("epsdiluted")
    return percent_growth(latest, previous)


def calculate_statement_growth(income_rows: Any, field: str, years: int) -> float | None:
    if not isinstance(income_rows, list) or len(income_rows) <= years:
        return None
    return percent_growth(income_rows[0].get(field), income_rows[years].get(field))


def ratio_to_percent(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number * 100 if abs(number) <= 1 else number


def research_market_data(
    *,
    symbol: str,
    quote: dict[str, Any],
    metrics: dict[str, Any],
    metrics_latest: dict[str, Any],
    ratios: dict[str, Any],
    ratios_latest: dict[str, Any],
    income_rows: Any,
    income_ttm: dict[str, Any],
    balance_ttm: dict[str, Any],
    cashflow_ttm: dict[str, Any],
    analyst_estimate: dict[str, Any],
    earnings: dict[str, Any],
    price_history: list[dict[str, Any]],
    intraday_history: list[dict[str, Any]],
) -> dict[str, Any]:
    next_eps = (
        analyst_estimate.get("estimatedEpsAvg")
        or analyst_estimate.get("estimatedEpsHigh")
        or analyst_estimate.get("epsEstimated")
    )
    price = first_number(quote.get("price"))
    market_cap = first_number(quote.get("marketCap"), metrics_latest.get("marketCap"))
    latest_income = first_item(income_rows)
    shares = first_number(
        quote.get("sharesOutstanding"),
        income_ttm.get("weightedAverageShsOutDil"),
        income_ttm.get("weightedAverageShsOut"),
        latest_income.get("weightedAverageShsOutDil"),
        latest_income.get("weightedAverageShsOut"),
    )
    revenue = first_number(income_ttm.get("revenue"), latest_income.get("revenue"))
    net_income = first_number(income_ttm.get("netIncome"), latest_income.get("netIncome"))
    ebitda = first_number(income_ttm.get("ebitda"), latest_income.get("ebitda"))
    equity = first_number(
        balance_ttm.get("totalStockholdersEquity"),
        balance_ttm.get("totalEquity"),
        balance_ttm.get("totalShareholderEquity"),
    )
    short_term_debt = safe_float(balance_ttm.get("shortTermDebt"))
    long_term_debt = safe_float(balance_ttm.get("longTermDebt"))
    total_debt = first_number(
        balance_ttm.get("totalDebt"),
        short_term_debt + long_term_debt if short_term_debt is not None and long_term_debt is not None else None,
    )
    operating_cash_flow = first_number(cashflow_ttm.get("operatingCashFlow"), cashflow_ttm.get("netCashProvidedByOperatingActivities"))
    capex = first_number(cashflow_ttm.get("capitalExpenditure"), cashflow_ttm.get("capitalExpenditures"))
    free_cash_flow = first_number(cashflow_ttm.get("freeCashFlow"))
    if free_cash_flow is None and operating_cash_flow is not None and capex is not None:
        free_cash_flow = operating_cash_flow - abs(capex)

    latest_eps = first_number(
        quote.get("eps"),
        metrics.get("netIncomePerShareTTM"),
        income_ttm.get("eps"),
        income_ttm.get("epsdiluted"),
        latest_income.get("eps"),
        latest_income.get("epsdiluted"),
        divide_or_none(net_income, shares),
    )
    pe = first_number(
        quote.get("pe"),
        metrics.get("peRatioTTM"),
        metrics.get("priceEarningsRatioTTM"),
        metrics_latest.get("peRatio"),
        ratios.get("priceEarningsRatioTTM"),
        ratios_latest.get("priceEarningsRatio"),
    )
    if pe is None and price is not None and latest_eps not in (None, 0):
        pe = price / latest_eps

    revenue_per_share = first_number(metrics.get("revenuePerShareTTM"), divide_or_none(revenue, shares))
    fcf_per_share = first_number(metrics.get("freeCashFlowPerShareTTM"), divide_or_none(free_cash_flow, shares))
    ps = first_number(metrics.get("priceToSalesRatioTTM"), ratios.get("priceToSalesRatioTTM"), divide_or_none(price, revenue_per_share))
    fcf_yield = ratio_to_percent(metrics.get("freeCashFlowYieldTTM") or ratios.get("freeCashFlowYieldTTM"))
    if fcf_yield is None and free_cash_flow is not None and market_cap not in (None, 0):
        fcf_yield = (free_cash_flow / market_cap) * 100
    roe = ratio_to_percent(ratios.get("returnOnEquityTTM") or metrics.get("roeTTM") or ratios_latest.get("returnOnEquity"))
    if roe is None and net_income is not None and equity not in (None, 0):
        roe = (net_income / equity) * 100
    debt_to_equity = first_number(
        metrics.get("debtToEquityTTM"),
        ratios.get("debtEquityRatioTTM"),
        ratios_latest.get("debtEquityRatio"),
        divide_or_none(total_debt, equity),
    )

    return {
        "price_history": price_history,
        "intraday_history": intraday_history,
        "metrics": {
            "price": price,
            "market_cap": market_cap,
            "pe": pe,
            "ps": ps,
            "ev_to_ebitda": first_number(
                metrics.get("enterpriseValueOverEBITDATTM"),
                ratios.get("enterpriseValueOverEBITDATTM"),
                ratios.get("enterpriseValueMultipleTTM"),
                divide_or_none(metrics_latest.get("enterpriseValue"), ebitda),
            ),
            "fcf_yield_pct": fcf_yield,
            "eps": latest_eps,
            "eps_growth_3y_pct": calculate_eps_growth(income_rows, 3),
            "eps_growth_5y_pct": calculate_eps_growth(income_rows, 5),
            "revenue_growth_3y_pct": calculate_statement_growth(income_rows, "revenue", 3),
            "eps_growth_next_year_pct": percent_growth(next_eps, latest_eps),
            "revenue_per_share": revenue_per_share,
            "fcf_per_share": fcf_per_share,
            "gross_margin_pct": ratio_to_percent(ratios.get("grossProfitMarginTTM")),
            "operating_margin_pct": ratio_to_percent(ratios.get("operatingProfitMarginTTM")),
            "net_margin_pct": ratio_to_percent(ratios.get("netProfitMarginTTM")),
            "roe_pct": roe,
            "debt_to_equity": debt_to_equity,
            "year_high": first_number(quote.get("yearHigh")),
            "year_low": first_number(quote.get("yearLow")),
        },
        "latest_earnings": {
            "date": earnings.get("date") or earnings.get("fiscalDateEnding"),
            "eps": earnings.get("eps") or earnings.get("epsActual"),
            "eps_estimated": earnings.get("epsEstimated") or earnings.get("epsEstimate"),
            "revenue": earnings.get("revenue"),
            "revenue_estimated": earnings.get("revenueEstimated"),
            "source_url": earnings.get("url") or earnings.get("link") or earnings.get("finalLink"),
        }
        if earnings
        else None,
    }


def research_stock_context(cursor: Any, user_id: str, symbol: str) -> tuple[str, dict[str, Any] | None]:
    cursor.execute(
        PORTFOLIO_SELECT
        + """
        where portfolio_items.user_id = %(user_id)s
          and upper(stocks.symbol) = %(symbol)s
        """,
        {"user_id": user_id, "symbol": symbol},
    )
    portfolio_row = cursor.fetchone()
    if portfolio_row:
        return "portfolio", serialize_portfolio_row(dict(portfolio_row))

    cursor.execute(
        WATCHLIST_SELECT
        + """
        where watchlist_items.user_id = %(user_id)s
          and upper(stocks.symbol) = %(symbol)s
        """,
        {"user_id": user_id, "symbol": symbol},
    )
    watchlist_row = cursor.fetchone()
    if watchlist_row:
        return "watchlist", serialize_watchlist_row(dict(watchlist_row))

    return "new", None


def research_schema(mode: str) -> dict[str, Any]:
    if mode == "portfolio":
        return {
            "mode": "portfolio",
            "signal": "thesis_supported | thesis_needs_review | red_flag_rising | no_material_change",
            "executive_summary": ["string"],
            "thesis_check": [{"field": "string", "assessment": "string", "evidence": [{"text": "string", "source_url": "string"}]}],
            "recent_developments": [{"headline": "string", "summary": "string", "source_url": "string"}],
            "risks_to_watch": ["string"],
            "suggested_next_steps": ["string"],
        }
    if mode == "watchlist":
        return {
            "mode": "watchlist",
            "signal": "positive_signal | negative_signal | mixed_signal | needs_more_evidence | no_material_change",
            "executive_summary": ["string"],
            "entry_conditions_check": [{"condition": "string", "assessment": "string", "evidence": [{"text": "string", "source_url": "string"}]}],
            "recent_developments": [{"headline": "string", "summary": "string", "source_url": "string"}],
            "still_missing": ["string"],
            "suggested_next_steps": ["string"],
        }
    return {
        "mode": "new",
        "watchlist_suitability": "potential_watchlist_candidate | worth_researching_further | too_early | low_relevance",
        "company_overview": ["string"],
        "business_model": ["string"],
        "products_and_customers": ["string"],
        "current_situation": ["string"],
        "future_outlook": ["string"],
        "bull_case": ["string"],
        "bear_case": ["string"],
        "what_to_understand_next": ["string"],
    }


def normalize_research_payload(payload: dict[str, Any], mode: str) -> dict[str, Any]:
    schema = research_schema(mode)
    normalized: dict[str, Any] = {"mode": mode}
    for key, fallback in schema.items():
        if key == "mode":
            continue
        value = payload.get(key)
        if isinstance(fallback, list):
            normalized[key] = value if isinstance(value, list) else []
        elif isinstance(value, str):
            normalized[key] = value.strip()
        else:
            normalized[key] = ""
    return normalized


@app.post("/api/research/company")
def research_company(payload: CompanyResearchRequest, request: Request) -> dict[str, Any]:
    user_id = current_user_id(request)
    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY is not configured.")

    from openai import OpenAI
    from psycopg.rows import dict_row
    from report import load_yaml, log_openai_usage, openai_usage_summary, parse_model_json

    symbol = clean_symbol(payload.symbol)
    company_name = (payload.company_name or symbol).strip() or symbol
    date_to = parse_report_date_filter(payload.date_to, "date_to") or dt.date.today()
    date_from = parse_report_date_filter(payload.date_from, "date_from") or (date_to - dt.timedelta(days=30))
    if date_from > date_to:
        raise HTTPException(status_code=422, detail="date_from must be before date_to.")

    with connection(row_factory=dict_row) as conn:
        with conn.cursor() as cursor:
            relationship, item = research_stock_context(cursor, user_id, symbol)

    client = fmp_client_from_env()
    profile = first_item(try_fmp_get(client, "profile", {"symbol": symbol}))
    quote = first_item(try_fmp_get(client, "quote", {"symbol": symbol}))
    metrics = first_item(try_fmp_get(client, "key-metrics-ttm", {"symbol": symbol}))
    metrics_latest = first_item(try_fmp_get(client, "key-metrics", {"symbol": symbol, "period": "annual", "limit": 1}))
    ratios = first_item(try_fmp_get(client, "ratios-ttm", {"symbol": symbol}))
    ratios_latest = first_item(try_fmp_get(client, "ratios", {"symbol": symbol, "period": "annual", "limit": 1}))
    income_ttm = first_item(try_fmp_get(client, "income-statement-ttm", {"symbol": symbol}))
    balance_ttm = first_item(try_fmp_get(client, "balance-sheet-statement-ttm", {"symbol": symbol}))
    cashflow_ttm = first_item(try_fmp_get(client, "cash-flow-statement-ttm", {"symbol": symbol}))
    income_rows = try_fmp_get(client, "income-statement", {"symbol": symbol, "period": "annual", "limit": 6})
    income = first_item(income_rows)
    analyst_estimate = fetch_first_available(
        client,
        [
            ("analyst-estimates", {"symbol": symbol, "period": "annual", "limit": 2}),
            ("analyst-estimates", {"symbol": symbol, "limit": 2}),
        ],
    )
    earnings = fetch_latest_actual_earnings(client, symbol, dt.date.today())
    price_history = fetch_price_history(client, symbol, date_to)
    intraday_history = fetch_intraday_history(client, symbol)
    news: list[dict[str, Any]] = []
    if relationship in {"portfolio", "watchlist"}:
        try:
            news = client.stock_news([symbol], start=date_from, end=date_to, limit=20)
            news = [item for item in news if not is_blocked_research_source(item)]
        except Exception:
            news = []

    config = load_yaml(ROOT / "config.yaml")
    model = config.get("openai", {}).get("model", "gpt-4.1-mini")
    task = {
        "portfolio": "research_portfolio_check",
        "watchlist": "research_watchlist_check",
        "new": "research_company_primer",
    }[relationship]
    context = {
        "company": {
            "symbol": symbol,
            "company_name": company_name,
            "relationship": relationship,
        },
        "date_window": {"from": date_from.isoformat(), "to": date_to.isoformat()} if relationship != "new" else None,
        "user_item": item,
        "fmp": {
            "profile": compact_fmp_item(
                profile,
                [
                    "companyName",
                    "description",
                    "sector",
                    "industry",
                    "ceo",
                    "country",
                    "website",
                    "fullTimeEmployees",
                    "marketCap",
                ],
            ),
            "quote": compact_fmp_item(
                quote,
                ["price", "changesPercentage", "marketCap", "eps", "pe", "sharesOutstanding", "yearHigh", "yearLow"],
            ),
            "metrics_ttm": compact_fmp_item(
                metrics,
                ["revenuePerShareTTM", "netIncomePerShareTTM", "freeCashFlowPerShareTTM", "debtToEquityTTM", "roeTTM"],
            ),
            "ratios_ttm": compact_fmp_item(
                ratios,
                ["grossProfitMarginTTM", "operatingProfitMarginTTM", "netProfitMarginTTM", "returnOnEquityTTM"],
            ),
            "latest_income_statement": compact_fmp_item(
                income,
                ["date", "revenue", "grossProfit", "operatingIncome", "netIncome", "eps", "ebitda"],
            ),
            "news": [compact_news_item(item) for item in news[:8]],
        },
        "required_json_schema": research_schema(relationship),
    }
    market_data = research_market_data(
        symbol=symbol,
        quote=quote,
        metrics=metrics,
        metrics_latest=metrics_latest,
        ratios=ratios,
        ratios_latest=ratios_latest,
        income_rows=income_rows,
        income_ttm=income_ttm,
        balance_ttm=balance_ttm,
        cashflow_ttm=cashflow_ttm,
        analyst_estimate=analyst_estimate,
        earnings=earnings,
        price_history=price_history,
        intraday_history=intraday_history,
    )
    if relationship == "new":
        instructions = (
            "Create a deep but concise company primer for a long-term investor who does not yet own or watch this company. "
            "Focus on what the company actually does, how it makes money, product lines, customer/end-market exposure, competitive position, current situation, future outlook, bull case, bear case, and what to learn next. "
            "Do not make a buy/sell/hold recommendation. Do not over-focus on generic valuation metrics. Use supplied data only; if something is unknown, say what should be verified."
        )
    elif relationship == "portfolio":
        instructions = (
            "Test the user's existing portfolio thesis against recent company-specific news and supplied data. "
            "Focus only on information relevant to why the user owns it, bull/bear case, key metrics, red flags, and action triggers. "
            "Summarize only a few material articles and include their source_url. When citing an article, use source_url fields; do not put source domains in parentheses inside the prose. Do not recommend buying, selling, or holding."
        )
    else:
        instructions = (
            "Check whether recent company-specific news and supplied data support or contradict the user's watchlist thesis and entry_conditions. "
            "Explain whether the company is moving closer to the user's entry conditions, what evidence is still missing, and summarize only material articles with source_url. When citing an article, use source_url fields; do not put source domains in parentheses inside the prose. "
            "Do not recommend buying, selling, or holding."
        )

    try:
        response = OpenAI(timeout=60).responses.create(
            model=model,
            input=[
                {
                    "role": "system",
                    "content": "You produce structured, evidence-based investment research JSON. Be specific, concise, neutral, and avoid recommendations.",
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "instructions": instructions,
                            "constraints": [
                                "Return valid JSON only.",
                                "Keep each bullet specific and useful; avoid generic filler.",
                                "Prefer 3-5 bullets per list.",
                                "Use only the supplied context and mark uncertainty clearly.",
                                "No buy/sell/hold recommendation and no personalized financial advice.",
                            ],
                            "context": context,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
        )
        usage = openai_usage_summary(response, model, config)
        log_openai_usage(user_id, task, usage)
        research = normalize_research_payload(parse_model_json(response.output_text), relationship)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Research generation failed: {exc}") from exc

    response_payload = {
        "mode": relationship,
        "stock": {
            "symbol": symbol,
            "company_name": profile.get("companyName") or company_name,
            "stock_id": item.get("stock_id") if item else None,
            "logo_url": stock_logo_url(symbol),
        },
        "date_window": context["date_window"],
        "market_data": market_data,
        "research": research,
    }
    from psycopg.types.json import Json

    with connection(row_factory=dict_row) as conn:
        with conn.cursor() as cursor:
            stock_id = item.get("stock_id") if item else get_or_create_stock(cursor, symbol, response_payload["stock"]["company_name"])
            response_payload["stock"]["stock_id"] = stock_id
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
                    %(research_type)s,
                    %(signal)s,
                    %(date_from)s,
                    %(date_to)s
                )
                returning id::text
                """,
                {
                    "user_id": user_id,
                    "stock_id": stock_id,
                    "body": Json(response_payload),
                    "research_type": research_type_for_mode(relationship),
                    "signal": research_signal_from_body(response_payload),
                    "date_from": date_from if relationship != "new" else None,
                    "date_to": date_to if relationship != "new" else None,
                },
            )
            inserted = cursor.fetchone()
            response_payload["research_item_id"] = inserted["id"]

    return response_payload


def parse_report_date_filter(value: str | None, field_name: str) -> dt.date | None:
    if not value:
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"{field_name} must use YYYY-MM-DD format.")


def serialize_report_row(row: dict[str, Any], include_html: bool = False) -> dict[str, Any]:
    payload = {
        "id": str(row["id"]),
        "report_date": row["report_date"].isoformat() if hasattr(row["report_date"], "isoformat") else row["report_date"],
        "created_at": row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else row["created_at"],
        "usage_id": str(row["usage_id"]) if row.get("usage_id") else None,
        "note_count": int(row.get("note_count") or 0),
    }
    if include_html:
        payload["html"] = row["html"]
    return payload


def research_type_for_mode(mode: str) -> str:
    return {
        "portfolio": "portfolio_check",
        "watchlist": "watchlist_check",
        "new": "company_primer",
    }[mode]


def research_signal_from_body(body: dict[str, Any]) -> str | None:
    research = body.get("research") if isinstance(body, dict) else None
    if not isinstance(research, dict):
        return None
    return research.get("signal") or research.get("watchlist_suitability")


def serialize_research_item_row(row: dict[str, Any], include_body: bool = False) -> dict[str, Any]:
    symbol = str(row["symbol"]).upper()
    body = row.get("body") if isinstance(row.get("body"), dict) else None
    payload = {
        "id": str(row["id"]),
        "stock_id": str(row["stock_id"]),
        "symbol": symbol,
        "company_name": row["company_name"],
        "logo_url": stock_logo_url(symbol),
        "research_type": row["research_type"],
        "signal": row.get("signal"),
        "date_from": row["date_from"].isoformat() if row.get("date_from") and hasattr(row["date_from"], "isoformat") else row.get("date_from"),
        "date_to": row["date_to"].isoformat() if row.get("date_to") and hasattr(row["date_to"], "isoformat") else row.get("date_to"),
        "created_at": row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else row["created_at"],
        "note_count": int(row.get("note_count") or 0),
    }
    if include_body:
        payload["body"] = body or row.get("body")
    return payload


@app.get("/api/reports")
def list_reports(
    request: Request,
    date_from: str | None = None,
    date_to: str | None = None,
    page: int = 1,
    page_size: int = 10,
) -> dict[str, Any]:
    user_id = current_user_id(request)
    from psycopg.rows import dict_row

    today = dt.date.today()
    parsed_date_from = parse_report_date_filter(date_from, "date_from") or (today - dt.timedelta(days=6))
    parsed_date_to = parse_report_date_filter(date_to, "date_to") or today
    page = max(page, 1)
    page_size = min(max(page_size, 1), 50)
    offset = (page - 1) * page_size

    with connection(row_factory=dict_row) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                select count(*) as total
                from public.reports
                where user_id = %(user_id)s
                  and report_date >= %(date_from)s
                  and report_date <= %(date_to)s
                """,
                {"user_id": user_id, "date_from": parsed_date_from, "date_to": parsed_date_to},
            )
            total = int(cursor.fetchone()["total"] or 0)
            cursor.execute(
                """
                select
                    reports.id::text as id,
                    reports.usage_id::text as usage_id,
                    reports.report_date,
                    reports.created_at,
                    count(notes.id)::int as note_count
                from public.reports
                left join public.notes
                  on notes.report_id = reports.id
                 and notes.user_id = reports.user_id
                where reports.user_id = %(user_id)s
                  and reports.report_date >= %(date_from)s
                  and reports.report_date <= %(date_to)s
                group by reports.id
                order by reports.report_date desc, reports.created_at desc
                limit %(page_size)s
                offset %(offset)s
                """,
                {
                    "user_id": user_id,
                    "date_from": parsed_date_from,
                    "date_to": parsed_date_to,
                    "page_size": page_size,
                    "offset": offset,
                },
            )
            rows = cursor.fetchall()

    return {
        "items": [serialize_report_row(dict(row)) for row in rows],
        "page": page,
        "page_size": page_size,
        "total": total,
        "date_from": parsed_date_from.isoformat(),
        "date_to": parsed_date_to.isoformat(),
    }


@app.get("/api/reports/{report_id}")
def get_report(report_id: str, request: Request) -> dict[str, Any]:
    user_id = current_user_id(request)
    from psycopg.rows import dict_row

    with connection(row_factory=dict_row) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                select
                    id::text as id,
                    usage_id::text as usage_id,
                    report_date,
                    created_at,
                    html
                from public.reports
                where id::text = %(id)s
                  and user_id = %(user_id)s
                """,
                {"id": report_id, "user_id": user_id},
            )
            row = cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Report not found.")
    return {"report": serialize_report_row(dict(row), include_html=True)}


RESEARCH_ITEM_SELECT = """
    select
        research_items.id::text as id,
        research_items.stock_id::text as stock_id,
        research_items.body,
        research_items.research_type,
        research_items.signal,
        research_items.date_from,
        research_items.date_to,
        research_items.created_at,
        stocks.symbol,
        stocks.company_name,
        count(notes.id)::int as note_count
    from public.research_items
    join public.stocks on stocks.id = research_items.stock_id
    left join public.notes
      on notes.research_item_id = research_items.id
     and notes.user_id = research_items.user_id
"""


@app.get("/api/research-items")
def list_research_items(
    request: Request,
    date_from: str | None = None,
    date_to: str | None = None,
    stock_query: str | None = None,
    research_type: str | None = None,
    page: int = 1,
    page_size: int = 10,
) -> dict[str, Any]:
    user_id = current_user_id(request)
    from psycopg.rows import dict_row

    parsed_date_from = parse_report_date_filter(date_from, "date_from")
    parsed_date_to = parse_report_date_filter(date_to, "date_to")
    page = max(page, 1)
    page_size = min(max(page_size, 1), 50)
    offset = (page - 1) * page_size
    where_clauses = ["research_items.user_id = %(user_id)s"]
    params: dict[str, Any] = {"user_id": user_id, "page_size": page_size, "offset": offset}
    if parsed_date_from:
        where_clauses.append("research_items.created_at::date >= %(date_from)s")
        params["date_from"] = parsed_date_from
    if parsed_date_to:
        where_clauses.append("research_items.created_at::date <= %(date_to)s")
        params["date_to"] = parsed_date_to
    if research_type:
        where_clauses.append("research_items.research_type = %(research_type)s")
        params["research_type"] = research_type
    if stock_query and stock_query.strip():
        where_clauses.append("(stocks.symbol ilike %(stock_query)s or stocks.company_name ilike %(stock_query)s)")
        params["stock_query"] = f"%{stock_query.strip()}%"
    where_sql = " and ".join(where_clauses)

    with connection(row_factory=dict_row) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                select count(*) as total
                from public.research_items
                join public.stocks on stocks.id = research_items.stock_id
                where {where_sql}
                """,
                params,
            )
            total = int(cursor.fetchone()["total"] or 0)
            cursor.execute(
                RESEARCH_ITEM_SELECT
                + f"""
                where {where_sql}
                group by research_items.id, stocks.id
                order by research_items.created_at desc
                limit %(page_size)s offset %(offset)s
                """,
                params,
            )
            rows = cursor.fetchall()

    return {
        "items": [serialize_research_item_row(dict(row)) for row in rows],
        "page": page,
        "page_size": page_size,
        "total": total,
    }


@app.get("/api/research-items/{research_item_id}")
def get_research_item(research_item_id: str, request: Request) -> dict[str, Any]:
    user_id = current_user_id(request)
    from psycopg.rows import dict_row

    with connection(row_factory=dict_row) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                RESEARCH_ITEM_SELECT
                + """
                where research_items.id::text = %(id)s
                  and research_items.user_id = %(user_id)s
                group by research_items.id, stocks.id
                """,
                {"id": research_item_id, "user_id": user_id},
            )
            row = cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Research item not found.")
    return {"item": serialize_research_item_row(dict(row), include_body=True)}


@app.delete("/api/research-items/{research_item_id}")
def delete_research_item(research_item_id: str, request: Request) -> dict[str, Any]:
    user_id = current_user_id(request)
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "delete from public.research_items where id::text = %s and user_id = %s",
                (research_item_id, user_id),
            )
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="Research item not found.")
    return {"deleted": True}


def serialize_note_row(row: dict[str, Any]) -> dict[str, Any]:
    symbol = str(row["symbol"]).upper()
    return {
        "id": str(row["id"]),
        "user_id": str(row["user_id"]),
        "stock_id": str(row["stock_id"]),
        "report_id": str(row["report_id"]) if row.get("report_id") else None,
        "research_item_id": str(row["research_item_id"]) if row.get("research_item_id") else None,
        "body": row["body"],
        "is_resolved": bool(row["is_resolved"]),
        "created_at": row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else row["created_at"],
        "updated_at": row["updated_at"].isoformat() if hasattr(row["updated_at"], "isoformat") else row["updated_at"],
        "symbol": symbol,
        "company_name": row["company_name"],
        "logo_url": stock_logo_url(symbol),
        "report_date": row["report_date"].isoformat() if row.get("report_date") and hasattr(row["report_date"], "isoformat") else row.get("report_date"),
        "research_type": row.get("research_type"),
    }


NOTE_SELECT = """
    select
        notes.id::text as id,
        notes.user_id::text as user_id,
        notes.stock_id::text as stock_id,
        notes.report_id::text as report_id,
        notes.research_item_id::text as research_item_id,
        notes.body,
        notes.is_resolved,
        notes.created_at,
        notes.updated_at,
        stocks.symbol,
        stocks.company_name,
        reports.report_date,
        research_items.research_type
    from public.notes
    join public.stocks on stocks.id = notes.stock_id
    left join public.reports on reports.id = notes.report_id
    left join public.research_items on research_items.id = notes.research_item_id
"""


def note_body(value: str | None) -> str:
    body = (value or "").strip()
    if not body:
        raise HTTPException(status_code=422, detail="Note body cannot be empty.")
    return body


def ensure_user_stock(cursor: Any, user_id: str, stock_id: str) -> None:
    cursor.execute(
        """
        select 1
        from public.stocks
        where id::text = %(stock_id)s
          and (
            exists (
                select 1 from public.portfolio_items
                where user_id = %(user_id)s and stock_id = public.stocks.id
            )
            or exists (
                select 1 from public.watchlist_items
                where user_id = %(user_id)s and stock_id = public.stocks.id
            )
          )
        """,
        {"stock_id": stock_id, "user_id": user_id},
    )
    if not cursor.fetchone():
        raise HTTPException(status_code=404, detail="Stock not found in your portfolio or watchlist.")


def ensure_user_report(cursor: Any, user_id: str, report_id: str | None) -> None:
    if not report_id:
        return
    cursor.execute(
        "select 1 from public.reports where id::text = %(report_id)s and user_id = %(user_id)s",
        {"report_id": report_id, "user_id": user_id},
    )
    if not cursor.fetchone():
        raise HTTPException(status_code=404, detail="Report not found.")


def ensure_user_research_item(cursor: Any, user_id: str, research_item_id: str | None, stock_id: str | None = None) -> None:
    if not research_item_id:
        return
    cursor.execute(
        """
        select stock_id::text as stock_id
        from public.research_items
        where id::text = %(research_item_id)s
          and user_id = %(user_id)s
        """,
        {"research_item_id": research_item_id, "user_id": user_id},
    )
    row = cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Research item not found.")
    if stock_id and str(row["stock_id"]) != str(stock_id):
        raise HTTPException(status_code=422, detail="Research note stock must match the research item.")


@app.get("/api/notes/stocks")
def list_note_stocks(request: Request) -> dict[str, Any]:
    user_id = current_user_id(request)
    from psycopg.rows import dict_row

    with connection(row_factory=dict_row) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                select distinct
                    stocks.id::text as stock_id,
                    stocks.symbol,
                    stocks.company_name,
                    case
                        when portfolio_items.id is not null and watchlist_items.id is not null then 'portfolio, watchlist'
                        when portfolio_items.id is not null then 'portfolio'
                        else 'watchlist'
                    end as list_name
                from public.stocks
                left join public.portfolio_items
                  on portfolio_items.stock_id = stocks.id
                 and portfolio_items.user_id = %(user_id)s
                left join public.watchlist_items
                  on watchlist_items.stock_id = stocks.id
                 and watchlist_items.user_id = %(user_id)s
                where portfolio_items.id is not null
                   or watchlist_items.id is not null
                order by stocks.symbol
                """,
                {"user_id": user_id},
            )
            rows = cursor.fetchall()

    items = []
    for row in rows:
        row = dict(row)
        symbol = str(row["symbol"]).upper()
        items.append(
            {
                "stock_id": str(row["stock_id"]),
                "symbol": symbol,
                "company_name": row["company_name"],
                "logo_url": stock_logo_url(symbol),
                "list_name": row["list_name"],
            }
        )
    return {"items": items}


@app.get("/api/notes")
def list_notes(
    request: Request,
    report_id: str | None = None,
    research_item_id: str | None = None,
    stock_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    is_resolved: bool | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    user_id = current_user_id(request)
    from psycopg.rows import dict_row

    parsed_date_from = parse_report_date_filter(date_from, "date_from")
    parsed_date_to = parse_report_date_filter(date_to, "date_to")
    page = max(page, 1)
    page_size = min(max(page_size, 1), 100)
    offset = (page - 1) * page_size
    where_clauses = ["notes.user_id = %(user_id)s"]
    params: dict[str, Any] = {
        "user_id": user_id,
        "limit": page_size,
        "offset": offset,
    }
    if report_id:
        where_clauses.append("notes.report_id::text = %(report_id)s")
        params["report_id"] = report_id
    if research_item_id:
        where_clauses.append("notes.research_item_id::text = %(research_item_id)s")
        params["research_item_id"] = research_item_id
    if stock_id:
        where_clauses.append("notes.stock_id::text = %(stock_id)s")
        params["stock_id"] = stock_id
    if is_resolved is not None:
        where_clauses.append("notes.is_resolved = %(is_resolved)s")
        params["is_resolved"] = is_resolved
    if parsed_date_from:
        where_clauses.append("notes.created_at::date >= %(date_from)s")
        params["date_from"] = parsed_date_from
    if parsed_date_to:
        where_clauses.append("notes.created_at::date <= %(date_to)s")
        params["date_to"] = parsed_date_to
    where_sql = " and ".join(where_clauses)

    with connection(row_factory=dict_row) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"select count(*) as total from public.notes where {where_sql}",
                params,
            )
            total = int(cursor.fetchone()["total"] or 0)
            cursor.execute(
                NOTE_SELECT
                + f"""
                where {where_sql}
                order by notes.created_at desc
                limit %(limit)s offset %(offset)s
                """,
                params,
            )
            rows = cursor.fetchall()

    return {
        "items": [serialize_note_row(dict(row)) for row in rows],
        "page": page,
        "page_size": page_size,
        "total": total,
    }


@app.post("/api/notes")
def create_note(payload: NoteCreateRequest, request: Request) -> dict[str, Any]:
    user_id = current_user_id(request)
    from psycopg.rows import dict_row

    with connection(row_factory=dict_row) as conn:
        with conn.cursor() as cursor:
            if payload.research_item_id:
                ensure_user_research_item(cursor, user_id, payload.research_item_id, payload.stock_id)
            else:
                ensure_user_stock(cursor, user_id, payload.stock_id)
            ensure_user_report(cursor, user_id, payload.report_id)
            cursor.execute(
                """
                insert into public.notes (
                    user_id,
                    stock_id,
                    report_id,
                    research_item_id,
                    body,
                    is_resolved
                )
                values (
                    %(user_id)s,
                    %(stock_id)s,
                    %(report_id)s,
                    %(research_item_id)s,
                    %(body)s,
                    %(is_resolved)s
                )
                returning id::text
                """,
                {
                    "user_id": user_id,
                    "stock_id": payload.stock_id,
                    "report_id": payload.report_id,
                    "research_item_id": payload.research_item_id,
                    "body": note_body(payload.body),
                    "is_resolved": payload.is_resolved,
                },
            )
            inserted = cursor.fetchone()
            cursor.execute(
                NOTE_SELECT + " where notes.id::text = %(id)s and notes.user_id = %(user_id)s",
                {"id": inserted["id"], "user_id": user_id},
            )
            row = cursor.fetchone()

    return {"note": serialize_note_row(dict(row))}


@app.put("/api/notes/{note_id}")
def update_note(note_id: str, payload: NoteUpdateRequest, request: Request) -> dict[str, Any]:
    user_id = current_user_id(request)
    from psycopg.rows import dict_row

    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=422, detail="No note updates provided.")
    set_clauses = []
    params: dict[str, Any] = {"id": note_id, "user_id": user_id}
    if "body" in updates and updates["body"] is not None:
        set_clauses.append("body = %(body)s")
        params["body"] = note_body(updates["body"])
    if "is_resolved" in updates and updates["is_resolved"] is not None:
        set_clauses.append("is_resolved = %(is_resolved)s")
        params["is_resolved"] = updates["is_resolved"]
    if not set_clauses:
        raise HTTPException(status_code=422, detail="No note updates provided.")

    with connection(row_factory=dict_row) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                update public.notes
                set {", ".join(set_clauses)}
                where id::text = %(id)s and user_id = %(user_id)s
                """,
                params,
            )
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="Note not found.")
            cursor.execute(
                NOTE_SELECT + " where notes.id::text = %(id)s and notes.user_id = %(user_id)s",
                {"id": note_id, "user_id": user_id},
            )
            row = cursor.fetchone()

    return {"note": serialize_note_row(dict(row))}


@app.delete("/api/notes/{note_id}")
def delete_note(note_id: str, request: Request) -> dict[str, Any]:
    user_id = current_user_id(request)
    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "delete from public.notes where id::text = %s and user_id = %s",
                (note_id, user_id),
            )
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="Note not found.")
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
