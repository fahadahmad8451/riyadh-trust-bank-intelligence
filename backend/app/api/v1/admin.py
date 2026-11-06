"""Admin API — Sprint 3 (ADMIN role only).

GET /admin/users      — all users (password hashes never returned)
GET /admin/audit-logs — audit entries, newest first, ?limit=100&offset=0
PUT /admin/users/{email}/role — change a user's role (v0.7). Only an
    ADMIN may do this, and an Admin may NOT change their own role
    (that would let a compromised admin lock everyone else out — or
    lock themselves out). Every change is audit-logged (ROLE_CHANGED).

All routes require a valid token AND the ADMIN role; anything else
gets 401 (no/invalid token) or 403 + ACCESS_DENIED audit (wrong role).
"""
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.core.audit import append_audit, read_audit
from app.core.rbac import ALL_ROLES
from app.core.security import require_admin
from app.core.users import get_user, list_public_users, public_user, update_user_role

router = APIRouter()


def _envelope(data: dict) -> dict:
    return {"success": True, "data": data, "error": None, "request_id": "admin"}


def _error(status: int, detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"success": False, "data": None, "error": detail, "request_id": "admin"},
    )


@router.get("/admin/users")
async def admin_users(user: dict = Depends(require_admin)):
    return _envelope({"users": list_public_users(), "count": len(list_public_users())})


class RoleChangeRequest(BaseModel):
    role: str = Field(..., min_length=1, max_length=50)


@router.put("/admin/users/{email}/role")
async def admin_change_role(
    email: str, payload: RoleChangeRequest, request: Request,
    user: dict = Depends(require_admin),
):
    target_email = (email or "").strip().lower()
    new_role = (payload.role or "").strip().upper()
    if new_role not in ALL_ROLES:
        return _error(400, f"Invalid role: {payload.role} — use one of {list(ALL_ROLES)}")
    if target_email == user["email"].lower():
        return _error(400, "You cannot change your own role.")
    target = get_user(target_email)
    if target is None:
        return _error(404, f"User not found: {target_email}")
    old_role = target["role"]
    updated = update_user_role(target_email, new_role)
    append_audit(
        "ROLE_CHANGED", user_email=user["email"], role=user["role"], result="ok",
        resource=f"/api/v1/admin/users/{target_email}/role",
        detail=f"{target_email}: {old_role} -> {new_role}",
        ip=request.client.host if request.client else None,
    )
    return _envelope({"user": public_user(updated)})


@router.get("/admin/audit-logs")
async def admin_audit_logs(
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user: dict = Depends(require_admin),
):
    entries, total = read_audit(limit=limit, offset=offset)
    return _envelope({
        "audit_logs": entries,
        "count": len(entries),
        "total": total,
        "limit": limit,
        "offset": offset,
    })
