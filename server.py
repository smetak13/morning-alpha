from __future__ import annotations

import os
import json
import html
import datetime as dt
import logging
import re
import sys
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urljoin
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
import requests
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


logger = logging.getLogger("morning_alpha.api")
logger.setLevel(os.getenv("API_LOG_LEVEL", "INFO").upper())
logger.propagate = False
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger.addHandler(handler)


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
    migrations_enabled = parse_bool(os.getenv("API_RUN_MIGRATIONS_ON_STARTUP"), default=True)
    if migrations_enabled:
        started_at = time.perf_counter()
        logger.info("Running startup migrations")
        run_alembic_migrations()
        logger.info("Startup migrations completed duration_ms=%.1f", (time.perf_counter() - started_at) * 1000)
    else:
        logger.info("Startup migrations skipped")
    logger.info("Morning Alpha API startup complete")
    yield
    logger.info("Morning Alpha API shutdown complete")


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


class ThesisQuestionAnswer(BaseModel):
    question_id: str
    answer: str


class DraftThesisRequest(BaseModel):
    item_type: Literal["portfolio", "watchlist"]
    symbol: str
    company_name: str
    mode: Literal["quick", "guided"] = "quick"
    answers: list[ThesisQuestionAnswer] = Field(default_factory=list)


GUIDED_THESIS_QUESTIONS: dict[str, str] = {
    "buy_reason": "Why did you buy this stock?",
    "interest_reason": "Why are you interested in this stock?",
    "needs_to_go_well": "What needs to go well?",
    "could_go_wrong": "What could go wrong?",
    "watch_points": "What numbers or events do you want to watch?",
    "worries": "What would make you worried?",
    "lose_interest": "What would make you lose interest?",
    "sell_or_rethink": "What would make you sell or seriously rethink it?",
    "buy_conditions": "What would make you consider buying it?",
}


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
    report_frequency: Literal["daily", "weekly", "monthly"] | None = None
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
    research_type: Literal["portfolio_check", "watchlist_check", "company_primer", "deep_research"] | None = None


class ShareResearchRequest(BaseModel):
    recipient_email: str
    message: str | None = None


class FeedbackRequest(BaseModel):
    email: str
    category: str
    message: str


def create_app() -> FastAPI:
    app = FastAPI(title="Morning Alpha API", lifespan=lifespan)

    @app.middleware("http")
    async def log_request_response(request: Request, call_next: Any) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        started_at = time.perf_counter()
        client_host = request.client.host if request.client else "-"
        path = request.url.path

        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (time.perf_counter() - started_at) * 1000
            logger.exception(
                "Request failed request_id=%s method=%s path=%s status=500 duration_ms=%.1f client=%s",
                request_id,
                request.method,
                path,
                duration_ms,
                client_host,
            )
            raise

        duration_ms = (time.perf_counter() - started_at) * 1000
        response.headers["x-request-id"] = request_id
        log = logger.warning if response.status_code >= 400 else logger.info
        log(
            "Request completed request_id=%s method=%s path=%s status=%s duration_ms=%.1f client=%s",
            request_id,
            request.method,
            path,
            response.status_code,
            duration_ms,
            client_host,
        )
        return response

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
logger.info("Morning Alpha API app initialized")


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
                    report_frequency,
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
                    report_frequency,
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
    if "report_frequency" in updates and updates["report_frequency"] is not None:
        params["report_frequency"] = updates["report_frequency"]
        set_clauses.append("report_frequency = %(report_frequency)s")

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
                    report_frequency,
                    created_at,
                    updated_at
                """,
                params,
            )
            row = cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="User profile not found.")
    return {"user": dict(row)}


def serialize_notification_row(row: dict[str, Any]) -> dict[str, Any]:
    metadata = row.get("metadata") or {}
    return {
        "id": str(row["id"]),
        "type": row["type"],
        "title": row["title"],
        "body": row.get("body"),
        "target_url": row.get("target_url"),
        "stock_id": str(row["stock_id"]) if row.get("stock_id") else None,
        "portfolio_item_id": str(row["portfolio_item_id"]) if row.get("portfolio_item_id") else None,
        "watchlist_item_id": str(row["watchlist_item_id"]) if row.get("watchlist_item_id") else None,
        "event_date": row["event_date"].isoformat() if row.get("event_date") else None,
        "reminder_kind": row.get("reminder_kind"),
        "read_at": row["read_at"].isoformat() if row.get("read_at") else None,
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
        "expires_at": row["expires_at"].isoformat() if row.get("expires_at") else None,
        "metadata": metadata if isinstance(metadata, dict) else {},
    }


@app.get("/api/notifications")
def list_notifications(request: Request, limit: int = 5) -> dict[str, Any]:
    user_id = current_user_id(request)
    from psycopg.rows import dict_row

    safe_limit = min(max(limit, 1), 20)
    with connection(row_factory=dict_row) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                select count(*) as unread_count
                from public.notifications
                where user_id = %(user_id)s
                  and read_at is null
                  and (expires_at is null or expires_at > now())
                """,
                {"user_id": user_id},
            )
            unread_count = int(cursor.fetchone()["unread_count"] or 0)

            cursor.execute(
                """
                select
                    id::text as id,
                    type,
                    title,
                    body,
                    target_url,
                    stock_id::text as stock_id,
                    portfolio_item_id::text as portfolio_item_id,
                    watchlist_item_id::text as watchlist_item_id,
                    event_date,
                    reminder_kind,
                    read_at,
                    expires_at,
                    metadata,
                    created_at
                from public.notifications
                where user_id = %(user_id)s
                  and (expires_at is null or expires_at > now())
                order by created_at desc
                limit %(limit)s
                """,
                {"user_id": user_id, "limit": safe_limit},
            )
            rows = cursor.fetchall()

    return {
        "items": [serialize_notification_row(dict(row)) for row in rows],
        "unread_count": unread_count,
    }


