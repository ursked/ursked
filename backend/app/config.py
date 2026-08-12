import logging
import secrets
from typing import List, Optional

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)

# Secrets that have been published in this repo's history or are obvious
# placeholders. Refusing these outright prevents a deploy from silently
# running with a signing key that an attacker already knows.
KNOWN_WEAK_SECRETS = {
    "dev-secret-key-change-in-production-abc123",
    "change-me",
    "changeme",
    "secret",
    "dev-secret-key",
    "your-secret-key",
}

MIN_SECRET_LENGTH = 32


class Settings(BaseSettings):
    APP_NAME: str = "Employee Scheduling SaaS"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    ENVIRONMENT: str = "development"
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/employee_scheduling"
    DATABASE_POOL_SIZE: int = 5
    DATABASE_MAX_OVERFLOW: int = 10

    REDIS_URL: str = "redis://localhost:6379/0"

    # No default. A generated-per-process default silently breaks multi-worker
    # deploys (each worker signs with a different key) and masks a missing
    # config value, so this must be supplied explicitly.
    JWT_SECRET_KEY: str = ""
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    TWO_FACTOR_TOKEN_EXPIRE_MINUTES: int = 5

    # --- Cookie-based auth ---
    COOKIE_SECURE: bool = True
    COOKIE_SAMESITE: str = "lax"

    # Escape hatch for self-hosting on a trusted network with no TLS (e.g. a LAN
    # trial). When true, the production guards on COOKIE_SECURE=false and on
    # http:// CORS origins are downgraded from hard errors to loud startup
    # warnings, so the app runs with ENVIRONMENT=production instead of forcing
    # development mode. It never relaxes the DEBUG guard or the wildcard-CORS
    # guard. Leave this false for any internet-facing deployment.
    ALLOW_INSECURE_TRANSPORT: bool = False
    COOKIE_DOMAIN: Optional[str] = None
    ACCESS_COOKIE_NAME: str = "access_token"
    REFRESH_COOKIE_NAME: str = "refresh_token"
    TWO_FACTOR_COOKIE_NAME: str = "two_factor_token"
    CSRF_COOKIE_NAME: str = "csrf_token"
    CSRF_HEADER_NAME: str = "X-CSRF-Token"

    # --- Brute-force protection ---
    LOGIN_RATE_LIMIT_ATTEMPTS: int = 10
    LOGIN_RATE_LIMIT_WINDOW_SECONDS: int = 300
    ACCOUNT_LOCKOUT_ATTEMPTS: int = 5
    ACCOUNT_LOCKOUT_MINUTES: int = 15
    TWO_FACTOR_RATE_LIMIT_ATTEMPTS: int = 5
    TWO_FACTOR_RATE_LIMIT_WINDOW_SECONDS: int = 300

    # --- API surface ---
    EXPOSE_API_DOCS: bool = False

    TOTP_ISSUER: str = "Employee Scheduling SaaS"
    ENCRYPTION_KEY: Optional[str] = None

    CORS_ORIGINS: List[str] = ["http://localhost:3000"]

    STRIPE_SECRET_KEY: Optional[str] = None
    STRIPE_WEBHOOK_SECRET: Optional[str] = None

    SENTRY_DSN: Optional[str] = None

    UPLOAD_FOLDER: str = "uploads"
    MAX_CONTENT_LENGTH: int = 16777216  # 16MB

    class Config:
        env_file = ".env"
        case_sensitive = True

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() in {"production", "prod", "staging"}

    @field_validator("COOKIE_SAMESITE")
    @classmethod
    def _validate_samesite(cls, v: str) -> str:
        allowed = {"lax", "strict", "none"}
        value = v.lower()
        if value not in allowed:
            raise ValueError(f"COOKIE_SAMESITE must be one of {sorted(allowed)}")
        return value

    @model_validator(mode="after")
    def _validate_security_config(self) -> "Settings":
        secret = (self.JWT_SECRET_KEY or "").strip()

        if secret.lower() in KNOWN_WEAK_SECRETS:
            raise ValueError(
                "JWT_SECRET_KEY is set to a known placeholder value. This key is "
                "public and allows anyone to forge tokens for any user. Generate a "
                "new one with: python -c \"import secrets; print(secrets.token_urlsafe(64))\""
            )

        if not secret:
            if self.is_production:
                raise ValueError(
                    "JWT_SECRET_KEY must be set in production. Generate one with: "
                    "python -c \"import secrets; print(secrets.token_urlsafe(64))\""
                )
            # Dev convenience only: ephemeral key, invalidates tokens on restart.
            self.JWT_SECRET_KEY = secrets.token_urlsafe(64)
            logger.warning(
                "JWT_SECRET_KEY is unset; generated an ephemeral development key. "
                "All sessions will be invalidated on restart."
            )
        elif len(secret) < MIN_SECRET_LENGTH:
            raise ValueError(
                f"JWT_SECRET_KEY must be at least {MIN_SECRET_LENGTH} characters "
                f"(got {len(secret)})."
            )

        if self.is_production:
            # DEBUG is never negotiable: it leaks exception detail and enables
            # wildcard CORS. ALLOW_INSECURE_TRANSPORT does not touch this.
            if self.DEBUG:
                raise ValueError(
                    "DEBUG must be false in production: it enables wildcard CORS "
                    "and leaks exception details to clients."
                )
            # A wildcard origin is always a hard error — it is never part of a
            # legitimate no-TLS trial and defeats CSRF/cookie protections.
            if any(o.strip() == "*" for o in self.CORS_ORIGINS):
                raise ValueError("CORS_ORIGINS must not contain '*' in production.")

            insecure_cors = [o for o in self.CORS_ORIGINS if o.startswith("http://")]

            if self.ALLOW_INSECURE_TRANSPORT:
                # Trusted-network / no-TLS opt-in: downgrade the transport-security
                # guards to loud warnings so the app still runs as production.
                if not self.COOKIE_SECURE:
                    logger.warning(
                        "ALLOW_INSECURE_TRANSPORT is set: running with "
                        "COOKIE_SECURE=false. Auth cookies will be sent over "
                        "plain HTTP. Use this ONLY on a trusted network; put TLS "
                        "in front and set COOKIE_SECURE=true for anything "
                        "internet-facing."
                    )
                if insecure_cors:
                    logger.warning(
                        "ALLOW_INSECURE_TRANSPORT is set: allowing http:// CORS "
                        "origins %s. Use https origins behind TLS in production.",
                        insecure_cors,
                    )
            else:
                if not self.COOKIE_SECURE:
                    raise ValueError(
                        "COOKIE_SECURE must be true in production. For a no-TLS "
                        "trial on a trusted network, set ALLOW_INSECURE_TRANSPORT=true."
                    )
                if insecure_cors:
                    raise ValueError(
                        f"CORS_ORIGINS must use https in production; got: {insecure_cors}. "
                        "For a no-TLS trial, set ALLOW_INSECURE_TRANSPORT=true."
                    )

        if self.COOKIE_SAMESITE == "none" and not self.COOKIE_SECURE:
            raise ValueError("COOKIE_SAMESITE=none requires COOKIE_SECURE=true.")

        return self


settings = Settings()
