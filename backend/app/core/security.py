"""JWT + password helpers (Design section 3 / 9).

Sprint 3: these helpers now back real endpoints — login, refresh,
logout (app/api/v1/auth.py) and the auth dependency used by every
protected route. Access tokens live 15 minutes; refresh tokens 24
hours and carry a jti so logout can revoke them. Nothing here needs
Redis or Ollama.
"""
import logging
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

logger = logging.getLogger("rtb.security")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
ALGORITHM = "HS256"
REFRESH_EXPIRE_HOURS = 24

_bearer = HTTPBearer(auto_error=False)

if "CHANGE-ME" in settings.secret_key or settings.secret_key == "change-me":
    logger.warning(
        "JWT secret is the dev default — set a long random SECRET_KEY in .env "
        "before any real use. Demo tokens are NOT safe to share."
    )


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return pwd_context.verify(plain, hashed)
    except Exception:  # noqa: BLE001 — bad hash format = no match
        return False


def _encode(payload: dict) -> str:
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def create_access_token(subject: str, role: str, expires_minutes: int | None = None) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=expires_minutes or settings.access_token_expire_minutes
    )
    return _encode(
        {"sub": subject, "role": role, "type": "access", "exp": expire}
    )


def create_refresh_token(subject: str, role: str) -> tuple[str, str]:
    """Returns (token, jti). The jti is stored so logout can revoke it."""
    jti = str(uuid.uuid4())
    expire = datetime.now(timezone.utc) + timedelta(hours=REFRESH_EXPIRE_HOURS)
    token = _encode(
        {"sub": subject, "role": role, "type": "refresh", "jti": jti, "exp": expire}
    )
    return token, jti


def decode_token(token: str, expected_type: str) -> dict | None:
    """Decode and check the token type. Returns the payload, or None
    for an expired/invalid/wrong-type token (a refresh token is never
    accepted where an access token is required, and vice versa)."""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except JWTError:
        return None
    if payload.get("type") != expected_type:
        return None
    return payload


def decode_access_token(token: str) -> dict | None:
    return decode_token(token, "access")


def _client_ip(request: Request | None) -> str | None:
    if request is None or request.client is None:
        return None
    return request.client.host


async def get_current_user(request: Request):
    """Auth dependency for protected routes. Raises 401 (never 403)
    when the token is missing, expired, of the wrong type, or the user
    no longer exists in the store. Failed attempts are audit-logged."""
    from app.core.audit import append_audit
    from app.core.users import get_user

    credentials = await _bearer(request)
    token = credentials.credentials if credentials else None
    if not token:
        append_audit("AUTH_FAILED", result="fail", resource=request.url.path,
                     detail="no token", ip=_client_ip(request))
        raise HTTPException(status_code=401, detail="Not authenticated — please log in.")
    payload = decode_access_token(token)
    if payload is None:
        append_audit("AUTH_FAILED", result="fail", resource=request.url.path,
                     detail="invalid or expired token", ip=_client_ip(request))
        raise HTTPException(status_code=401, detail="Invalid or expired token — please log in again.")
    user = get_user(payload.get("sub", ""))
    if user is None:
        append_audit("AUTH_FAILED", user_email=payload.get("sub"), result="fail",
                     resource=request.url.path, detail="user not found",
                     ip=_client_ip(request))
        raise HTTPException(status_code=401, detail="User not found — please log in again.")
    return user


def _deny(request: Request, user: dict, roles: tuple[str, ...]) -> None:
    """Log + raise the 403 for a role that may not use an endpoint."""
    from app.core.audit import append_audit

    append_audit(
        "ACCESS_DENIED", user_email=user["email"], role=user["role"],
        result="denied", resource=request.url.path,
        detail=f"role {user['role']} may not access this endpoint",
        ip=_client_ip(request),
    )
    raise HTTPException(
        status_code=403,
        detail=f"Forbidden — role {user['role']} may not access this endpoint.",
    )


def require_roles(*roles: str):
    """Dependency factory: allow only the given roles. Other roles get
    403 + an ACCESS_DENIED audit entry (the denial itself is logged).
    Use as Depends(require_roles("ADMIN")) — FastAPI resolves the
    get_current_user dependency; never call the returned function
    directly (its `user` default is a Depends marker, not a user)."""

    async def _checker(request: Request, user: dict = Depends(get_current_user)):
        if user["role"] not in roles:
            _deny(request, user, roles)
        return user

    return _checker


async def require_admin(request: Request, user: dict = Depends(get_current_user)):
    """Shortcut dependency: ADMIN role only."""
    if user["role"] != "ADMIN":
        _deny(request, user, ("ADMIN",))
    return user