@app.post("/api/notifications/read")
def mark_notifications_read(request: Request) -> dict[str, Any]:
    user_id = current_user_id(request)

    with connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                update public.notifications
                set read_at = coalesce(read_at, now())
                where user_id::text = %(user_id)s
                  and read_at is null
                  and (expires_at is null or expires_at > now())
                """,
                {"user_id": user_id},
            )
            updated = cursor.rowcount

    return {"updated": updated}


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
    return f"/api/stocks/logo/{symbol.upper()}"


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


def clean_answer(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def strip_reason_prefix(value: str) -> str:
    return re.sub(
        r"^\s*(?:possible\s+)?(?:reason(?:s)?(?:\s+to\s+(?:watch|own|follow|track|monitor))?|reason\s+for\s+(?:watching|owning)|rationale)\s*:\s*",
        "",
        value,
        flags=re.IGNORECASE,
    ).strip()


def fmp_client_from_env() -> Any:
    from report import FmpClient, load_yaml

    api_key = os.getenv("FMP_API_KEY")
    if not api_key:
        logger.error("FMP_API_KEY is not configured")
        raise HTTPException(status_code=500, detail="Market data service is not configured.")

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


def fmp_error_status(exc: Exception) -> int:
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    return status_code if isinstance(status_code, int) else 502


def fmp_public_error_detail(operation: str, exc: Exception) -> str:
    status_code = fmp_error_status(exc)
    if status_code in {401, 403}:
        return f"Stock {operation} is temporarily unavailable."
    if status_code == 429:
        return f"Stock {operation} is temporarily rate limited."
    return f"Stock {operation} failed. Please try again later."


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
            status_code = fmp_error_status(exc)
            detail = fmp_public_error_detail("search", exc)
            logger.warning("FMP search failed endpoint=%s status=%s error=%s", endpoint, status_code, exc)
            raise HTTPException(status_code=status_code, detail=detail) from exc
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


@app.get("/api/stocks/logo/{symbol}", response_model=None)
def stock_logo(symbol: str) -> Response:
    cleaned_symbol = clean_symbol(symbol)
    url = f"https://financialmodelingprep.com/image-stock/{cleaned_symbol}.png"
    try:
        upstream = requests.get(url, timeout=10)
        upstream.raise_for_status()
    except Exception as exc:
        logger.warning("Stock logo fetch failed symbol=%s error=%s", cleaned_symbol, exc)
        raise HTTPException(status_code=404, detail="Stock logo not found.") from exc

    content_type = upstream.headers.get("content-type", "image/png")
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=404, detail="Stock logo not found.")
    return Response(
        content=upstream.content,
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=86400"},
    )


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
    first_field = "why_i_own_it" if item_type == "portfolio" else "why_i_watch_it"
    normalized: dict[str, list[str]] = {}
    for key in schema:
        value = payload.get(key)
        if isinstance(value, str):
            bullets = clean_bullets([value])
        elif isinstance(value, list):
            bullets = clean_bullets([str(item) for item in value])
        else:
            bullets = []
        if key == first_field:
            bullets = clean_bullets([strip_reason_prefix(item) for item in bullets])
        normalized[key] = bullets
    return normalized


def guided_thesis_answers(payload: DraftThesisRequest) -> list[dict[str, str]]:
    answers: list[dict[str, str]] = []
    for item in payload.answers:
        question_id = item.question_id.strip()
        answer = clean_answer(item.answer)
        if not question_id or not answer:
            continue
        answers.append(
            {
                "question_id": question_id,
                "question": GUIDED_THESIS_QUESTIONS.get(question_id, question_id),
                "answer": answer,
            }
        )
    return answers


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
    guided_answers = guided_thesis_answers(payload)
    first_guidance = (
        "2 to 4 concise possible reasons a long-term investor might own this company; write the reason text directly with no label prefix"
        if payload.item_type == "portfolio"
        else "2 to 4 concise possible reasons a long-term investor might watch this company; write the reason text directly with no label prefix"
    )

    task = (
        "Convert the user's investing rationale into a monitorable thesis for review and editing."
        if payload.mode == "guided" and guided_answers
        else "Generate a neutral draft investment thesis for a user to review and edit."
    )
    prompt = {
        "task": task,
        "company": {"symbol": symbol, "company_name": company_name},
        "item_type": payload.item_type,
        "mode": payload.mode,
        "required_json_schema": schema,
        "field_guidance": {
            first_label: first_guidance,
            "bull_case": "3 concise bullets for what could go right",
            "bear_case": "3 concise bullets for what could go wrong",
            "key_metrics": "3 concise metrics or signals to monitor",
            "red_flags": "3 concise warning signs",
            "action_triggers": "3 concise negative or thesis-breaking events/evidence that would make an existing holder reconsider the position",
            "entry_conditions": "3 concise pieces of evidence that would make this watchlist company more attractive as a portfolio candidate",
        },
        "constraints": [
            "Return valid JSON only.",
            "Each field must be an array of 2 to 4 short bullets.",
            "Do not recommend buying, selling, holding, position sizing, or trading.",
            "Use cautious language because this is only an AI draft.",
            "Do not claim to know the user's personal reason; phrase personal-looking fields as possible reasons.",
            "For the first field, do not prefix bullets with labels such as 'Possible reason:', 'Reason to watch:', or 'Reason to own:'.",
        ],
    }
    if payload.mode == "guided" and guided_answers:
        prompt["user_answers"] = guided_answers
        prompt["constraints"].extend(
            [
                "Use the user answers as the source of intent.",
                "Preserve the user's actual rationale and do not add unrelated thesis pillars.",
                "Expand vague answers into observable signals, risks, metrics, and thesis-breaking evidence.",
                "If the user leaves optional answers blank, infer the missing sections only from the provided answers and company context.",
                "Make inferred bullets cautious and monitorable rather than confident or advisory.",
            ]
        )
    try:
        response = OpenAI().responses.create(
            model=model,
            input=[
                {"role": "system", "content": "You generate concise, neutral investment thesis drafts as JSON only."},
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
        )
        usage = openai_usage_summary(response, model, config)
        log_openai_usage(user_id, f"{payload.item_type}_{payload.mode}_draft", usage)
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


def row_any(row: dict[str, Any], *names: str) -> Any:
    lower_map = {str(key).lower(): value for key, value in row.items()} if isinstance(row, dict) else {}
    for name in names:
        if name in row and row.get(name) not in (None, "", []):
            return row.get(name)
        value = lower_map.get(str(name).lower())
        if value not in (None, "", []):
            return value
    return None


def fiscal_quarter_number(row: dict[str, Any]) -> int | None:
    value = row_any(row, "quarter", "fiscalQuarter", "fiscal_quarter", "fiscalQ", "q")
    if value in (None, "", []):
        value = row_any(row, "period")
    if value in (None, "", []):
        return None
    text = str(value).strip().upper()
    if not text or text in {"FY", "ANNUAL"}:
        return None
    if text.startswith("Q"):
        text = text[1:].split()[0]
    try:
        quarter = int(float(text))
    except (TypeError, ValueError):
        return None
    return quarter if 1 <= quarter <= 4 else None


def fiscal_year_value(row: dict[str, Any]) -> str | None:
    year = row_any(row, "calendarYear", "fiscalYear", "fiscal_year", "year")
    if year not in (None, "", []):
        try:
            return str(int(float(year)))
        except (TypeError, ValueError):
            return str(year)
    date_value = row_any(row, "fiscalDateEnding", "date", "publishedDate")
    if date_value:
        return str(date_value)[:4]
    return None


def fiscal_quarter_label(row: dict[str, Any]) -> str | None:
    quarter = fiscal_quarter_number(row)
    if not quarter:
        return None
    year = fiscal_year_value(row)
    return f"Q{quarter} {year}" if year else f"Q{quarter}"


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
        try:
            next_year = str(int(float(year)) + 1)
        except (TypeError, ValueError):
            next_year = year
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


def fetch_research_earnings_reports(client: Any, symbol: str, today: dt.date) -> dict[str, Any]:
    rows = fmp_items(try_fmp_get(client, "earnings", {"symbol": symbol, "limit": 100, "includeReportTimes": True}))
    quarter_rows = fmp_items(try_fmp_get(client, "income-statement", {"symbol": symbol, "period": "quarter", "limit": 12}))
    dated_rows = [
        (parsed_date, row)
        for row in rows
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
    earnings_reports: dict[str, Any],
    price_history: list[dict[str, Any]],
    intraday_history: list[dict[str, Any]],
    metric_snapshot: dict[str, Any] | None = None,
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
        ratios.get("priceToEarningsRatioTTM"),
        ratios.get("priceToEarningsRatio"),
        metrics.get("peRatioTTM"),
        metrics.get("priceEarningsRatioTTM"),
        metrics.get("priceToEarningsRatioTTM"),
        metrics_latest.get("peRatio"),
        metrics_latest.get("priceToEarningsRatio"),
        ratios.get("priceEarningsRatioTTM"),
        ratios.get("priceEarningsRatio"),
        ratios_latest.get("priceToEarningsRatio"),
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
    dividend_yield = ratio_to_percent(
        first_number(
            metrics.get("dividendYieldTTM"),
            metrics.get("dividendYield"),
            metrics.get("dividendYieldPercentageTTM"),
            metrics.get("dividendYieldPercentage"),
            ratios.get("dividendYieldTTM"),
            ratios.get("dividendYield"),
            ratios.get("dividendYieldPercentageTTM"),
            ratios.get("dividendYieldPercentage"),
            metrics_latest.get("dividendYield"),
            metrics_latest.get("dividendYieldPercentage"),
            ratios_latest.get("dividendYield"),
            ratios_latest.get("dividendYieldPercentage"),
            quote.get("dividendYield"),
        )
    )
    roe = ratio_to_percent(ratios.get("returnOnEquityTTM") or ratios.get("returnOnEquity") or metrics.get("roeTTM") or ratios_latest.get("returnOnEquity"))
    if roe is None and net_income is not None and equity not in (None, 0):
        roe = (net_income / equity) * 100
    debt_to_equity = first_number(
        metrics.get("debtToEquityTTM"),
        metrics.get("debtToEquityRatioTTM"),
        ratios.get("debtToEquityRatioTTM"),
        ratios.get("debtToEquityRatio"),
        ratios.get("debtToEquityTTM"),
        ratios.get("debtToEquity"),
        ratios.get("debtEquityRatioTTM"),
        ratios.get("debtEquityRatio"),
        ratios_latest.get("debtToEquityRatio"),
        ratios_latest.get("debtToEquity"),
        ratios_latest.get("debtEquityRatio"),
        divide_or_none(total_debt, equity),
    )

    return {
        "price_history": price_history,
        "intraday_history": intraday_history,
        "earnings_reports": earnings_reports.get("reports") or [],
        "next_earnings_date": earnings_reports.get("next_earnings_date"),
        "metrics": metric_snapshot or {
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
            "dividend_yield_pct": dividend_yield if dividend_yield and dividend_yield > 0 else None,
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


def research_mode_from_type(research_type: str) -> str:
    return {
        "portfolio_check": "portfolio",
        "watchlist_check": "watchlist",
        "company_primer": "new",
        "deep_research": "deep_research",
    }[research_type]


def requested_research_mode(research_type: str | None, relationship: str) -> str:
    if not research_type:
        return relationship

    mode = research_mode_from_type(research_type)
    if mode == "portfolio" and relationship != "portfolio":
        raise HTTPException(status_code=422, detail="Portfolio check is only available for companies in your portfolio.")
    if mode == "watchlist" and relationship != "watchlist":
        raise HTTPException(status_code=422, detail="Watchlist check is only available for companies in your watchlist.")
    return mode


def create_deep_research_run(
    cursor: Any,
    *,
    user_id: str,
    stock_id: str,
    symbol: str,
    company_name: str,
    relationship: str,
    model: str,
) -> dict[str, Any]:
    from psycopg.types.json import Json

    cursor.execute(
        """
        insert into public.research_runs (
            user_id,
            stock_id,
            research_type,
            status,
            progress_step,
            progress_pct,
            model,
            request
        )
        values (
            %(user_id)s,
            %(stock_id)s,
            'deep_research',
            'queued',
            'Queued for deep research',
            0,
            %(model)s,
            %(request)s
        )
        returning
            id::text as id,
            user_id::text as user_id,
            stock_id::text as stock_id,
            research_item_id::text as research_item_id,
            usage_id::text as usage_id,
            research_type,
            status,
            progress_step,
            progress_pct,
            model,
            request,
            usage,
            error,
            created_at,
            started_at,
            completed_at,
            updated_at
        """,
        {
            "user_id": user_id,
            "stock_id": stock_id,
            "model": model,
            "request": Json(
                {
                    "symbol": symbol,
                    "company_name": company_name,
                    "relationship": relationship,
                }
            ),
        },
    )
    return dict(cursor.fetchone())


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
            research_mode = requested_research_mode(payload.research_type, relationship)
            if research_mode == "deep_research":
                config = load_yaml(ROOT / "config.yaml")
                model = config.get("openai", {}).get("deep_research_model", "gpt-5.6-terra")
                stock_id = item["stock_id"] if item else get_or_create_stock(cursor, symbol, company_name)
                run = create_deep_research_run(
                    cursor,
                    user_id=user_id,
                    stock_id=stock_id,
                    symbol=symbol,
                    company_name=company_name,
                    relationship=relationship,
                    model=model,
                )
                return {
                    "mode": "deep_research",
                    "relationship": relationship,
                    "status": run["status"],
                    "research_run_id": run["id"],
                    "progress_step": run.get("progress_step"),
                    "progress_pct": int(run.get("progress_pct") or 0),
                    "stock": {
                        "stock_id": stock_id,
                        "symbol": symbol,
                        "company_name": company_name,
                        "logo_url": stock_logo_url(symbol),
                    },
                    "model": model,
                }

    client = fmp_client_from_env()
    profile = first_item(try_fmp_get(client, "profile", {"symbol": symbol}))
    quote = first_item(try_fmp_get(client, "quote", {"symbol": symbol}))
    metrics = first_item(try_fmp_get(client, "key-metrics-ttm", {"symbol": symbol}))
    metrics_latest = first_item(try_fmp_get(client, "key-metrics", {"symbol": symbol, "period": "annual", "limit": 1}))
    ratios = first_item(try_fmp_get(client, "ratios-ttm", {"symbol": symbol}))
    ratios_latest = first_item(try_fmp_get(client, "ratios", {"symbol": symbol, "period": "annual", "limit": 1}))
    market_cap_row = first_item(try_fmp_get(client, "market-capitalization", {"symbol": symbol}))
    metrics_annual = fmp_items(try_fmp_get(client, "key-metrics", {"symbol": symbol, "period": "annual", "limit": 10}))
    ratios_annual = (
        fmp_items(try_fmp_get(client, "ratios", {"symbol": symbol, "limit": 10}))
        + fmp_items(try_fmp_get(client, "ratios", {"symbol": symbol, "period": "annual", "limit": 10}))
    )
    income_ttm = first_item(try_fmp_get(client, "income-statement-ttm", {"symbol": symbol}))
    balance_ttm = first_item(try_fmp_get(client, "balance-sheet-statement-ttm", {"symbol": symbol}))
    cashflow_ttm = first_item(try_fmp_get(client, "cash-flow-statement-ttm", {"symbol": symbol}))
    income_rows = try_fmp_get(client, "income-statement", {"symbol": symbol, "period": "annual", "limit": 6})
    balance_annual = fmp_items(try_fmp_get(client, "balance-sheet-statement", {"symbol": symbol, "period": "annual", "limit": 10}))
    cashflow_annual = fmp_items(try_fmp_get(client, "cash-flow-statement", {"symbol": symbol, "period": "annual", "limit": 10}))
    growth_annual = fmp_items(try_fmp_get(client, "financial-growth", {"symbol": symbol, "period": "annual", "limit": 10}))
    income = first_item(income_rows)
    analyst_estimate = fetch_first_available(
        client,
        [
            ("analyst-estimates", {"symbol": symbol, "period": "annual", "limit": 2}),
            ("analyst-estimates", {"symbol": symbol, "limit": 2}),
        ],
    )
    earnings = fetch_latest_actual_earnings(client, symbol, dt.date.today())
    earnings_reports = fetch_research_earnings_reports(client, symbol, dt.date.today())
    price_history = fetch_price_history(client, symbol, date_to)
    intraday_history = fetch_intraday_history(client, symbol)
    metric_snapshot = None
    try:
        from deep_research import build_metric_snapshot

        metric_snapshot = build_metric_snapshot(
            {
                "quote": quote,
                "market_cap": market_cap_row,
                "metrics_ttm": metrics,
                "ratios_ttm": ratios or first_item(ratios_annual),
                "metrics_annual": metrics_annual,
                "ratios_annual": ratios_annual,
                "income_annual": fmp_items(income_rows),
                "cashflow_annual": cashflow_annual,
                "balance_annual": balance_annual,
                "growth_annual": growth_annual,
            }
        )
    except Exception:
        metric_snapshot = None
    news: list[dict[str, Any]] = []
    if research_mode in {"portfolio", "watchlist"}:
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
    }[research_mode]
    research_item = item if research_mode in {"portfolio", "watchlist"} else None
    context = {
        "company": {
            "symbol": symbol,
            "company_name": company_name,
            "relationship": research_mode,
        },
        "date_window": {"from": date_from.isoformat(), "to": date_to.isoformat()} if research_mode != "new" else None,
        "user_item": research_item,
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
            "earnings_reports": earnings_reports.get("reports") or [],
            "next_earnings_date": earnings_reports.get("next_earnings_date"),
            "news": [compact_news_item(item) for item in news[:8]],
        },
        "required_json_schema": research_schema(research_mode),
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
        earnings_reports=earnings_reports,
        price_history=price_history,
        intraday_history=intraday_history,
        metric_snapshot=metric_snapshot,
    )
    if research_mode == "new":
        instructions = (
            "Create a deep but concise company primer for a long-term investor who does not yet own or watch this company. "
            "Focus on what the company actually does, how it makes money, product lines, customer/end-market exposure, competitive position, current situation, future outlook, bull case, bear case, and what to learn next. "
            "Do not make a buy/sell/hold recommendation. Do not over-focus on generic valuation metrics. Use supplied data only; if something is unknown, say what should be verified."
        )
    elif research_mode == "portfolio":
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
        research = normalize_research_payload(parse_model_json(response.output_text), research_mode)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Research generation failed: {exc}") from exc

    response_payload = {
        "mode": research_mode,
        "relationship": relationship,
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
                    "research_type": research_type_for_mode(research_mode),
                    "signal": research_signal_from_body(response_payload),
                    "date_from": date_from if research_mode != "new" else None,
                    "date_to": date_to if research_mode != "new" else None,
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


def display_long_date(value: Any) -> str:
    if isinstance(value, dt.datetime):
        value = value.date()
    if isinstance(value, dt.date):
        return f"{value.strftime('%B')} {value.day}, {value.year}"
    try:
        parsed = dt.date.fromisoformat(str(value))
        return f"{parsed.strftime('%B')} {parsed.day}, {parsed.year}"
    except (TypeError, ValueError):
        return str(value or "")


def fallback_report_period_display(report_date: Any, frequency: str) -> str:
    parsed = report_date if isinstance(report_date, dt.date) else None
    if parsed is None:
        try:
            parsed = dt.date.fromisoformat(str(report_date))
        except (TypeError, ValueError):
            return str(report_date or "")

    if frequency == "weekly":
        start = parsed - dt.timedelta(days=parsed.weekday())
        return f"{display_long_date(start)} - {display_long_date(parsed)}"
    if frequency == "monthly":
        start = parsed.replace(day=1)
        return f"{display_long_date(start)} - {display_long_date(parsed)}"
    return display_long_date(parsed)


def report_archive_metadata_from_html(report_html: str | None) -> dict[str, str]:
    metadata = {"report_frequency": "daily", "report_period_display": ""}
    if not report_html:
        return metadata

    kicker_match = re.search(r'class=["\'][^"\']*\breport-kicker\b[^"\']*["\'][^>]*>(.*?)</span>', report_html, re.IGNORECASE | re.DOTALL)
    if kicker_match:
        kicker = html.unescape(re.sub(r"<[^>]+>", "", kicker_match.group(1))).strip().lower()
        if "weekly" in kicker:
            metadata["report_frequency"] = "weekly"
        elif "monthly" in kicker:
            metadata["report_frequency"] = "monthly"
        elif "daily" in kicker:
            metadata["report_frequency"] = "daily"

    date_match = re.search(r'class=["\'][^"\']*\breport-date-main\b[^"\']*["\'][^>]*>(.*?)</strong>', report_html, re.IGNORECASE | re.DOTALL)
    if date_match:
        metadata["report_period_display"] = html.unescape(re.sub(r"<[^>]+>", "", date_match.group(1))).strip()

    return metadata


def serialize_report_row(row: dict[str, Any], include_html: bool = False) -> dict[str, Any]:
    metadata = report_archive_metadata_from_html(row.get("html"))
    report_frequency = str(row.get("report_frequency") or metadata["report_frequency"] or "daily").lower()
    if report_frequency not in {"daily", "weekly", "monthly"}:
        report_frequency = "daily"
    report_period_display = (
        row.get("report_period_display")
        or metadata["report_period_display"]
        or fallback_report_period_display(row.get("report_date"), report_frequency)
    )
    payload = {
        "id": str(row["id"]),
        "report_date": row["report_date"].isoformat() if hasattr(row["report_date"], "isoformat") else row["report_date"],
        "report_frequency": report_frequency,
        "report_period_display": report_period_display,
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
        "deep_research": "deep_research",
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


def serialize_research_run_row(row: dict[str, Any]) -> dict[str, Any]:
    symbol = str(row["symbol"]).upper()
    payload = {
        "id": str(row["id"]),
        "research_run_id": str(row["id"]),
        "user_id": str(row["user_id"]),
        "stock_id": str(row["stock_id"]),
        "research_item_id": str(row["research_item_id"]) if row.get("research_item_id") else None,
        "usage_id": str(row["usage_id"]) if row.get("usage_id") else None,
        "research_type": row.get("research_type"),
        "status": row.get("status"),
        "progress_step": row.get("progress_step"),
        "progress_pct": int(row.get("progress_pct") or 0),
        "model": row.get("model"),
        "request": row.get("request") or {},
        "usage": row.get("usage") or {},
        "error": row.get("error"),
        "created_at": row["created_at"].isoformat() if hasattr(row.get("created_at"), "isoformat") else row.get("created_at"),
        "started_at": row["started_at"].isoformat() if row.get("started_at") and hasattr(row.get("started_at"), "isoformat") else row.get("started_at"),
        "completed_at": row["completed_at"].isoformat() if row.get("completed_at") and hasattr(row.get("completed_at"), "isoformat") else row.get("completed_at"),
        "updated_at": row["updated_at"].isoformat() if hasattr(row.get("updated_at"), "isoformat") else row.get("updated_at"),
        "stock": {
            "stock_id": str(row["stock_id"]),
            "symbol": symbol,
            "company_name": row["company_name"],
            "logo_url": stock_logo_url(symbol),
        },
    }
    if row.get("research_item_id"):
        payload["research_item"] = {
            "id": str(row["research_item_id"]),
            "stock_id": str(row["stock_id"]),
            "symbol": symbol,
            "company_name": row["company_name"],
            "logo_url": stock_logo_url(symbol),
            "research_type": row.get("item_research_type") or row.get("research_type"),
            "signal": row.get("item_signal"),
            "date_from": row["item_date_from"].isoformat() if row.get("item_date_from") and hasattr(row.get("item_date_from"), "isoformat") else row.get("item_date_from"),
            "date_to": row["item_date_to"].isoformat() if row.get("item_date_to") and hasattr(row.get("item_date_to"), "isoformat") else row.get("item_date_to"),
            "created_at": row["item_created_at"].isoformat() if row.get("item_created_at") and hasattr(row.get("item_created_at"), "isoformat") else row.get("item_created_at"),
            "note_count": int(row.get("note_count") or 0),
            "body": row.get("item_body"),
        }
    return payload


def validate_email_address(value: str, detail: str) -> str:
    email_value = (value or "").strip()
    if not email_value or "@" not in email_value or "." not in email_value.rsplit("@", 1)[-1]:
        raise HTTPException(status_code=422, detail=detail)
    return email_value


def validate_share_email(value: str) -> str:
    return validate_email_address(value, "Enter a valid recipient email.")


def validate_feedback_email(value: str) -> str:
    return validate_email_address(value, "Enter a valid email.")


FEEDBACK_RECIPIENT_EMAIL = "simon.smejkal@seznam.cz"
FEEDBACK_CATEGORY_LABELS = {
    "bug": "Bug",
    "feature_request": "Feature request",
    "small_improvement": "Small improvement",
    "data_quality": "Data or calculation issue",
    "usability": "Usability / UX",
    "other": "Other",
}


def validate_feedback_category(value: str) -> str:
    category = (value or "").strip()
    if category not in FEEDBACK_CATEGORY_LABELS:
        raise HTTPException(status_code=422, detail="Select a valid feedback category.")
    return category


def validate_feedback_message(value: str) -> str:
    message = (value or "").strip()
    if len(message) < 10:
        raise HTTPException(status_code=422, detail="Feedback message must be at least 10 characters.")
    if len(message) > 10000:
        raise HTTPException(status_code=422, detail="Feedback message is too long.")
    return message


def app_public_url() -> str:
    return (os.getenv("API_PUBLIC_URL") or "http://localhost:8000").strip().rstrip("/")


def absolute_public_url(value: str | None) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    if re.match(r"^https?://", text, flags=re.IGNORECASE):
        return text
    return urljoin(f"{app_public_url()}/", text.lstrip("/"))


def stock_email_logo_url(symbol: str, value: str | None = None) -> str | None:
    absolute_url = absolute_public_url(value)
    if absolute_url and "localhost" not in absolute_url and "127.0.0.1" not in absolute_url:
        return absolute_url
    cleaned_symbol = "".join(char for char in str(symbol or "").upper().strip() if char.isalnum() or char in {".", "-"})
    return f"https://financialmodelingprep.com/image-stock/{cleaned_symbol}.png" if cleaned_symbol else absolute_url


def html_escape(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def html_email_text(value: Any) -> str:
    return html_escape(value).replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")


def email_spacer(height: int = 14) -> str:
    return f'<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;"><tr><td height="{height}" style="font-size:{height}px;line-height:{height}px;">&nbsp;</td></tr></table>'


def render_research_email_panel(title: str, content_html: str) -> str:
    return f"""
    {email_spacer(14)}
    <div style="background:#181818;border:1px solid #2a2a2a;border-left:4px solid #f3c42e;border-radius:8px;margin:0;padding:16px;">
      <h3 style="color:#ffffff;font-size:18px;line-height:1.25;margin:0 0 15px;">{html_escape(title)}</h3>
      {content_html}
    </div>
    """


def research_email_label(value: str | None) -> str:
    return {
        "portfolio_check": "Portfolio thesis check",
        "watchlist_check": "Watchlist entry check",
        "company_primer": "Company primer",
        "deep_research": "Deep research",
    }.get(value or "", py_human_label(value or "Research"))


def py_human_label(value: Any) -> str:
    return " ".join(str(value or "").replace("_", " ").split()).title()


def py_capitalize_first(value: Any) -> str:
    text = str(value or "").strip()
    return text[:1].upper() + text[1:] if text else ""


def compact_email_number(value: Any, prefix: str = "", suffix: str = "") -> str:
    number = None
    try:
        if value is not None and value != "":
            number = float(value)
    except (TypeError, ValueError):
        number = None
    if number is None:
        return "N/A"
    abs_number = abs(number)
    if abs_number >= 1_000_000_000_000:
        formatted = f"{number / 1_000_000_000_000:.2f}".rstrip("0").rstrip(".") + "T"
    elif abs_number >= 1_000_000_000:
        formatted = f"{number / 1_000_000_000:.2f}".rstrip("0").rstrip(".") + "B"
    elif abs_number >= 1_000_000:
        formatted = f"{number / 1_000_000:.2f}".rstrip("0").rstrip(".") + "M"
    elif abs_number >= 100:
        formatted = f"{number:.0f}"
    else:
        formatted = f"{number:.2f}".rstrip("0").rstrip(".")
    return f"{prefix}{formatted}{suffix}"


def research_email_metric_value(key: str, value: Any) -> str:
    currency_metric_keys = {
        "eps",
        "fcf_per_share",
        "market_cap",
        "price",
        "revenue_per_share",
        "year_high",
        "year_low",
    }

    if key == "dividend_yield_pct":
        number = safe_float(value)
        return f"{number:.2f}%" if number and number > 0 else "-"
    if key in currency_metric_keys:
        return compact_email_number(value, prefix="$")
    if "growth" in key or "margin" in key or "yield" in key:
        return compact_email_number(value, suffix="%")
    return compact_email_number(value)


def research_email_metrics(body: dict[str, Any]) -> list[tuple[str, str]]:
    metrics = (((body or {}).get("market_data") or {}).get("metrics") or {})
    labels = {
        "price": "Price",
        "market_cap": "Market cap",
        "pe": "P/E TTM",
        "ps": "P/S TTM",
        "ev_to_ebitda": "EV/EBITDA",
        "fcf_yield_pct": "FCF yield",
        "dividend_yield_pct": "Dividend yield",
        "eps": "EPS",
        "revenue_growth_3y_pct": "Revenue growth 3Y",
        "eps_growth_3y_pct": "EPS growth 3Y",
        "eps_growth_5y_pct": "EPS growth 5Y",
        "revenue_per_share": "Revenue/share",
        "gross_margin_pct": "Gross margin",
        "operating_margin_pct": "Operating margin",
        "net_margin_pct": "Net margin",
        "year_high": "52W high",
        "year_low": "52W low",
    }
    return [(label, research_email_metric_value(key, metrics.get(key))) for key, label in labels.items()]


def render_research_email_list(title: str, items: Any) -> str:
    if not isinstance(items, list) or not items:
        return ""
    rows = "".join(
        f"""
        <tr>
          <td colspan="2" bgcolor="#303030" height="1" style="background:#303030;background-color:#303030!important;color:#303030;font-size:1px;line-height:1px;mso-line-height-rule:exactly;">&nbsp;</td>
        </tr>
        <tr>
          <td width="34" style="width:34px;vertical-align:top;padding:12px 10px 12px 0;color:#f3c42e;font-weight:700;">{index:02d}</td>
          <td style="padding:12px 0;color:#d7d7d0;font-size:14px;line-height:1.55;">{html_email_text(item if isinstance(item, str) else json.dumps(item, ensure_ascii=False))}</td>
        </tr>
        """
        for index, item in enumerate(items, start=1)
    )
    return render_research_email_panel(title, f"<table role=\"presentation\" width=\"100%\" cellspacing=\"0\" cellpadding=\"0\" style=\"border-collapse:collapse;\">{rows}</table>")


def render_research_email_assessments(title: str, items: Any, title_key: str) -> str:
    if not isinstance(items, list) or not items:
        return ""
    blocks = []
    for item in items:
        if not isinstance(item, dict):
            continue
        evidence_items = item.get("evidence") if isinstance(item.get("evidence"), list) else []
        evidence_html = ""
        if evidence_items:
            evidence_html = "<ul style=\"margin:8px 0 0 18px;padding:0;color:#d7d7d0;line-height:1.5;\">" + "".join(
                f"<li>{html_email_text(point.get('text') if isinstance(point, dict) else point)}</li>"
                for point in evidence_items
            ) + "</ul>"
        blocks.append(
            f"""
            {email_spacer(10)}
            <div style="background:#0d0d0d;border:1px solid #2a2a2a;border-radius:8px;margin:0;padding:12px;">
              <strong style="color:#ffffff;font-size:14px;line-height:1.35;">{html_escape(py_capitalize_first(item.get(title_key) or "Item"))}</strong>
              <p style="color:#d7d7d0;font-size:14px;line-height:1.55;margin:8px 0 0;">{html_email_text(item.get("assessment") or "")}</p>
              {evidence_html}
            </div>
            """
        )
    if not blocks:
        return ""
    return render_research_email_panel(title, "".join(blocks))


def render_research_email_articles(title: str, items: Any) -> str:
    if not isinstance(items, list) or not items:
        return ""
    blocks = []
    for item in items:
        if not isinstance(item, dict):
            continue
        link = item.get("source_url")
        link_html = f"<a href=\"{html_escape(link)}\" style=\"color:#f3c42e;text-decoration:none;\">Full article</a>" if link else ""
        blocks.append(
            f"""
            {email_spacer(10)}
            <div style="background:#0d0d0d;border:1px solid #2a2a2a;border-radius:8px;margin:0;padding:12px;">
              <strong style="color:#ffffff;font-size:14px;line-height:1.35;">{html_escape(item.get("headline") or "Article")}</strong>
              <p style="color:#d7d7d0;font-size:14px;line-height:1.55;margin:8px 0;">{html_email_text(item.get("summary") or "")}</p>
              {link_html}
            </div>
            """
        )
    return render_research_email_panel(title, "".join(blocks))


def render_research_email_body(body: dict[str, Any]) -> str:
    research = (body or {}).get("research") or {}
    mode = (body or {}).get("mode")
    sections = []
    if mode == "portfolio":
        sections.extend(
            [
                render_research_email_list("Executive summary", research.get("executive_summary")),
                render_research_email_assessments("Thesis check", research.get("thesis_check"), "field"),
                render_research_email_articles("Recent developments", research.get("recent_developments")),
                render_research_email_list("Risks to watch", research.get("risks_to_watch")),
                render_research_email_list("Suggested next steps", research.get("suggested_next_steps")),
            ]
        )
    elif mode == "watchlist":
        sections.extend(
            [
                render_research_email_list("Executive summary", research.get("executive_summary")),
                render_research_email_assessments("Entry conditions check", research.get("entry_conditions_check"), "condition"),
                render_research_email_articles("Recent developments", research.get("recent_developments")),
                render_research_email_list("Still missing", research.get("still_missing")),
                render_research_email_list("Suggested next steps", research.get("suggested_next_steps")),
            ]
        )
    else:
        for key, title in [
            ("company_overview", "Company overview"),
            ("business_model", "Business model"),
            ("products_and_customers", "Products and customers"),
            ("current_situation", "Current situation"),
            ("future_outlook", "Future outlook"),
            ("bull_case", "Bull case"),
            ("bear_case", "Bear case"),
            ("what_to_understand_next", "What to understand next"),
        ]:
            sections.append(render_research_email_list(title, research.get(key)))
    return "".join(section for section in sections if section)


def render_shared_research_email(
    *,
    research_item: dict[str, Any],
    notes: list[dict[str, Any]],
    sender: dict[str, Any] | None,
    message: str | None,
) -> str:
    body = research_item.get("body") if isinstance(research_item.get("body"), dict) else {}
    stock = body.get("stock") if isinstance(body.get("stock"), dict) else {}
    research = body.get("research") if isinstance(body.get("research"), dict) else {}
    sender_name = (sender or {}).get("display_name") or (sender or {}).get("email") or "A Morning Alpha user"
    signal = research.get("signal") or research.get("watchlist_suitability") or research_item.get("signal")
    stock_symbol = str(stock.get("symbol") or research_item.get("symbol") or "").upper()
    company_name = stock.get("company_name") or research_item.get("company_name") or stock_symbol
    stock_logo_src = stock_email_logo_url(stock_symbol, stock.get("logo_url") or research_item.get("logo_url") or (stock_logo_url(stock_symbol) if stock_symbol else None))
    email_title = f"{research_email_label(research_item.get('research_type'))} for {company_name or stock_symbol}"
    metric_cells = [
        f"""
        <td width="50%" style="width:50%;padding:6px;vertical-align:top;">
          <div style="background:#0d0d0d;border:1px solid #2a2a2a;border-radius:8px;margin:0;padding:10px;">
            <div style="color:#a7a7a0;font-size:12px;line-height:1.25;">{html_escape(label)}</div>
            <div style="color:#ffffff;font-size:15px;font-weight:700;line-height:1.25;margin-top:4px;">{html_escape(value)}</div>
          </div>
        </td>
        """
        for label, value in research_email_metrics(body)
    ]
    metric_rows = "".join(f"<tr>{''.join(metric_cells[index:index + 2])}</tr>" for index in range(0, len(metric_cells), 2))
    notes_html = ""
    if notes:
        note_blocks = "".join(
            f"""
            {email_spacer(10)}
            <div style="background:#0d0d0d;border:1px solid #2a2a2a;border-radius:8px;margin:0;padding:12px;">
              <p style="color:#d7d7d0;font-size:14px;line-height:1.55;margin:0;">{html_email_text(note.get("body"))}</p>
              <p style="color:#a7a7a0;font-size:12px;line-height:1.4;margin:18px 0 0;">Created {html_escape(note.get("created_at"))}</p>
            </div>
            """
            for note in notes
        )
        notes_html = render_research_email_panel(f"Notes from {sender_name}", note_blocks)
    app_url = app_public_url()
    logo_src = None
    cta_button_src = None
    try:
        from report import email_asset_src

        logo_src = email_asset_src("ma-logo.png")
        cta_button_src = email_asset_src("create-account-button.png")
    except Exception:
        logo_src = None
        cta_button_src = None
    logo_html = (
        f"<img src=\"{logo_src}\" width=\"270\" height=\"50\" alt=\"Morning Alpha\" style=\"border:0;display:block;height:auto;line-height:0;max-width:270px;width:270px;\">"
        if logo_src
        else "<strong style=\"color:#ffffff;font-size:20px;\">Morning Alpha</strong>"
    )
    cta_html = (
        f"""
        <a href="{html_escape(app_url)}" style="border:0;display:inline-block;text-decoration:none;">
          <img src="{cta_button_src}" width="320" height="50" alt="Create your Morning Alpha account" style="border:0;display:block;height:50px;line-height:0;max-width:100%;width:320px;">
        </a>
        """
        if cta_button_src
        else f"""
        <table border="0" cellpadding="0" cellspacing="0" role="presentation">
          <tr>
            <td bgcolor="#f3c42e" style="background:#f3c42e;border-radius:8px;mso-padding-alt:14px 18px;">
              <a href="{html_escape(app_url)}" style="background:#f3c42e;color:#111111;display:inline-block;font-size:16px;font-weight:700;line-height:20px;padding:14px 18px;text-decoration:none;">Create your account</a>
            </td>
          </tr>
        </table>
        """
    )
    message_html = (
        f"""
        <div style="background:#0d0d0d;border:1px solid #343434;border-radius:8px;margin:0 0 14px;padding:14px;">
          <div style="color:#a7a7a0;font-size:12px;line-height:1.35;margin-bottom:6px;">Message from {html_escape(sender_name)}</div>
          <p style="color:#ffffff;font-size:14px;line-height:1.55;margin:0;">{html_email_text(message)}</p>
        </div>
        {email_spacer(14)}
        """
        if message
        else ""
    )
    company_logo_html = (
        f"""
        <table border="0" cellpadding="0" cellspacing="0" role="presentation" width="46" style="border-collapse:collapse;width:46px;">
          <tr>
            <td align="center" bgcolor="#ffffff" style="background:#ffffff;background-color:#ffffff!important;border-radius:8px;height:46px;padding:0;text-align:center;vertical-align:middle;width:46px;">
              <img src="{html_escape(stock_logo_src)}" width="34" height="34" alt="{html_escape(stock_symbol)}" style="-webkit-filter:none!important;border:0;display:inline-block;filter:none!important;height:34px;line-height:34px;max-height:34px;max-width:34px;min-height:34px;min-width:34px;object-fit:contain;outline:0;text-decoration:none;vertical-align:middle;width:34px;">
            </td>
          </tr>
        </table>
        """
        if stock_logo_src
        else f"""
        <table border="0" cellpadding="0" cellspacing="0" role="presentation" width="46" style="border-collapse:collapse;width:46px;">
          <tr>
            <td align="center" bgcolor="#0d0d0d" style="background:#0d0d0d;background-color:#0d0d0d!important;border:1px solid #2a2a2a;border-radius:8px;color:#f3c42e;font-size:16px;font-weight:700;height:44px;line-height:44px;text-align:center;vertical-align:middle;width:44px;">{html_escape(stock_symbol[:2])}</td>
          </tr>
        </table>
        """
    )
    company_panel_html = f"""
    <div style="background:#181818;border:1px solid #2a2a2a;border-radius:8px;margin:0 0 8px;padding:16px;">
      <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;">
        <tr>
          <td width="58" style="width:58px;vertical-align:top;padding:0 12px 0 0;">{company_logo_html}</td>
          <td style="vertical-align:top;padding:0;">
            <div style="color:#ffffff;font-size:18px;font-weight:700;line-height:1.25;">{html_escape(stock_symbol)}</div>
            <div style="color:#d7d7d0;font-size:14px;line-height:1.4;margin-top:2px;">{html_escape(company_name)}</div>
            <div style="margin-top:9px;">
              <span style="background:#080808;border:1px solid #5a4a16;border-radius:999px;box-sizing:border-box;color:#f3c42e;display:inline-block;font-size:12px;font-weight:700;line-height:1.25;max-width:100%;padding:7px 10px;word-break:break-word;">{html_escape(py_human_label(signal or "Research"))}</span>
            </div>
          </td>
        </tr>
      </table>
    </div>
    {email_spacer(6)}
    """
    return f"""
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <base target="_blank">
        <title>Shared Morning Alpha research</title>
      </head>
      <body style="margin:0;padding:0;background:#080808;color:#f4f4f0;font-family:Arial,Helvetica,sans-serif;">
        <div style="background:#080808;padding:28px 12px;">
          <div style="max-width:760px;margin:0 auto;background:#111111;border:1px solid #2a2a2a;border-color:#2a2a2a;border-radius:8px;mso-border-alt:solid #2a2a2a 1pt;overflow:hidden;">
            <div style="background:#151515;border-bottom:1px solid #2a2a2a;border-bottom-color:#2a2a2a;mso-border-bottom-alt:solid #2a2a2a 1pt;padding:26px 28px 22px;">
              <div style="margin-bottom:26px;">{logo_html}</div>
              <div style="color:#a7a7a0;font-size:12px;text-transform:uppercase;letter-spacing:.08em;">Shared research</div>
              <h1 style="color:#ffffff;font-size:28px;line-height:1.15;margin:8px 0 10px;">{html_escape(email_title)}</h1>
              <p style="color:#d7d7d0;font-size:14px;line-height:1.55;margin:0 0 16px;">{html_escape(sender_name)} shared this Morning Alpha research with you.</p>
              <div style="margin-top:30px;">
                {cta_html}
              </div>
            </div>
            <div style="padding:24px 28px 28px;">
              {message_html}
              {company_panel_html}
              <div style="background:#181818;border:1px solid #2a2a2a;border-radius:8px;margin:0 0 14px;padding:16px;">
                <h3 style="color:#ffffff;font-size:18px;line-height:1.25;margin:0 0 10px;">Key metrics</h3>
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;table-layout:fixed;">{metric_rows}</table>
              </div>
              {render_research_email_body(body)}
              {notes_html}
              <div style="background:#17150f;border:1px solid #5a4a16;border-left:4px solid #f3c42e;border-radius:8px;margin:18px 0 0;padding:18px;">
                <a href="{html_escape(app_url)}" style="color:#ffffff;display:block;text-decoration:none;">
                  <strong style="color:#ffffff;display:block;font-size:19px;line-height:1.25;margin-bottom:6px;">Build your own investment research workflow</strong>
                  <span style="color:#d7d7d0;display:block;font-size:14px;line-height:1.5;">Track portfolio theses, watchlist entry conditions, research notes, and daily market reports in Morning Alpha.</span>
                  <span style="color:#f3c42e;display:block;font-size:14px;font-weight:700;margin-top:12px;">Join Morning Alpha</span>
                </a>
              </div>
            </div>
          </div>
        </div>
      </body>
    </html>
    """


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
                    reports.html,
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


def monitor_key(value: str) -> str:
    text = re.sub(r"[^a-z0-9\s]", " ", str(value or "").lower())
    words = [word for word in text.split() if len(word) > 2]
    return " ".join(words[:18])


MONITOR_STOPWORDS = {
    "any",
    "and",
    "are",
    "for",
    "from",
    "how",
    "next",
    "that",
    "the",
    "this",
    "watch",
    "whether",
    "with",
    "management",
    "commentary",
    "comments",
    "updated",
    "upcoming",
    "quarter",
    "quarterly",
    "report",
    "details",
    "discussion",
    "signs",
    "watching",
}


def monitor_tokens(value: str) -> set[str]:
    words = re.findall(r"[a-z0-9][a-z0-9\-]{2,}", str(value or "").lower())
    normalized = {word.replace("-", "") for word in words}
    return {word for word in normalized if word not in MONITOR_STOPWORDS and len(word) > 2}


def monitor_similarity(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def split_monitor_points(value: str) -> list[str]:
    text = str(value or "").strip().strip(".")
    if not text:
        return []
    text = re.sub(r"\s+", " ", text)
    parts = re.split(
        r"\s*(?:;|,|\bor\b|\band whether\b|\band any\b|\band signs of\b|\band management\b|\band next\b)\s*",
        text,
        flags=re.IGNORECASE,
    )
    output = []
    for part in parts:
        cleaned = clean_monitor_point(part)
        if len(monitor_tokens(cleaned)) >= 1 and cleaned.lower() not in {item.lower() for item in output}:
            output.append(cleaned)
    return output


def clean_monitor_point(value: str) -> str:
    text = str(value or "").strip(" .;:,")
    text = re.sub(r"^(?:and\s+)?(?:watch\s+(?:for\s+)?|monitor\s+|any\s+|next\s+|upcoming\s+|change\s+in\s+|signs?\s+of\s+)", "", text, flags=re.IGNORECASE)
    text = re.sub(
        r"^(?:management\s+)?(?:commentary|comments|discussion|detail|details)\s+(?:on|of|about)\s+",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"^(?:whether|if)\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\bmanagement\s+(?:commentary|comments|discussion)\s+(?:on|of|about)\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip(" .;:,")
    if not text:
        return ""
    text = text[:1].upper() + text[1:]
    if len(text) > 120:
        text = text[:117].rstrip(" ,;.") + "..."
    return text


def monitor_topic_key(value: str) -> str:
    tokens = monitor_tokens(value)
    text = " ".join(sorted(tokens))
    if "aws" in tokens and ("growth" in tokens or "accelerating" in tokens):
        return "aws_growth"
    if {"free", "cash", "flow"}.issubset(tokens) or "fcf" in tokens:
        return "free_cash_flow"
    if "capex" in tokens or ({"capital", "spending"} & tokens):
        return "capex"
    if "ai" in tokens and ({"adoption", "customer", "customers", "demand", "conversion"} & tokens):
        return "ai_adoption"
    if "ai" in tokens and ({"returns", "return", "roi"} & tokens):
        return "ai_returns"
    if {"operating", "income"} & tokens or {"profitability", "margin", "margins"} & tokens:
        return "profitability"
    if {"pricing", "competitive", "competition", "pressure"} & tokens:
        return "pricing_pressure"
    if {"regulatory", "regulation", "penalty", "settlement"} & tokens:
        return "regulatory"
    if {"launch", "product", "adoption", "engagement"} & tokens:
        return "product_adoption"
    return f"terms:{text}"


def monitor_topic_label(topic_key: str) -> str | None:
    return {
        "aws_growth": "AWS growth",
        "free_cash_flow": "Free cash flow",
        "capex": "Capex",
        "ai_adoption": "AI customer adoption",
        "ai_returns": "AI returns",
        "profitability": "Profitability",
        "pricing_pressure": "Pricing pressure",
        "regulatory": "Regulatory exposure",
        "product_adoption": "Product adoption",
    }.get(topic_key)


def concise_monitor_text(values: list[str], topic_key: str = "") -> str:
    label = monitor_topic_label(topic_key)
    if label:
        return label
    if not values:
        return ""
    candidates = sorted(values, key=lambda text: (len(text), text))
    return clean_monitor_point(candidates[0])


def build_monitor_summary(items: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    clusters: list[dict[str, Any]] = []
    for item in items:
        monitor_next = str(item.get("monitor_next") or "").strip()
        if not monitor_next:
            continue
        for point in split_monitor_points(monitor_next):
            tokens = monitor_tokens(point)
            topic_key = monitor_topic_key(point)
            best_cluster = None
            best_score = 0.0
            for cluster in clusters:
                score = 1.0 if cluster["topic_key"] == topic_key else monitor_similarity(tokens, cluster["tokens"])
                if score > best_score:
                    best_cluster = cluster
                    best_score = score
            if best_cluster is None or best_score < 0.5:
                best_cluster = {
                    "topic_key": topic_key,
                    "tokens": set(tokens),
                    "texts": [],
                    "count": 0,
                    "first_seen_at": item["report_date"],
                    "last_seen_at": item["report_date"],
                    "report_item_ids": [],
                }
                clusters.append(best_cluster)
            best_cluster["tokens"].update(tokens)
            best_cluster["texts"].append(point)
            best_cluster["count"] += 1
            if item["id"] not in best_cluster["report_item_ids"]:
                best_cluster["report_item_ids"].append(item["id"])
            best_cluster["first_seen_at"] = min(best_cluster["first_seen_at"], item["report_date"])
            best_cluster["last_seen_at"] = max(best_cluster["last_seen_at"], item["report_date"])

    latest_date = max((item["report_date"] for item in items), default="")
    output = []
    for cluster in clusters:
        recency_bonus = 1 if cluster["last_seen_at"] == latest_date else 0
        output.append(
            {
                "text": concise_monitor_text(cluster["texts"], cluster["topic_key"]),
                "count": cluster["count"],
                "first_seen_at": cluster["first_seen_at"],
                "last_seen_at": cluster["last_seen_at"],
                "report_item_ids": cluster["report_item_ids"],
                "score": (cluster["count"] * 10) + recency_bonus,
            }
        )
    return sorted(output, key=lambda item: (item["score"], item["last_seen_at"]), reverse=True)[:limit]


def serialize_report_company_item(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "report_id": str(row["report_id"]),
        "stock_id": str(row["stock_id"]),
        "company_memory_item_id": str(row["company_memory_item_id"]) if row.get("company_memory_item_id") else None,
        "section": row.get("section"),
        "ticker": str(row.get("ticker") or "").upper(),
        "company_name": row.get("company_name"),
        "headline": row.get("headline"),
        "why_it_matters": row.get("why_it_matters"),
        "article_summary": row.get("article_summary") or [],
        "source": row.get("source"),
        "source_url": row.get("source_url"),
        "attention_label": row.get("attention_label"),
        "importance": row.get("importance"),
        "thesis_impact": row.get("thesis_impact"),
        "thesis_summary": row.get("thesis_summary"),
        "thesis_points_affected": row.get("thesis_points_affected") or [],
        "monitor_next": row.get("monitor_next"),
        "report_date": row["report_date"].isoformat() if hasattr(row["report_date"], "isoformat") else row["report_date"],
        "created_at": row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else row["created_at"],
    }


def serialize_context_memory_row(row: dict[str, Any]) -> dict[str, Any]:
    symbol = str(row["symbol"]).upper()
    return {
        "id": str(row["id"]),
        "stock_id": str(row["stock_id"]),
        "symbol": symbol,
        "company_name": row["company_name"],
        "logo_url": stock_logo_url(symbol),
        "theme": row.get("theme"),
        "description": row.get("description"),
        "latest_development": row.get("latest_development"),
        "thesis_points": row.get("thesis_points") or [],
        "thesis_linked": bool(row.get("thesis_linked")),
        "importance": row.get("importance"),
        "status": row.get("status"),
        "evidence_count": int(row.get("evidence_count") or 0),
        "first_seen_at": row["first_seen_at"].isoformat() if hasattr(row["first_seen_at"], "isoformat") else row["first_seen_at"],
        "last_seen_at": row["last_seen_at"].isoformat() if hasattr(row["last_seen_at"], "isoformat") else row["last_seen_at"],
    }


def company_context_earnings(symbol: str) -> dict[str, Any]:
    try:
        client = fmp_client_from_env()
        return fetch_research_earnings_reports(client, symbol, dt.date.today())
    except Exception as exc:
        logger.info("Company context earnings unavailable symbol=%s error=%s", symbol, exc)
        return {"next_earnings_date": None, "reports": []}


@app.get("/api/stocks/{stock_id}/context")
def get_stock_context(stock_id: str, request: Request) -> dict[str, Any]:
    user_id = current_user_id(request)
    from psycopg.rows import dict_row

    with connection(row_factory=dict_row) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                select
                    stocks.id::text as stock_id,
                    stocks.symbol,
                    stocks.company_name,
                    portfolio_items.id::text as portfolio_item_id,
                    watchlist_items.id::text as watchlist_item_id,
                    portfolio_items.position_size_pct,
                    portfolio_items.why_i_own_it,
                    portfolio_items.bull_case as portfolio_bull_case,
                    portfolio_items.bear_case as portfolio_bear_case,
                    portfolio_items.key_metrics as portfolio_key_metrics,
                    portfolio_items.red_flags as portfolio_red_flags,
                    portfolio_items.action_triggers,
                    watchlist_items.why_i_watch_it,
                    watchlist_items.bull_case as watchlist_bull_case,
                    watchlist_items.bear_case as watchlist_bear_case,
                    watchlist_items.key_metrics as watchlist_key_metrics,
                    watchlist_items.red_flags as watchlist_red_flags,
                    watchlist_items.entry_conditions
                from public.stocks
                left join public.portfolio_items
                  on portfolio_items.stock_id = stocks.id
                 and portfolio_items.user_id = %(user_id)s
                left join public.watchlist_items
                  on watchlist_items.stock_id = stocks.id
                 and watchlist_items.user_id = %(user_id)s
                where stocks.id::text = %(stock_id)s
                  and (portfolio_items.id is not null or watchlist_items.id is not null)
                """,
                {"stock_id": stock_id, "user_id": user_id},
            )
            stock_row = cursor.fetchone()
            if not stock_row:
                raise HTTPException(status_code=404, detail="Stock not found in your portfolio or watchlist.")

            cursor.execute(
                """
                select *
                from public.report_company_items
                where user_id = %(user_id)s
                  and stock_id::text = %(stock_id)s
                order by report_date desc, created_at desc
                limit 100
                """,
                {"stock_id": stock_id, "user_id": user_id},
            )
            item_rows = cursor.fetchall()

            cursor.execute(
                NOTE_SELECT
                + """
                where notes.user_id = %(user_id)s
                  and notes.stock_id::text = %(stock_id)s
                order by notes.created_at desc
                limit 100
                """,
                {"stock_id": stock_id, "user_id": user_id},
            )
            note_rows = cursor.fetchall()

            cursor.execute(
                """
                select
                    company_memory_items.id::text as id,
                    company_memory_items.stock_id::text as stock_id,
                    stocks.symbol,
                    stocks.company_name,
                    company_memory_items.theme,
                    company_memory_items.description,
                    company_memory_items.latest_development,
                    company_memory_items.thesis_points,
                    company_memory_items.thesis_linked,
                    company_memory_items.importance,
                    company_memory_items.status,
                    company_memory_items.evidence_count,
                    company_memory_items.first_seen_at,
                    company_memory_items.last_seen_at
                from public.company_memory_items
                join public.stocks on stocks.id = company_memory_items.stock_id
                where company_memory_items.user_id = %(user_id)s
                  and company_memory_items.stock_id::text = %(stock_id)s
                order by
                    case company_memory_items.status when 'active' then 0 when 'stale' then 1 else 2 end,
                    company_memory_items.importance desc,
                    company_memory_items.last_seen_at desc
                limit 30
                """,
                {"stock_id": stock_id, "user_id": user_id},
            )
            memory_rows = cursor.fetchall()

    stock = dict(stock_row)
    symbol = str(stock["symbol"]).upper()
    items = [serialize_report_company_item(dict(row)) for row in item_rows]
    notes = [serialize_note_row(dict(row)) for row in note_rows]

    relationship = "portfolio" if stock.get("portfolio_item_id") else "watchlist"
    thesis = (
        {
            "why_i_own_it": stock.get("why_i_own_it") or [],
            "bull_case": stock.get("portfolio_bull_case") or [],
            "bear_case": stock.get("portfolio_bear_case") or [],
            "key_metrics": stock.get("portfolio_key_metrics") or [],
            "red_flags": stock.get("portfolio_red_flags") or [],
            "action_triggers": stock.get("action_triggers") or [],
        }
        if relationship == "portfolio"
        else {
            "why_i_watch_it": stock.get("why_i_watch_it") or [],
            "bull_case": stock.get("watchlist_bull_case") or [],
            "bear_case": stock.get("watchlist_bear_case") or [],
            "key_metrics": stock.get("watchlist_key_metrics") or [],
            "red_flags": stock.get("watchlist_red_flags") or [],
            "entry_conditions": stock.get("entry_conditions") or [],
        }
    )
    earnings = company_context_earnings(symbol)
    return {
        "stock": {
            "stock_id": str(stock["stock_id"]),
            "symbol": symbol,
            "company_name": stock["company_name"],
            "logo_url": stock_logo_url(symbol),
            "relationship": relationship,
            "position_size_pct": stock.get("position_size_pct"),
            "thesis": thesis,
        },
        "summary": {
            "report_item_count": len(items),
            "memory_count": len(memory_rows),
            "unresolved_note_count": sum(1 for note in notes if not note.get("is_resolved")),
            "latest_signal": items[0].get("attention_label") if items else None,
            "next_earnings_date": earnings.get("next_earnings_date"),
        },
        "report_items": items,
        "notes": notes,
        "memories": [serialize_context_memory_row(dict(row)) for row in memory_rows],
        "monitor_items": build_monitor_summary(items),
        "next_earnings_date": earnings.get("next_earnings_date"),
    }


