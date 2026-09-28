from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.middleware.auth import get_current_user
from app.models.user import User
from app.schemas.user import (
    UserBulkRequest,
    UserBulkResponse,
    UserBulkResult,
    UserCreate,
    UserListResponse,
    UserResponse,
    UserSeparateRequest,
    UserUpdate,
    UserUpdateProfile,
)
from app.services import audit_service, employee_access, employee_field_service, employee_lifecycle
from app.services import employee_record_service as records
from app.services.email_service import EmailService
from app.services.invite_service import InviteService
from app.services.token_store import RateLimiter
from app.services.user_service import UserService

router = APIRouter(prefix="/users", tags=["Users"])

# Kept for callers that import it; the rule lives in employee_record_service.
PRIVILEGED_ROLE_CODES = records.PRIVILEGED_ROLE_CODES


async def _frontend_base(db: AsyncSession, request: Request) -> str:
    from app.api.v1.auth import _frontend_base as base

    return await base(db, request)


def _integrity_message(exc: IntegrityError) -> str:
    """A unique index caught what the pre-checks missed (two saves racing).
    Say which value, in words."""
    text = str(getattr(exc, "orig", exc)).lower()
    if "email" in text:
        return "That email address is already used by another employee."
    if "username" in text:
        return "That username is already taken."
    if "personnel" in text:
        return "That employee number is already assigned to another employee."
    if "employee_field_value" in text:
        return "One of the custom field values is already used by another employee."
    return "That change conflicts with another employee's record."


# Pickers across the app (approver rules, org members, visibility grants,
# attendance) used `GET /users?per_page=100`, which the backend caps at 100, so
# a company with 101 employees silently could not pick the 101st. This is a
# search-as-you-type lookup instead: minimal fields, no page cap on the result
# set because the caller narrows it by typing.
_LOOKUP_PERMISSIONS = (
    ("employees", "view"),
    ("organization", "edit"),
    ("schedules", "edit"),
    ("leave", "edit"),
    ("settings", "edit"),
)


@router.get("/lookup")
async def lookup_users(
    q: Optional[str] = Query(None, max_length=100),
    limit: int = Query(50, ge=1, le=200),
    include_inactive: bool = False,
    ids: Optional[str] = Query(None, description="Comma-separated ids to resolve"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import func, or_

    from app.services.permission_service import PermissionService

    if not current_user.has_role("tenant_admin"):
        role_ids = [ur.role_id for ur in current_user.user_roles]
        allowed = False
        for module, action in _LOOKUP_PERMISSIONS:
            if await PermissionService.check_permission(
                db, current_user.tenant_id, role_ids, module, action
            ):
                allowed = True
                break
        if not allowed:
            raise HTTPException(status_code=403, detail="Insufficient permissions")

    stmt = select(User).where(User.tenant_id == current_user.tenant_id)
    if not include_inactive:
        stmt = stmt.where(User.is_active == True)  # noqa: E712
    if ids:
        try:
            wanted = [int(x) for x in ids.split(",") if x.strip()]
        except ValueError:
            raise HTTPException(status_code=422, detail="ids must be integers")
        stmt = stmt.where(User.id.in_(wanted[:500]))
    elif q and q.strip():
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(User.first_name).like(like),
                func.lower(User.last_name).like(like),
                func.lower(User.first_name + " " + User.last_name).like(like),
                func.lower(User.email).like(like),
                func.lower(User.username).like(like),
                func.lower(func.coalesce(User.personnel_number, "")).like(like),
            )
        )
    stmt = stmt.order_by(User.last_name, User.first_name).limit(limit)
    users = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": u.id,
            "name": f"{u.first_name} {u.last_name}".strip(),
            "email": u.email,
            "username": u.username,
            "personnel_number": u.personnel_number,
            "org_node_id": u.org_node_id,
            "is_active": u.is_active,
        }
        for u in users
    ]


# ── Directory ────────────────────────────────────────────────────────


async def _org_node_filter(db: AsyncSession, tenant_id, node_id: Optional[int], include_sub_units: bool):
    if node_id is None:
        return None
    if not include_sub_units:
        return [node_id]
    from app.services.schedule_service import ScheduleService

    return list(await ScheduleService._get_descendant_node_ids(db, [node_id], tenant_id))


