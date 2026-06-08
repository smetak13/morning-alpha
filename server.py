from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from database import connection
from neon_auth import load_settings


ROOT = Path(__file__).resolve().parent
FRONTEND_DIST = ROOT / "frontend" / "dist"
FRONTEND_INDEX = FRONTEND_DIST / "index.html"

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
                    onboarding_completed_at,
                    created_at,
                    updated_at
                from public.users
                where id = %(id)s
                """,
                {"id": str(user_id)},
            )
            row = cursor.fetchone()

    return dict(row) if row else None


def create_user_profile_if_missing(user: dict[str, Any]) -> dict[str, Any] | None:
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
    }

    with connection(row_factory=dict_row) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                insert into public.users (id, email, display_name)
                values (%(id)s, %(email)s, %(display_name)s)
                on conflict (id) do nothing
                returning
                    id,
                    email,
                    display_name,
                    timezone,
                    locale,
                    onboarding_completed_at,
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
            GoogleIdTokenRequest(id_token=payload.id_token, access_token=payload.access_token),
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
    profile = create_user_profile_if_missing(user) if user else None
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
        profile = create_user_profile_if_missing(user)
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