def load_company_memory_detail(cursor: Any, *, user_id: str, memory_id: str) -> dict[str, Any]:
    cursor.execute(
        """
        select
            company_memory_items.id::text as id,
            company_memory_items.stock_id::text as stock_id,
            stocks.symbol,
            stocks.company_name,
            company_memory_items.theme,
            company_memory_items.description,
            company_memory_items.latest_development,
            company_memory_items.thesis_points,
            company_memory_items.thesis_linked,
            company_memory_items.importance,
            company_memory_items.status,
            company_memory_items.evidence_count,
            company_memory_items.first_seen_at,
            company_memory_items.last_seen_at,
            company_memory_items.created_at,
            company_memory_items.updated_at
        from public.company_memory_items
        join public.stocks on stocks.id = company_memory_items.stock_id
        where company_memory_items.id::text = %(id)s
          and company_memory_items.user_id = %(user_id)s
        """,
        {"id": memory_id, "user_id": user_id},
    )
    memory_row = cursor.fetchone()
    if not memory_row:
        raise HTTPException(status_code=404, detail="Company memory not found.")

    cursor.execute(
        """
        select
            company_memory_events.id::text as id,
            company_memory_events.report_id::text as report_id,
            company_memory_events.event_date,
            company_memory_events.event_type,
            company_memory_events.relationship,
            company_memory_events.headline,
            company_memory_events.summary,
            company_memory_events.source_url,
            company_memory_events.source,
            company_memory_events.importance,
            company_memory_events.thesis_points,
            company_memory_events.metadata,
            company_memory_events.created_at
        from public.company_memory_events
        where company_memory_events.company_memory_item_id::text = %(id)s
          and company_memory_events.user_id = %(user_id)s
        order by company_memory_events.event_date asc, company_memory_events.created_at asc
        """,
        {"id": memory_id, "user_id": user_id},
    )
    event_rows = cursor.fetchall()
    memory = dict(memory_row)
    symbol = str(memory["symbol"]).upper()
    return {
        "memory": {
            "id": str(memory["id"]),
            "stock_id": str(memory["stock_id"]),
            "symbol": symbol,
            "company_name": memory.get("company_name"),
            "logo_url": stock_logo_url(symbol),
            "theme": memory.get("theme"),
            "description": memory.get("description"),
            "latest_development": memory.get("latest_development"),
            "thesis_points": memory.get("thesis_points") or [],
            "thesis_linked": bool(memory.get("thesis_linked")),
            "importance": memory.get("importance"),
            "status": memory.get("status"),
            "evidence_count": int(memory.get("evidence_count") or 0),
            "first_seen_at": memory["first_seen_at"].isoformat() if hasattr(memory["first_seen_at"], "isoformat") else memory["first_seen_at"],
            "last_seen_at": memory["last_seen_at"].isoformat() if hasattr(memory["last_seen_at"], "isoformat") else memory["last_seen_at"],
            "events": [
                {
                    "id": str(row["id"]),
                    "report_id": str(row["report_id"]) if row.get("report_id") else None,
                    "event_date": row["event_date"].isoformat() if hasattr(row["event_date"], "isoformat") else row["event_date"],
                    "event_type": row.get("event_type"),
                    "relationship": row.get("relationship"),
                    "headline": row.get("headline"),
                    "summary": row.get("summary"),
                    "source_url": row.get("source_url"),
                    "source": row.get("source"),
                    "importance": row.get("importance"),
                    "thesis_points": row.get("thesis_points") or [],
                    "metadata": row.get("metadata") or {},
                    "created_at": row["created_at"].isoformat() if hasattr(row["created_at"], "isoformat") else row["created_at"],
                }
                for row in event_rows
            ],
        }
    }