async def _directory_query(
    db: AsyncSession,
    viewer: User,
    access,
    *,
    search: Optional[str],
    role: Optional[str],
    is_active: Optional[bool],
    separation_type: Optional[str],
    org_node_id: Optional[int],
    include_sub_units: bool,
    custom: Dict[str, str],
) -> Dict[str, Any]:
    """The keyword arguments to UserService.list_users for a directory view
    (used by the list and by bulk 'all matching the filter')."""
    scope = await employee_access.readable_employee_ids(db, viewer)
    return dict(
        restrict_to_ids=scope,
        search=search,
        role=role,
        is_active=is_active,
        separation_type=separation_type,
        org_node_ids=await _org_node_filter(db, viewer.tenant_id, org_node_id, include_sub_units),
        search_field_ids=await employee_field_service.searchable_field_ids(db, viewer.tenant_id, access),
        extra_clauses=await employee_field_service.filter_clauses(db, viewer.tenant_id, access, custom),
    )


@router.get("", response_model=UserListResponse)
async def list_users(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None, max_length=100),
    role: Optional[str] = None,
    is_active: Optional[bool] = None,
    separation_type: Optional[str] = None,
    org_node_id: Optional[int] = None,
    include_sub_units: bool = True,
    department_id: Optional[int] = None,
    section_id: Optional[int] = None,
    unit_id: Optional[int] = None,
    sort_by: Optional[str] = None,
    order: Optional[str] = Query(None, pattern="^(asc|desc)$"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Employee directory. `cf_<key>=value` filters on a select or unique
    custom field the caller may see."""
    # employees:view, scoped: a manager sees the teams they head, not every
    # colleague's contact details and separation reason (audit Tier 1 #14).
    await employee_access.require(db, current_user, "employees", "view")
    access = await employee_field_service.viewer_access(db, current_user)
    custom = {k[3:]: v for k, v in request.query_params.items() if k.startswith("cf_") and v != ""}
    query = await _directory_query(
        db, current_user, access,
        search=search, role=role, is_active=is_active, separation_type=separation_type,
        org_node_id=org_node_id, include_sub_units=include_sub_units, custom=custom,
    )
    result = await UserService.list_users(
        db,
        tenant_id=current_user.tenant_id,
        page=page,
        per_page=per_page,
        department_id=department_id,
        section_id=section_id,
        unit_id=unit_id,
        sort_by=sort_by,
        order=order or "asc",
        **query,
    )
    return UserListResponse(
        items=await records.serialize(db, result["items"], current_user, listing=True, access=access),
        total=result["total"],
        page=result["page"],
        per_page=result["per_page"],
        total_pages=result["total_pages"],
    )


# ── Create ───────────────────────────────────────────────────────────


@router.post("", response_model=UserResponse, status_code=201)
async def create_user(
    data: UserCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await employee_access.require(db, current_user, "employees", "create")
    tenant_id = current_user.tenant_id

    user_data = data.model_dump()
    custom_fields = user_data.pop("custom_fields", None) or {}
    role_codes = user_data.pop("role_codes", None) or ["employee"]
    send_invite = user_data.pop("send_invite")
    if not user_data.get("username"):
        user_data["username"] = data.email

    # If not using invite flow, password is required
    if not send_invite and not data.password:
        raise HTTPException(status_code=400, detail="Password is required when not sending an invite")

    records.assert_may_grant(current_user, role_codes)
    await records.assert_roles_exist(db, tenant_id, set(role_codes) | {"employee"})
    await records.validate_fields(db, tenant_id, user_data)

    # One savepoint for the account and its custom fields: a required field
    # left empty must not leave a half-created employee behind.
    try:
        async with db.begin_nested():
            user = await UserService.create_user(
                db, tenant_id=tenant_id, data=user_data, role_codes=role_codes, assigned_by=current_user.id,
            )
            cf_changes = {}
            access = await records.creation_access(db, current_user)
            if custom_fields or await employee_field_service.list_definitions(db, tenant_id):
                cf_changes = await employee_field_service.set_values(
                    db, tenant_id=tenant_id, target=user, values=custom_fields, access=access, creating=True,
                )
    except IntegrityError as exc:
        raise HTTPException(status_code=400, detail=_integrity_message(exc))

    frontend_base = await _frontend_base(db, request)
    if send_invite:
        await InviteService.issue_and_email(
            db, user=user, created_by=current_user.id, frontend_base=frontend_base
        )
    else:
        # Admin-set password. The password is deliberately NOT emailed: mail is
        # unencrypted at rest in most inboxes and is the wrong channel for a
        # credential. The admin communicates it out-of-band, and the employee
        # must change it at first sign-in.
        login_url = f"{frontend_base}/auth/login"
        EmailService.fire_and_forget(
            lambda db, _email=user.email, _name=user.first_name, _url=login_url:
                EmailService.send_account_activated_email(
                    db, to_email=_email, first_name=_name, login_url=_url,
                )
        )

    audit_service.record(
        db,
        actor=current_user,
        action="user_create",
        resource_type="user",
        resource_id=user.id,
        request=request,
        details={
            "target_name": audit_service.user_label(user),
            "after": audit_service.snapshot_user(user),
            "roles": sorted(user.role_codes),
            "custom_fields": cf_changes,
            "invited": bool(send_invite),
        },
    )
    user = await UserService.get_user_by_id(db, user.id, tenant_id)
    return (await records.serialize(db, [user], current_user))[0]


# ── Bulk edit ────────────────────────────────────────────────────────
#
# Declared before /{user_id} so "bulk" is never read as an id.

_BULK_PERMISSION = {
    "set_employee_type": "edit",
    "set_schedule_format": "edit",
    "set_org_unit": "edit",
    "set_reports_to": "edit",
    "send_invite": "create",
    "separate": "delete",
}
_BULK_FIELD = {
    "set_employee_type": "employee_type",
    "set_schedule_format": "schedule_format",
    "set_org_unit": "org_node_id",
    "set_reports_to": "reports_to_id",
}


@router.patch("/bulk", response_model=UserBulkResponse)
async def bulk_update(
    body: UserBulkRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Apply one change to many employees (audit E-10).

    Targets are the listed ids or everyone matching `filter` within the
    caller's read scope. Each target is checked (scope, safeguards) and applied
    in its own savepoint, so one refusal never undoes the others, and every
    target gets a result line. One audit entry describes the whole batch.
    """
    action = body.action
    await employee_access.require(db, current_user, "employees", _BULK_PERMISSION[action])
    tenant_id = current_user.tenant_id

    if body.user_ids is None and body.filter is None:
        raise HTTPException(status_code=400, detail="Choose the employees to change, or a filter.")
    if body.user_ids is not None:
        ids = list(dict.fromkeys(body.user_ids))
    else:
        f = body.filter
        access = await employee_field_service.viewer_access(db, current_user)
        query = await _directory_query(
            db, current_user, access,
            search=f.search, role=f.role, is_active=f.is_active, separation_type=f.separation_type,
            org_node_id=f.org_node_id, include_sub_units=True, custom=f.custom or {},
        )
        ids = (await UserService.list_users(db, tenant_id, ids_only=True, **query))["ids"]
    if len(ids) > 5000:
        raise HTTPException(status_code=400, detail="At most 5,000 employees can be changed at once.")

    value = body.value
    field = _BULK_FIELD.get(action)
    if field:
        if field in ("org_node_id", "reports_to_id") and value is not None:
            try:
                value = int(value)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="The new value must be an id.")
        elif field in ("employee_type", "schedule_format"):
            value = (str(value).strip() or None) if value is not None else None
        # Validate the value once, before touching anyone.
        await records.validate_fields(db, tenant_id, {field: value} if field != "reports_to_id" else {})
        if field == "reports_to_id":
            await UserService.assert_valid_reports_to(db, None, tenant_id, value)
    if action == "separate" and body.separation is None:
        raise HTTPException(status_code=400, detail="Separation details are required.")

    users = {
        u.id: u
        for u in (
            await db.execute(
                select(User).where(User.tenant_id == tenant_id, User.id.in_(ids))
            )
        ).scalars().all()
    }
    frontend_base = await _frontend_base(db, request) if action == "send_invite" else ""
    results: List[UserBulkResult] = []

    for uid in ids:
        user = await UserService.get_user_by_id(db, uid, tenant_id) if uid in users else None
        if user is None:
            results.append(UserBulkResult(user_id=uid, name=f"#{uid}", status="error", message="Employee not found."))
            continue
        name = audit_service.user_label(user)
        try:
            async with db.begin_nested():
                await employee_access.assert_manages(db, current_user, [uid])
                if field:
                    if getattr(user, field) == value:
                        results.append(UserBulkResult(user_id=uid, name=name, status="skipped", message="Already set."))
                        continue
                    if field == "reports_to_id":
                        await UserService.assert_valid_reports_to(db, user, tenant_id, value)
                    await UserService.update_user(db, user, {field: value}, assigned_by=current_user.id)
                elif action == "send_invite":
                    if not user.is_active:
                        results.append(UserBulkResult(user_id=uid, name=name, status="skipped", message="Inactive."))
                        continue
                    if not user.must_change_password:
                        results.append(UserBulkResult(user_id=uid, name=name, status="skipped", message="Already activated their account."))
                        continue
                    employee_access.assert_may_change_sign_in(current_user, user, {"password"})
                    if await RateLimiter.hit(
                        f"invite-resend:{tenant_id}:{user.id}",
                        settings.INVITE_RESEND_RATE_LIMIT_ATTEMPTS,
                        settings.INVITE_RESEND_RATE_LIMIT_WINDOW_SECONDS,
                    ):
                        raise HTTPException(status_code=429, detail="Invited too many times recently; try again later.")
                    await InviteService.issue_and_email(
                        db, user=user, created_by=current_user.id, frontend_base=frontend_base, resend=True
                    )
                elif action == "separate":
                    if not user.is_active:
                        results.append(UserBulkResult(user_id=uid, name=name, status="skipped", message="Already inactive."))
                        continue
                    await employee_access.assert_may_change_active_status(db, current_user, user, deactivating=True)
                    sep = body.separation
                    await employee_lifecycle.separate(
                        db, actor=current_user, user=user,
                        separation_type=sep.separation_type, separation_date=sep.separation_date,
                        reason=sep.separation_reason, delete_future_shifts=sep.delete_future_shifts,
                    )
            results.append(UserBulkResult(user_id=uid, name=name, status="updated"))
        except HTTPException as exc:
            results.append(UserBulkResult(user_id=uid, name=name, status="error", message=str(exc.detail)))
        except IntegrityError as exc:
            results.append(UserBulkResult(user_id=uid, name=name, status="error", message=_integrity_message(exc)))

    counts = {s: sum(1 for r in results if r.status == s) for s in ("updated", "skipped", "error")}
    audit_service.record(
        db,
        actor=current_user,
        action="users_bulk_update",
        resource_type="user",
        request=request,
        details={
            "bulk_action": action,
            "value": value if field else None,
            "separation": body.separation.model_dump() if body.separation else None,
            "updated_ids": [r.user_id for r in results if r.status == "updated"],
            "counts": counts,
        },
    )
    return UserBulkResponse(
        action=action,
        total=len(results),
        updated=counts["updated"],
        skipped=counts["skipped"],
        failed=counts["error"],
        results=results,
    )


