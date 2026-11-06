"""Auth API — Sprint 3 (real, working), cookies in v0.10.

POST /auth/login    {email, password} -> 200 + user (tokens are set
                    as httpOnly cookies, NOT in the JSON body)
POST /auth/register  {full_name, email, password, confirm_password}
                    -> 201 + user + cookies (auto-login). New accounts
                       are ALWAYS CUSTOMER_SERVICE (lowest privilege);
                       the role can only be raised later by an Admin.
                       Duplicate email -> 409, weak password / bad
                       email -> 400.
POST /auth/refresh  (refresh token from the httpOnly cookie, or a
                    {refresh_token} JSON body for API clients) -> new
                    access token (refresh token rotated, cookies reset)
POST /auth/logout   (refresh token from cookie or body) -> revoke the
                    refresh token and clear both cookies
GET  /auth/me       (cookie or Bearer token) -> current user

v0.10 — httpOnly cookies: the browser never sees a token, so an XSS
flaw can no longer steal a session the way localStorage tokens
could. SameSite=Lax + Secure-in-production (see app/core/cookies.py),
plus an Origin check on cookie-authenticated state-changing requests
(see app/main.py). Bearer tokens are still accepted as a fallback
for API clients and scripts — the frontend does not use them.

Wrong password -> 401. No token -> 401. Expired token -> 401.
Refresh tokens are JWTs with a jti; logout revokes the jti and refresh
rotates it (see app/core/refresh_tokens.py). Access tokens are
stateless and short-lived, so logout cannot revoke an access token —
that is documented here, not hidden.
"""
import logging
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.core import refresh_tokens as rt
from app.core.audit import append_audit
from app.core.config import settings
from app.core.cookies import clear_auth_cookies, read_refresh_token, set_auth_cookies
from app.core.password_reset import create_request as create_reset_request
from app.core.rate_limit import LOGIN_LIMIT, REGISTER_LIMIT, check_allowed, clear, record
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_user,
    validate_password,
    verify_password,
)
from app.core.users import DEMO_EMAILS, create_user, get_user, public_user

logger = logging.getLogger("rtb.auth")
router = APIRouter()

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def _password_error(password: str) -> str | None:
    """Password rule (shown to the user as-is). The rule itself lives
    in app.core.security.validate_password (shared with the admin
    password reset); this is just the local name the register
    endpoint has always used."""
    return validate_password(password)


def _client_ip(request: Request | None) -> str | None:
    if request is None or request.client is None:
        return None
    return request.client.host


def _error(status: int, detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"success": False, "data": None, "error": detail, "request_id": "auth"},
    )


def _envelope(data: dict) -> dict:
    return {"success": True, "data": data, "error": None, "request_id": "auth"}


def _auth_response(data: dict, access: str, refresh: str, status: int = 200,
                   request: Request | None = None) -> JSONResponse:
    """Success response for login/register/refresh: the JSON body
    carries the user + metadata only — the tokens go out as
    httpOnly cookies (see app/core/cookies.py), never in the body.
    The request is passed so the Secure flag can follow the actual
    transport (HTTPS or not)."""
    response = JSONResponse(status_code=status, content=_envelope(data))
    set_auth_cookies(response, access, refresh, request=request)
    return response


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=1, max_length=200)


class RefreshRequest(BaseModel):
    # Optional in v0.10: the browser sends the refresh token in the
    # httpOnly cookie, so no body is needed. API clients without a
    # cookie jar may still pass it in the JSON body.
    refresh_token: str | None = Field(default=None, min_length=10)


class RegisterRequest(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=100)
    email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=1, max_length=200)
    confirm_password: str = Field(..., min_length=1, max_length=200)


def _rate_limited_response(retry_after: int, resource: str) -> JSONResponse:
    """429 envelope with a Retry-After header (seconds)."""
    return JSONResponse(
        status_code=429,
        content={
            "success": False,
            "data": None,
            "error": f"Too many attempts — please wait {retry_after} seconds and try again.",
            "request_id": "auth",
        },
        headers={"Retry-After": str(retry_after)},
    )