def unique_json_strings(values: list[Any], limit: int = 24) -> list[str]:
    output = []
    seen = set()
    for value in values:
        text = str(value or "").strip()
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        output.append(text)
        if len(output) >= limit:
            break
    return output


def recalculate_company_memory_item(cursor: Any, *, user_id: str, memory_id: str) -> None:
    cursor.execute(
        """
        select
            id::text as id,
            report_id::text as report_id,
            event_date,
            summary,
            source_url,
            importance,
            thesis_points,
            created_at
        from public.company_memory_events
        where company_memory_item_id::text = %(memory_id)s
          and user_id = %(user_id)s
        order by event_date asc, created_at asc
        """,
        {"memory_id": memory_id, "user_id": user_id},
    )
    rows = [dict(row) for row in cursor.fetchall()]
    if not rows:
        raise HTTPException(status_code=409, detail="Cannot remove the only tracked context item.")
    latest = rows[-1]
    source_urls = unique_json_strings([row.get("source_url") for row in rows if row.get("source_url")], limit=20)
    thesis_points = unique_json_strings(
        [
            point
            for row in rows
            for point in (row.get("thesis_points") or [])
        ],
        limit=16,
    )
    cursor.execute(
        """
        update public.company_memory_items
        set
            latest_development = %(latest_development)s,
            thesis_points = %(thesis_points)s::jsonb,
            source_urls = %(source_urls)s::jsonb,
            last_source_url = %(last_source_url)s,
            importance = %(importance)s,
            evidence_count = %(evidence_count)s,
            last_seen_at = %(last_seen_at)s,
            last_report_id = %(last_report_id)s,
            updated_at = now()
        where id::text = %(memory_id)s
          and user_id = %(user_id)s
        """,
        {
            "memory_id": memory_id,
            "user_id": user_id,
            "latest_development": latest.get("summary"),
            "thesis_points": json.dumps(thesis_points),
            "source_urls": json.dumps(source_urls),
            "last_source_url": latest.get("source_url"),
            "importance": "high" if any(row.get("importance") == "high" for row in rows) else "medium",
            "evidence_count": len(rows),
            "last_seen_at": latest.get("event_date"),
            "last_report_id": latest.get("report_id"),
        },
    )


