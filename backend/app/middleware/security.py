"""Cookie helpers, CSRF protection and security response headers."""

import hmac
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.config import settings

SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}

# Docs UIs pull assets from a CDN, so the strict API CSP cannot apply to them.
CSP_EXEMPT_PATHS = {"/docs", "/redoc", "/openapi.json"}

# Login is exempt from double-submit CSRF: a stale CSRF cookie alongside a
# still-present session cookie would otherwise lock a user out of signing in
# again. The residual risk is "login CSRF" (forcing a victim into the
# attacker's session), which SameSite=Lax already blocks by withholding cookies
# from cross-site POSTs.
CSRF_EXEMPT_PATHS = {"/api/v1/auth/login"}


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def _cookie_kwargs() -> dict:
    kwargs = {
        "secure": settings.COOKIE_SECURE,
        "samesite": settings.COOKIE_SAMESITE,
        "path": "/",
    }
    if settings.COOKIE_DOMAIN:
        kwargs["domain"] = settings.COOKIE_DOMAIN
    return kwargs


def set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> str:
    """Attach the auth cookie pair plus a readable CSRF token. Returns the CSRF token."""
    common = _cookie_kwargs()

    response.set_cookie(
        settings.ACCESS_COOKIE_NAME,
        access_token,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        httponly=True,
        **common,
    )
    response.set_cookie(
        settings.REFRESH_COOKIE_NAME,
        refresh_token,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600,
        httponly=True,
        **common,
    )

    csrf_token = generate_csrf_token()
    # Deliberately not httpOnly: the SPA must read this to echo it back in the
    # X-CSRF-Token header. It carries no authority on its own.
    response.set_cookie(
        settings.CSRF_COOKIE_NAME,
        csrf_token,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600,
        httponly=False,
        **common,
    )
    return csrf_token


def set_two_factor_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        settings.TWO_FACTOR_COOKIE_NAME,
        token,
        max_age=settings.TWO_FACTOR_TOKEN_EXPIRE_MINUTES * 60,
        httponly=True,
        **_cookie_kwargs(),
    )


def clear_auth_cookies(response: Response) -> None:
    common = _cookie_kwargs()
    common.pop("samesite", None)
    common.pop("secure", None)
    for name in (
        settings.ACCESS_COOKIE_NAME,
        settings.REFRESH_COOKIE_NAME,
        settings.TWO_FACTOR_COOKIE_NAME,
        settings.CSRF_COOKIE_NAME,
    ):
        response.delete_cookie(name, **common)


class CSRFMiddleware(BaseHTTPMiddleware):
    """Double-submit cookie CSRF protection.

    Only enforced when the request authenticates via cookies. Requests using an
    `Authorization: Bearer` header are not CSRF-able (a browser will not attach
    that header cross-origin automatically), so machine clients are unaffected.
    """

    async def dispatch(self, request: Request, call_next):
        if request.method in SAFE_METHODS or request.url.path in CSRF_EXEMPT_PATHS:
            return await call_next(request)

        has_auth_cookie = bool(
            request.cookies.get(settings.ACCESS_COOKIE_NAME)
            or request.cookies.get(settings.REFRESH_COOKIE_NAME)
        )
        if not has_auth_cookie:
            return await call_next(request)

        cookie_token = request.cookies.get(settings.CSRF_COOKIE_NAME)
        header_token = request.headers.get(settings.CSRF_HEADER_NAME)

        if not cookie_token or not header_token or not hmac.compare_digest(
            cookie_token, header_token
        ):
            return JSONResponse(
                status_code=403,
                content={"detail": "CSRF token missing or invalid"},
            )

        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = (
            "geolocation=(), microphone=(), camera=(), payment=()"
        )
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Cross-Origin-Resource-Policy"] = "same-site"

        if request.url.path not in CSP_EXEMPT_PATHS:
            # This service only ever returns JSON; nothing should be loadable.
            response.headers["Content-Security-Policy"] = (
                "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
            )

        if settings.COOKIE_SECURE:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )

        return response