# ── Own profile ──────────────────────────────────────────────────────


@router.get("/me", response_model=UserResponse)
async def get_my_profile(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return (await records.serialize(db, [current_user], current_user))[0]


@router.patch("/me", response_model=UserResponse)
async def update_my_profile(
    data: UserUpdateProfile,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    update_data = data.model_dump(exclude_unset=True)
    custom_fields = update_data.pop("custom_fields", None)
    before = audit_service.snapshot_user(current_user)
    cf_changes = {}
    if custom_fields:
        access = await employee_field_service.viewer_access(db, current_user)
        cf_changes = await employee_field_service.set_values(
            db, tenant_id=current_user.tenant_id, target=current_user, values=custom_fields, access=access,
        )
    await UserService.update_user(db, current_user, update_data)

    # UserService.update_user calls db.refresh(), which expires the eagerly
    # loaded user_roles. UserResponse needs them for `roles`/`primary_role`, and
    # a lazy load here raises MissingGreenlet under asyncio, so re-fetch with
    # the relationship eager-loaded.
    user = await UserService.get_user_by_id(db, current_user.id, current_user.tenant_id)
    changes = audit_service.diff(before, audit_service.snapshot_user(user))
    if changes or cf_changes:
        audit_service.record(
            db, actor=current_user, action="profile_update", resource_type="user", resource_id=user.id,
            request=request,
            details={"target_name": audit_service.user_label(user), "changes": changes, "custom_fields": cf_changes},
        )
    return (await records.serialize(db, [user], current_user))[0]


# ── One employee ─────────────────────────────────────────────────────


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Your own record is self-service; anyone else's needs employees:view and
    # must be inside your scope.
    if user_id != current_user.id:
        await employee_access.require(db, current_user, "employees", "view")
    user = await UserService.get_user_by_id(db, user_id, current_user.tenant_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    await employee_access.assert_can_read(db, current_user, user_id)
    return (await records.serialize(db, [user], current_user))[0]


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    data: UserUpdate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await employee_access.require(db, current_user, "employees", "edit")
    tenant_id = current_user.tenant_id
    user = await UserService.get_user_by_id(db, user_id, tenant_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    await employee_access.assert_manages(db, current_user, [user.id])

    # Only the keys the client sent; an explicit null clears (audit E-5).
    update_data = data.model_dump(exclude_unset=True)
    custom_fields = update_data.pop("custom_fields", None)
    role_codes = update_data.pop("role_codes", None)

    # Sign-in details of an administrator are an account-takeover path: change
    # the email, then "forgot password" (audit Tier 1 #1).
    changed = {
        k for k in ("email", "username")
        if k in update_data and (update_data[k] or "").lower() != (getattr(user, k) or "").lower()
    }
    employee_access.assert_may_change_sign_in(current_user, user, changed)
    await records.validate_fields(db, tenant_id, update_data, target=user)

    before = audit_service.snapshot_user(user)
    roles_before = roles_after = sorted(user.role_codes)
    cf_changes: Dict[str, Any] = {}
    # All or nothing: roles, custom fields and columns in one savepoint.
    try:
        async with db.begin_nested():
            if role_codes is not None:
                roles_before, roles_after = await records.set_roles(db, current_user, user, role_codes)
            if custom_fields:
                access = await employee_field_service.viewer_access(db, current_user)
                cf_changes = await employee_field_service.set_values(
                    db, tenant_id=tenant_id, target=user, values=custom_fields, access=access,
                )
            user = await UserService.update_user(db, user, update_data, assigned_by=current_user.id)
    except IntegrityError as exc:
        raise HTTPException(status_code=400, detail=_integrity_message(exc))

    user = await UserService.get_user_by_id(db, user.id, tenant_id)
    changes = audit_service.diff(before, audit_service.snapshot_user(user))
    label = audit_service.user_label(user)
    if changes or cf_changes:
        audit_service.record(
            db, actor=current_user, action="user_update", resource_type="user", resource_id=user.id,
            request=request, details={"target_name": label, "changes": changes, "custom_fields": cf_changes},
        )
    roles_changed = roles_before != roles_after
    if roles_changed:
        audit_service.record(
            db, actor=current_user, action="user_roles_change", resource_type="user", resource_id=user.id,
            request=request, details={"target_name": label, "from": roles_before, "to": roles_after},
        )

    # Notify the user their roles changed (fire-and-forget). Only when the set
    # actually differs and it isn't the admin editing their own account.
    if roles_changed and user.email and user.id != current_user.id:
        role_labels = ", ".join(sorted(user.role_codes)) or "employee"
        EmailService.fire_and_forget(
            lambda db, email=user.email, first_name=user.first_name, labels=role_labels:
                EmailService.send_roles_changed_email(
                    db, to_email=email, first_name=first_name, role_labels=labels,
                )
        )

    return (await records.serialize(db, [user], current_user))[0]


@router.delete("/{user_id}", status_code=204)
async def delete_user(
    user_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Deactivate without recording a separation type. Same safeguards and
    clean-up as separate, except shifts are left alone."""
    await employee_access.require(db, current_user, "employees", "delete")
    user = await UserService.get_user_by_id(db, user_id, current_user.tenant_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    await employee_access.assert_manages(db, current_user, [user.id])
    await employee_access.assert_may_change_active_status(db, current_user, user, deactivating=True)
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Employee is already inactive")

    summary = await employee_lifecycle.separate(
        db, actor=current_user, user=user, separation_type=None, separation_date=None,
        reason=None, delete_future_shifts=False,
    )
    audit_service.record(
        db, actor=current_user, action="user_deactivate", resource_type="user", resource_id=user.id,
        request=request, details={"target_name": audit_service.user_label(user), **summary},
    )

    # Send account deactivated email (fire-and-forget)
    EmailService.fire_and_forget(
        lambda db, email=user.email, first_name=user.first_name: EmailService.send_account_deactivated_email(
            db, to_email=email, first_name=first_name,
        )
    )


@router.post("/{user_id}/separate", response_model=UserResponse)
async def separate_employee(
    user_id: int,
    data: UserSeparateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark an employee as resigned or terminated, and clean up after them
    (unit head roles, optionally future shifts, sessions; see
    employee_lifecycle)."""
    await employee_access.require(db, current_user, "employees", "delete")

    user = await UserService.get_user_by_id(db, user_id, current_user.tenant_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    await employee_access.assert_manages(db, current_user, [user.id])
    await employee_access.assert_may_change_active_status(db, current_user, user, deactivating=True)

    if not user.is_active:
        raise HTTPException(status_code=400, detail="Employee is already inactive")

    summary = await employee_lifecycle.separate(
        db, actor=current_user, user=user,
        separation_type=data.separation_type, separation_date=data.separation_date,
        reason=data.separation_reason, delete_future_shifts=data.delete_future_shifts,
    )
    audit_service.record(
        db, actor=current_user, action="user_separate", resource_type="user", resource_id=user.id,
        request=request,
        details={
            "target_name": audit_service.user_label(user),
            "separation_type": data.separation_type,
            "separation_date": data.separation_date,
            "reason": data.separation_reason,
            **summary,
        },
    )

    # Send notification email
    EmailService.fire_and_forget(
        lambda db, email=user.email, first_name=user.first_name: EmailService.send_account_deactivated_email(
            db, to_email=email, first_name=first_name,
        )
    )

    user = await UserService.get_user_by_id(db, user_id, current_user.tenant_id)
    return (await records.serialize(db, [user], current_user))[0]


@router.post("/{user_id}/reinstate", response_model=UserResponse)
async def reinstate_employee(
    user_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Reinstate a separated employee back to active status."""
    await employee_access.require(db, current_user, "employees", "delete")
    user = await UserService.get_user_by_id(db, user_id, current_user.tenant_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    await employee_access.assert_manages(db, current_user, [user.id])
    await employee_access.assert_may_change_active_status(db, current_user, user, deactivating=False)

    if user.is_active:
        raise HTTPException(status_code=400, detail="Employee is already active")

    previous = {
        "separation_type": user.separation_type,
        "separation_date": user.separation_date,
    }
    await employee_lifecycle.reinstate(db, user=user)
    audit_service.record(
        db, actor=current_user, action="user_reinstate", resource_type="user", resource_id=user.id,
        request=request, details={"target_name": audit_service.user_label(user), "previous": previous},
    )

    # Notify the reinstated user (fire-and-forget).
    login_url = f"{await _frontend_base(db, request)}/auth/login"
    if user.email:
        EmailService.fire_and_forget(
            lambda db, email=user.email, first_name=user.first_name, url=login_url:
                EmailService.send_account_reinstated_email(
                    db, to_email=email, first_name=first_name, login_url=url,
                )
        )

    user = await UserService.get_user_by_id(db, user_id, current_user.tenant_id)
    return (await records.serialize(db, [user], current_user))[0]


@router.post("/{user_id}/resend-invite")
async def resend_invite(
    user_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await employee_access.require(db, current_user, "employees", "create")
    user = await UserService.get_user_by_id(db, user_id, current_user.tenant_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    await employee_access.assert_manages(db, current_user, [user.id])
    # An activation link is a way to set the password, so for an administrator
    # it is the same privilege as changing their sign-in details.
    employee_access.assert_may_change_sign_in(current_user, user, {"password"})

    if not user.is_active:
        raise HTTPException(status_code=400, detail="This employee is inactive. Reinstate them first.")
    if not user.must_change_password:
        raise HTTPException(status_code=400, detail="User has already activated their account")

    # Cap resends per invitee so a repeated click (or a malicious admin) cannot
    # mailbomb the target address. Keyed by target user, not the caller.
    if await RateLimiter.hit(
        f"invite-resend:{current_user.tenant_id}:{user.id}",
        settings.INVITE_RESEND_RATE_LIMIT_ATTEMPTS,
        settings.INVITE_RESEND_RATE_LIMIT_WINDOW_SECONDS,
    ):
        raise HTTPException(
            status_code=429,
            detail="Too many invite resends for this user. Please wait before trying again.",
        )

    await InviteService.issue_and_email(
        db, user=user, created_by=current_user.id,
        frontend_base=await _frontend_base(db, request), resend=True,
    )
    audit_service.record(
        db, actor=current_user, action="user_invite_resend", resource_type="user", resource_id=user.id,
        request=request, details={"target_name": audit_service.user_label(user)},
    )
    return {"message": "Invite resent successfully"}