@app.get("/api/company-memory/{memory_id}")
def get_company_memory(memory_id: str, request: Request) -> dict[str, Any]:
    user_id = current_user_id(request)
    from psycopg.rows import dict_row

    with connection(row_factory=dict_row) as conn:
        with conn.cursor() as cursor:
            return load_company_memory_detail(cursor, user_id=user_id, memory_id=memory_id)


@app.delete("/api/company-memory/{memory_id}/events/{event_id}")
def delete_company_memory_event(memory_id: str, event_id: str, request: Request) -> dict[str, Any]:
    user_id = current_user_id(request)
    from psycopg.rows import dict_row

    with connection(row_factory=dict_row) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                select id::text as id
                from public.company_memory_items
                where id::text = %(memory_id)s
                  and user_id = %(user_id)s
                for update
                """,
                {"memory_id": memory_id, "user_id": user_id},
            )
            if not cursor.fetchone():
                raise HTTPException(status_code=404, detail="Company memory not found.")
            cursor.execute(
                """
                select id::text as id
                from public.company_memory_events
                where company_memory_item_id::text = %(memory_id)s
                  and user_id = %(user_id)s
                order by event_date asc, created_at asc
                """,
                {"memory_id": memory_id, "user_id": user_id},
            )
            event_ids = [str(row["id"]) for row in cursor.fetchall()]
            if event_id not in event_ids:
                raise HTTPException(status_code=404, detail="Tracked context item not found.")
            if event_ids.index(event_id) == 0:
                raise HTTPException(status_code=422, detail="The first tracked context item defines this theme and cannot be removed.")
            cursor.execute(
                """
                delete from public.company_memory_events
                where id::text = %(event_id)s
                  and company_memory_item_id::text = %(memory_id)s
                  and user_id = %(user_id)s
                """,
                {"event_id": event_id, "memory_id": memory_id, "user_id": user_id},
            )
            recalculate_company_memory_item(cursor, user_id=user_id, memory_id=memory_id)
            return load_company_memory_detail(cursor, user_id=user_id, memory_id=memory_id)


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


@app.get("/api/research-runs/{run_id}")
def get_research_run(run_id: str, request: Request) -> dict[str, Any]:
    user_id = current_user_id(request)
    from psycopg.rows import dict_row

    with connection(row_factory=dict_row) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                select
                    research_runs.id::text as id,
                    research_runs.user_id::text as user_id,
                    research_runs.stock_id::text as stock_id,
                    research_runs.research_item_id::text as research_item_id,
                    research_runs.usage_id::text as usage_id,
                    research_runs.research_type,
                    research_runs.status,
                    research_runs.progress_step,
                    research_runs.progress_pct,
                    research_runs.model,
                    research_runs.request,
                    research_runs.usage,
                    research_runs.error,
                    research_runs.created_at,
                    research_runs.started_at,
                    research_runs.completed_at,
                    research_runs.updated_at,
                    stocks.symbol,
                    stocks.company_name,
                    research_items.body as item_body,
                    research_items.research_type as item_research_type,
                    research_items.signal as item_signal,
                    research_items.date_from as item_date_from,
                    research_items.date_to as item_date_to,
                    research_items.created_at as item_created_at,
                    count(notes.id)::int as note_count
                from public.research_runs
                join public.stocks on stocks.id = research_runs.stock_id
                left join public.research_items on research_items.id = research_runs.research_item_id
                left join public.notes
                  on notes.research_item_id = research_items.id
                 and notes.user_id = research_runs.user_id
                where research_runs.id::text = %(id)s
                  and research_runs.user_id = %(user_id)s
                group by research_runs.id, stocks.id, research_items.id
                """,
                {"id": run_id, "user_id": user_id},
            )
            row = cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Research run not found.")
    return {"run": serialize_research_run_row(dict(row))}


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


