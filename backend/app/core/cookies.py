"""httpOnly cookie auth — v0.10.

The browser never sees a token: login / register / refresh set the
access token (15 min) and refresh token (24 h, rotating jti) as
HttpOnly cookies, and logout clears them. JavaScript cannot read
them, so an XSS flaw can no longer steal a session the way it could
when the tokens lived in localStorage.

Cookie rules (deliberate, documented):
  * HttpOnly=True always, SameSite="lax" always (cross-site POSTs do
    not carry the cookies).
  * Secure=True ONLY when the request actually arrived over HTTPS
    (request.url.scheme, or X-Forwarded-Proto behind a proxy). It must
    NOT follow the environment name: local production on Fahad's PC is
    plain HTTP, and a Secure cookie set over plain HTTP is never sent
    back by httpx/curl (only localhost browsers tolerate it) — that
    broke the production smoke (16/18) until the rule was fixed.
    Without a request object, the old environment rule is the fallback
    (production -> Secure).
  * The refresh cookie is scoped to Path=/api/v1/auth — the browser
    only sends it to the auth endpoints that need it; every other
    endpoint gets the access cookie only.
  * The JSON bodies of login/register/refresh no longer contain any
    token — only the user object and metadata. (Tests and scripts
    read the tokens from the Set-Cookie headers / cookie jar.)

Backward compatibility: get_current_user() still accepts an
Authorization: Bearer token (API clients, curl, smoke scripts).
The browser path is cookies-only; Bearer is a documented fallback
for non-browser clients, not something the frontend uses.
"""
import logging

from fastapi import Request, Response

from app.core.config import settings

logger = logging.getLogger("rtb.cookies")

ACCESS_COOKIE = "rtb_access"
REFRESH_COOKIE = "rtb_refresh"
ACCESS_MAX_AGE = 15 * 60  # seconds — matches the 15-minute access token
REFRESH_MAX_AGE = 24 * 3600  # seconds — matches the 24-hour refresh token
_REFRESH_PATH = "/api/v1/auth"


def _secure(request: Request | None = None) -> bool:
    """Secure cookies only where HTTPS is real. The request's scheme
    decides (X-Forwarded-Proto wins behind a proxy); without a
    request, fall back to the environment rule."""
    if request is not None:
        scheme = request.headers.get(
            "x-forwarded-proto", request.url.scheme
        ).split(",")[0].strip().lower()
        return scheme == "https"
    return settings.environment == "production"


def set_auth_cookies(
    response: Response, access: str, refresh: str,
    request: Request | None = None,
) -> None:
    secure = _secure(request)
    response.set_cookie(
        ACCESS_COOKIE, access,
        max_age=ACCESS_MAX_AGE, path="/",
        httponly=True, samesite="lax", secure=secure,
    )
    response.set_cookie(
        REFRESH_COOKIE, refresh,
        max_age=REFRESH_MAX_AGE, path=_REFRESH_PATH,
        httponly=True, samesite="lax", secure=secure,
    )


def clear_auth_cookies(response: Response, request: Request | None = None) -> None:
    # The delete must match the cookie's flags, or the browser may
    # keep the old (Secure) cookie.
    secure = _secure(request)
    response.delete_cookie(ACCESS_COOKIE, path="/", secure=secure)
    response.delete_cookie(REFRESH_COOKIE, path=_REFRESH_PATH, secure=secure)


def read_access_token(request: Request) -> str | None:
    """Access token from the httpOnly cookie first, then the
    Authorization: Bearer header (non-browser clients)."""
    token = request.cookies.get(ACCESS_COOKIE)
    if token:
        return token
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    return None


def read_refresh_token(request: Request, body_token: str | None = None) -> str | None:
    """Refresh token from the httpOnly cookie first, then a JSON body
    field (scripts / API clients that do not keep cookies)."""
    token = request.cookies.get(REFRESH_COOKIE)
    if token:
        return token
    return body_token or None
