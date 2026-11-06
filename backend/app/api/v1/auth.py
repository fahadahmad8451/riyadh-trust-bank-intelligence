"""Auth API — Sprint 3 (real, working).

POST /auth/login    {email, password} -> access token (15 min) + refresh token (24 h)
POST /auth/register  {full_name, email, password, confirm_password}
                    -> 201 + tokens (auto-login). New accounts are ALWAYS
                       CUSTOMER_SERVICE (lowest privilege); the role can
                       only be raised later by an Admin. Duplicate email
                       -> 409, weak password / bad email -> 400.
POST /auth/refresh  {refresh_token}   -> new access token (refresh token rotated)
POST /auth/logout   {refresh_token}   -> revoke the refresh token
GET  /auth/me       (Bearer token)    -> current user (email, name, role, departments)

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
from app.core.rate_limit import LOGIN_LIMIT, REGISTER_LIMIT, check_allowed, clear, record
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_user,
    verify_password,
)
from app.core.users import DEMO_EMAILS, create_user, get_user, public_user

logger = logging.getLogger("rtb.auth")
router = APIRouter()

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def _password_error(password: str) -> str | None:
    """Password rule (shown to the user as-is): at least 8 characters,
    at least one letter and at least one digit."""
    if len(password) < 8:
        return "Password must be at least 8 characters long."
    if not re.search(r"[A-Za-z]", password):
        return "Password must contain at least one letter."
    if not re.search(r"\d", password):
        return "Password must contain at least one digit."
    return None


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


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=1, max_length=200)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(..., min_length=10)


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
    Success auto-logs the user in (access + refresh tokens returned),
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
    return JSONResponse(
        status_code=201,
        content=_envelope({
            "access_token": access,
            "refresh_token": refresh,
            "token_type": "bearer",
            "expires_in_minutes": 15,
            "user": public_user(user),
        }),
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
    return _envelope({
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "bearer",
        "expires_in_minutes": 15,
        "user": public_user(user),
    })


@router.post("/auth/refresh")
async def refresh(payload: RefreshRequest, request: Request):
    token = payload.refresh_token
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
    return _envelope({
        "access_token": access,
        "refresh_token": new_refresh,
        "token_type": "bearer",
        "expires_in_minutes": 15,
        "user": public_user(user),
    })


@router.post("/auth/logout")
async def logout(payload: RefreshRequest, request: Request):
    decoded = decode_token(payload.refresh_token, "refresh")
    if decoded is not None and decoded.get("jti"):
        rt.revoke_refresh_token(decoded["jti"])
        append_audit("LOGIN", user_email=decoded.get("sub"), result="ok",
                     resource="/api/v1/auth/logout", detail="refresh token revoked",
                     ip=_client_ip(request))
    # Logout always returns 200 (even for a bad token): there is nothing
    # left to revoke, and the frontend clears its stored tokens anyway.
    return _envelope({"logged_out": True})


@router.get("/auth/me")
async def me(user: dict = Depends(get_current_user)):
    return _envelope({"user": public_user(user)})