@app.post("/api/feedback")
def send_feedback(payload: FeedbackRequest, request: Request) -> dict[str, Any]:
    user_id = current_user_id(request)
    sender_profile = get_user_profile(user_id) or {}
    sender_email = validate_feedback_email(payload.email)
    category = validate_feedback_category(payload.category)
    message = validate_feedback_message(payload.message)
    category_label = FEEDBACK_CATEGORY_LABELS[category]

    from report import send_email

    subject = f"Morning Alpha feedback: {category_label}"
    email_html = f"""
    <div style="background:#0d0d0d;color:#eeeeea;font-family:Arial,sans-serif;padding:24px;">
      <div style="max-width:720px;margin:0 auto;background:#181818;border:1px solid #2a2a2a;border-radius:12px;padding:22px;">
        <h1 style="color:#ffffff;font-size:22px;margin:0 0 18px;">Morning Alpha Feedback</h1>
        <table style="border-collapse:collapse;width:100%;margin-bottom:18px;">
          <tr>
            <td style="color:#a7a7a0;padding:6px 0;width:150px;">Category</td>
            <td style="color:#ffffff;padding:6px 0;">{html_email_text(category_label)}</td>
          </tr>
          <tr>
            <td style="color:#a7a7a0;padding:6px 0;">Contact email</td>
            <td style="color:#ffffff;padding:6px 0;">{html_email_text(sender_email)}</td>
          </tr>
          <tr>
            <td style="color:#a7a7a0;padding:6px 0;">Account email</td>
            <td style="color:#ffffff;padding:6px 0;">{html_email_text(sender_profile.get("email") or "")}</td>
          </tr>
          <tr>
            <td style="color:#a7a7a0;padding:6px 0;">User ID</td>
            <td style="color:#ffffff;padding:6px 0;">{html_email_text(user_id)}</td>
          </tr>
        </table>
        <div style="border-top:1px solid #303030;padding-top:18px;">
          <h2 style="color:#f4c430;font-size:16px;margin:0 0 10px;">Message</h2>
          <p style="color:#eeeeea;font-size:15px;line-height:1.6;margin:0;white-space:pre-wrap;">{html_email_text(message)}</p>
        </div>
      </div>
    </div>
    """
    try:
        send_email(subject, email_html, recipient_email=FEEDBACK_RECIPIENT_EMAIL, from_email="report@morning-alpha.com")
    except SystemExit as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Unable to send feedback email: {exc}") from exc
    return {"sent": True}