@router.post("/auth/register", status_code=201)
async def register(payload: RegisterRequest, request: Request):
    """Sign up. The caller NEVER chooses a role: every new account is
    CUSTOMER_SERVICE (lowest privilege) — an Admin raises it later.
    Success auto-logs the user in (tokens set as httpOnly cookies),
    exactly like POST /auth/login.

    Production (v0.8): rate-limited to 3 attempts / 60 s per (IP, email)
    — see app/core/rate_limit.py."""
    email = (payload.email or "").strip().lower()
    rl_key = f"register:{_client_ip(request)}:{email}"
    allowed, retry_after = check_allowed(rl_key, REGISTER_LIMIT)
    if not allowed:
        append_audit(
            "USER_REGISTERED", user_email=email, result="fail",
            resource="/api/v1/auth/register", detail="rate limited",
            ip=_client_ip(request),
        )
        return _rate_limited_response(retry_after, "/api/v1/auth/register")
    record(rl_key)
    if not _EMAIL_RE.match(email):
        return _error(400, "Please enter a valid email address.")
    if payload.password != payload.confirm_password:
        return _error(400, "Passwords do not match.")
    pw_error = _password_error(payload.password)
    if pw_error:
        return _error(400, pw_error)
    if get_user(email) is not None:
        append_audit(
            "USER_REGISTERED", user_email=email, result="fail",
            resource="/api/v1/auth/register", detail="duplicate email",
            ip=_client_ip(request),
        )
        return _error(409, "An account with this email already exists.")
    try:
        user = create_user(email, payload.full_name, payload.password)
    except ValueError:
        return _error(409, "An account with this email already exists.")
    access = create_access_token(user["email"], user["role"])
    refresh, jti = create_refresh_token(user["email"], user["role"])
    rt.issue_refresh_token(
        jti, user["email"],
        (datetime.now(timezone.utc).timestamp() + 24 * 3600),
    )
    append_audit(
        "USER_REGISTERED", user_email=user["email"], role=user["role"], result="ok",
        resource="/api/v1/auth/register", ip=_client_ip(request),
    )
    return _auth_response(
        {
            "token_type": "cookie",
            "expires_in_minutes": 15,
            "user": public_user(user),
        },
        access, refresh, status=201, request=request,
    )


@router.post("/auth/login")
async def login(payload: LoginRequest, request: Request):
    email = (payload.email or "").strip().lower()
    # Production (v0.8): demo accounts can never log in while disabled
    # — even if a users.json containing them was copied into the
    # production data dir. Same 401 as a wrong password (do not leak it).
    if not settings.demo_accounts_enabled and email in DEMO_EMAILS:
        append_audit(
            "LOGIN", user_email=email, result="fail",
            resource="/api/v1/auth/login", detail="demo account disabled",
            ip=_client_ip(request),
        )
        return _error(401, "Invalid email or password.")
    # Production (v0.8): 5 FAILED logins / 60 s per (IP, email) -> 429.
    # Only failures count; a successful login clears the key.
    rl_key = f"login:{_client_ip(request)}:{email}"
    allowed, retry_after = check_allowed(rl_key, LOGIN_LIMIT)
    if not allowed:
        append_audit(
            "LOGIN", user_email=email, result="fail",
            resource="/api/v1/auth/login", detail="rate limited",
            ip=_client_ip(request),
        )
        return _rate_limited_response(retry_after, "/api/v1/auth/login")
    user = get_user(payload.email)
    # Same response + same audit shape whether the email or the
    # password was wrong (do not leak which one failed).
    if user is None or not verify_password(payload.password, user["password_hash"]):
        record(rl_key)
        append_audit(
            "LOGIN", user_email=payload.email, result="fail",
            resource="/api/v1/auth/login", detail="invalid credentials",
            ip=_client_ip(request),
        )
        return _error(401, "Invalid email or password.")
    clear(rl_key)
    access = create_access_token(user["email"], user["role"])
    refresh, jti = create_refresh_token(user["email"], user["role"])
    rt.issue_refresh_token(
        jti, user["email"],
        (datetime.now(timezone.utc).timestamp() + 24 * 3600),
    )
    append_audit(
        "LOGIN", user_email=user["email"], role=user["role"], result="ok",
        resource="/api/v1/auth/login", ip=_client_ip(request),
    )
    return _auth_response(
        {
            "token_type": "cookie",
            "expires_in_minutes": 15,
            "user": public_user(user),
        },
        access, refresh, request=request,
    )


