from __future__ import annotations

import os
from dataclasses import dataclass


def _parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True)
class NeonAuthSettings:
    base_url: str | None
    frontend_url: str | None
    cookie_secret: str | None
    email_password_enabled: bool
    google_oauth_enabled: bool

    @property
    def auth_url(self) -> str | None:
        return self.frontend_url or self.base_url

    def missing_required(self) -> list[str]:
        missing: list[str] = []
        if not self.auth_url:
            missing.append("NEON_AUTH_BASE_URL")
        return missing

    def missing_for_server_cookie_sessions(self) -> list[str]:
        missing = self.missing_required()
        if not self.cookie_secret:
            missing.append("NEON_AUTH_COOKIE_SECRET")
        return missing


def load_settings() -> NeonAuthSettings:
    return NeonAuthSettings(
        base_url=os.getenv("NEON_AUTH_BASE_URL"),
        frontend_url=os.getenv("NEON_AUTH_URL"),
        cookie_secret=os.getenv("NEON_AUTH_COOKIE_SECRET"),
        email_password_enabled=_parse_bool(os.getenv("NEON_AUTH_EMAIL_PASSWORD_ENABLED"), default=True),
        google_oauth_enabled=_parse_bool(os.getenv("NEON_AUTH_GOOGLE_OAUTH_ENABLED"), default=True),
    )
