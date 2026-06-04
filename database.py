from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


DATABASE_URL_ENV_NAMES = ("DATABASE_URL", "POSTGRES_URL", "NEON_DATABASE_URL")


def database_url(required: bool = True) -> str | None:
    for name in DATABASE_URL_ENV_NAMES:
        value = os.getenv(name)
        if value:
            return value.strip()
    if required:
        names = ", ".join(DATABASE_URL_ENV_NAMES)
        raise RuntimeError(f"Missing database connection string. Set one of: {names}.")
    return None


def _with_default_sslmode(conninfo: str) -> str:
    parsed = urlparse(conninfo)
    if parsed.scheme not in {"postgres", "postgresql"}:
        return conninfo

    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.setdefault("sslmode", "require")
    return urlunparse(parsed._replace(query=urlencode(query)))


def normalized_database_url(required: bool = True) -> str | None:
    conninfo = database_url(required=required)
    if conninfo is None:
        return None
    return _with_default_sslmode(conninfo)


def sqlalchemy_database_url(required: bool = True) -> str | None:
    conninfo = normalized_database_url(required=required)
    if conninfo is None:
        return None

    parsed = urlparse(conninfo)
    if parsed.scheme in {"postgres", "postgresql"}:
        return urlunparse(parsed._replace(scheme="postgresql+psycopg"))
    return conninfo


def connect(row_factory: Any | None = None) -> Any:
    conninfo = normalized_database_url(required=True) or ""

    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("Missing dependency 'psycopg'. Install dependencies with: pip install -r requirements.txt") from exc

    timeout = int(os.getenv("DATABASE_CONNECT_TIMEOUT_SECONDS", "10"))
    kwargs: dict[str, Any] = {"connect_timeout": timeout}
    if row_factory is not None:
        kwargs["row_factory"] = row_factory
    return psycopg.connect(conninfo, **kwargs)


@contextmanager
def connection(row_factory: Any | None = None) -> Iterator[Any]:
    with connect(row_factory=row_factory) as conn:
        yield conn


def check_connection() -> dict[str, str]:
    database_url(required=True)

    try:
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise RuntimeError("Missing dependency 'psycopg'. Install dependencies with: pip install -r requirements.txt") from exc

    with connection(row_factory=dict_row) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                select
                    current_database() as database,
                    current_user as role,
                    inet_server_addr()::text as host,
                    version() as version
                """
            )
            row = cursor.fetchone()

    if not row:
        raise RuntimeError("Database connection check returned no rows.")
    return {key: str(value) for key, value in row.items()}