@router.post("/auth/refresh")
async def refresh(payload: RefreshRequest | None = None, request: Request = None):
    # v0.10: the refresh token comes from the httpOnly cookie first;
    # a JSON body token is the fallback for API clients without a
    # cookie jar. Neither -> 401 (same message as an invalid token).
    token = read_refresh_token(request, (payload.refresh_token if payload else None))
    if not token:
        append_audit("LOGIN", result="fail", resource="/api/v1/auth/refresh",
                     detail="no refresh token", ip=_client_ip(request))
        return _error(401, "Invalid or expired refresh token — please log in again.")
    decoded = decode_token(token, "refresh")
    if decoded is None:
        append_audit("LOGIN", result="fail", resource="/api/v1/auth/refresh",
                     detail="invalid or expired refresh token", ip=_client_ip(request))
        return _error(401, "Invalid or expired refresh token — please log in again.")
    jti = decoded.get("jti", "")
    if rt.is_denied(jti) or not rt.is_refresh_valid(jti):
        append_audit("LOGIN", user_email=decoded.get("sub"), result="fail",
                     resource="/api/v1/auth/refresh", detail="refresh token revoked",
                     ip=_client_ip(request))
        return _error(401, "Refresh token revoked — please log in again.")
    user = get_user(decoded.get("sub", ""))
    if user is None:
        return _error(401, "User not found — please log in again.")
    # Rotate: revoke the old refresh token, issue a new pair.
    rt.revoke_refresh_token(jti)
    access = create_access_token(user["email"], user["role"])
    new_refresh, new_jti = create_refresh_token(user["email"], user["role"])
    rt.issue_refresh_token(
        new_jti, user["email"],
        (datetime.now(timezone.utc).timestamp() + 24 * 3600),
    )
    append_audit("LOGIN", user_email=user["email"], role=user["role"], result="ok",
                 resource="/api/v1/auth/refresh", detail="token refreshed",
                 ip=_client_ip(request))
    return _auth_response(
        {
            "token_type": "cookie",
            "expires_in_minutes": 15,
            "user": public_user(user),
        },
        access, new_refresh, request=request,
    )


@router.post("/auth/logout")
async def logout(payload: RefreshRequest | None = None, request: Request = None):
    # v0.10: revoke the refresh token from the cookie (or the body
    # fallback), then clear both cookies in the response.
    token = read_refresh_token(request, (payload.refresh_token if payload else None))
    decoded = decode_token(token, "refresh") if token else None
    if decoded is not None and decoded.get("jti"):
        rt.revoke_refresh_token(decoded["jti"])
        append_audit("LOGIN", user_email=decoded.get("sub"), result="ok",
                     resource="/api/v1/auth/logout", detail="refresh token revoked",
                     ip=_client_ip(request))
    # Logout always returns 200 (even for a bad token): there is nothing
    # left to revoke, and the frontend clears its stored user anyway.
    response = JSONResponse(status_code=200, content=_envelope({"logged_out": True}))
    clear_auth_cookies(response, request=request)
    return response


class ForgotPasswordRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)


@router.post("/auth/forgot-password")
async def forgot_password(payload: ForgotPasswordRequest, request: Request):
    """Self-service forgot-password (v0.10).

    There is NO email/SMTP in this system, so no reset link or token
    is ever sent. This endpoint records a request for the admin: the
    admin sees it in the Admin panel and approves it by setting a
    new temporary password, which they give to the user out of band
    (in person / on the phone). The response is IDENTICAL whether
    the email exists or not — it must never reveal which emails have
    accounts.
    """
    email = (payload.email or "").strip().lower()
    user = get_user(email)
    if user is not None:
        create_reset_request(email)
        append_audit(
            "PASSWORD_RESET_REQUESTED", user_email=email, result="ok",
            resource="/api/v1/auth/forgot-password",
            detail="reset request recorded for admin review",
            ip=_client_ip(request),
        )
    else:
        # Same audit shape, same response — no existence leak.
        append_audit(
            "PASSWORD_RESET_REQUESTED", user_email=email, result="fail",
            resource="/api/v1/auth/forgot-password",
            detail="unknown email — no request recorded",
            ip=_client_ip(request),
        )
    return _envelope({
        "message": (
            "Your request has been recorded. An administrator will set a "
            "new temporary password for you — please contact the bank admin."
        ),
    })


@router.get("/auth/me")
async def me(user: dict = Depends(get_current_user)):
    return _envelope({"user": public_user(user)})