@app.post("/api/research-items/{research_item_id}/share")
def share_research_item(research_item_id: str, payload: ShareResearchRequest, request: Request) -> dict[str, Any]:
    user_id = current_user_id(request)
    recipient_email = validate_share_email(payload.recipient_email)
    from psycopg.rows import dict_row
    from report import send_email

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
            research_row = cursor.fetchone()
            if not research_row:
                raise HTTPException(status_code=404, detail="Research item not found.")
            cursor.execute(
                NOTE_SELECT
                + """
                where notes.research_item_id::text = %(id)s
                  and notes.user_id = %(user_id)s
                order by notes.created_at desc
                """,
                {"id": research_item_id, "user_id": user_id},
            )
            note_rows = cursor.fetchall()

    research_item = serialize_research_item_row(dict(research_row), include_body=True)
    if research_item["research_type"] == "deep_research":
        raise HTTPException(status_code=422, detail="Sharing deep research by email is not available yet.")
    notes = [serialize_note_row(dict(row)) for row in note_rows]
    sender = get_user_profile(user_id)
    sender_name = (sender or {}).get("display_name") or (sender or {}).get("email") or "Morning Alpha user"
    subject = f"{research_email_label(research_item['research_type'])} for {research_item['symbol']} shared by {sender_name}"
    email_html = render_shared_research_email(
        research_item=research_item,
        notes=notes,
        sender=sender,
        message=(payload.message or "").strip() or None,
    )
    try:
        send_email(subject, email_html, recipient_email=recipient_email)
    except SystemExit as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Unable to send research email: {exc}") from exc
    return {"sent": True}


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
            or exists (
                select 1 from public.notes
                where user_id = %(user_id)s and stock_id = public.stocks.id
            )
          )
        """,
        {"stock_id": stock_id, "user_id": user_id},
    )
    if not cursor.fetchone():
        raise HTTPException(status_code=404, detail="Stock not found in your portfolio, watchlist, or notes.")


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
                        when watchlist_items.id is not null then 'watchlist'
                        else 'notes'
                    end as list_name
                from public.stocks
                left join public.portfolio_items
                  on portfolio_items.stock_id = stocks.id
                 and portfolio_items.user_id = %(user_id)s
                left join public.watchlist_items
                  on watchlist_items.stock_id = stocks.id
                 and watchlist_items.user_id = %(user_id)s
                left join public.notes
                  on notes.stock_id = stocks.id
                 and notes.user_id = %(user_id)s
                where portfolio_items.id is not null
                   or watchlist_items.id is not null
                   or notes.id is not null
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
    source: str | None = None,
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
    if source:
        normalized_source = source.strip().lower()
        if normalized_source == "standalone":
            where_clauses.append("notes.report_id is null and notes.research_item_id is null")
        elif normalized_source == "report":
            where_clauses.append("notes.report_id is not null and notes.research_item_id is null")
        elif normalized_source == "research":
            where_clauses.append("notes.research_item_id is not null")
        elif normalized_source != "all":
            raise HTTPException(status_code=422, detail="Unsupported notes source filter.")
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
    uvicorn.run(app, host=host, port=port, access_log=True, log_level=os.getenv("API_LOG_LEVEL", "INFO").lower())
