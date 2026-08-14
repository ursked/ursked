from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.middleware.auth import get_current_user, require_role
from app.models.tenant import Tenant
from app.models.user import User
from app.services.token_store import RateLimiter
from app.schemas.user import (
    UserCreate,
    UserListResponse,
    UserResponse,
    UserSeparateRequest,
    UserUpdate,
    UserUpdateProfile,
)
from app.services.configurable_type_service import ConfigurableTypeService
from app.services.email_service import EmailService
from app.services.invite_service import InviteService
from app.services.role_service import RoleService
from app.services.user_service import UserService


async def _assert_valid_employee_type(db, tenant_id, employee_type) -> None:
    """Reject an employee_type that doesn't map to a configured active type.

    None/empty is allowed (unassigned). This closes the integrity gap where
    users.employee_type could hold arbitrary strings that no policy matches.
    """
    if not await ConfigurableTypeService.validate_employee_type(
        db, tenant_id, employee_type
    ):
        raise HTTPException(
            status_code=400,
            detail=f"Unknown employee type '{employee_type}'. Configure it under Employee Types first.",
        )

router = APIRouter(prefix="/users", tags=["Users"])

# Roles that may only be granted by a tenant_admin. Without this, any `hr` user
# (who can already reach the user-update endpoint) could grant themselves
# tenant_admin and bypass every permission check in the application.
PRIVILEGED_ROLE_CODES = {"tenant_admin"}


def _assert_may_assign_roles(actor: User, role_codes: list[str]) -> None:
    if actor.has_role("tenant_admin"):
        return
    requested = set(role_codes) & PRIVILEGED_ROLE_CODES
    if requested:
        raise HTTPException(
            status_code=403,
            detail=f"Only a tenant admin may grant: {', '.join(sorted(requested))}",
        )


def _assert_may_revoke_roles(actor: User, removed_codes: set[str]) -> None:
    if actor.has_role("tenant_admin"):
        return
    privileged = removed_codes & PRIVILEGED_ROLE_CODES
    if privileged:
        raise HTTPException(
            status_code=403,
            detail=f"Only a tenant admin may revoke: {', '.join(sorted(privileged))}",
        )


@router.get("", response_model=UserListResponse)
async def list_users(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    role: Optional[str] = None,
    is_active: Optional[bool] = None,
    separation_type: Optional[str] = None,
    department_id: Optional[int] = None,
    division_id: Optional[int] = None,
    section_id: Optional[int] = None,
    unit_id: Optional[int] = None,
    sort_by: Optional[str] = None,
    order: Optional[str] = Query(None, pattern="^(asc|desc)$"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(["tenant_admin", "hr", "manager"])),
):
    result = await UserService.list_users(
        db,
        tenant_id=current_user.tenant_id,
        page=page,
        per_page=per_page,
        search=search,
        role=role,
        is_active=is_active,
        separation_type=separation_type,
        department_id=department_id,
        section_id=section_id,
        unit_id=unit_id,
        sort_by=sort_by,
        order=order or "asc",
    )
    return UserListResponse(
        items=[UserResponse.model_validate(u) for u in result["items"]],
        total=result["total"],
        page=result["page"],
        per_page=result["per_page"],
        total_pages=result["total_pages"],
    )


@router.post("", response_model=UserResponse, status_code=201)
async def create_user(
    data: UserCreate,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(["tenant_admin", "hr"])),
):
    # Check for duplicate email
    existing = await UserService.get_user_by_email(db, data.email, current_user.tenant_id)
    if existing:
        raise HTTPException(status_code=400, detail="Email already in use")

    # Default username to email if not provided
    user_data = data.model_dump()
    if not user_data.get("username"):
        user_data["username"] = data.email

    # Check duplicate username
    existing_username = await UserService.get_user_by_username(
        db, user_data["username"], current_user.tenant_id
    )
    if existing_username:
        raise HTTPException(status_code=400, detail="Username already in use")

    await _assert_valid_employee_type(
        db, current_user.tenant_id, user_data.get("employee_type")
    )

    send_invite = data.send_invite
    raw_password = data.password

    # If not using invite flow, password is required
    if not send_invite and not raw_password:
        raise HTTPException(status_code=400, detail="Password is required when not sending an invite")

    role_codes = user_data.pop("role_codes", ["employee"])
    user_data.pop("tenant_id", None)

    _assert_may_assign_roles(current_user, role_codes)

    user = await UserService.create_user(
        db,
        tenant_id=current_user.tenant_id,
        data=user_data,
        role_codes=role_codes,
        assigned_by=current_user.id,
    )

    # Get tenant name for emails
    tenant_result = await db.execute(
        select(Tenant.name).where(Tenant.id == current_user.tenant_id)
    )
    tenant_name = tenant_result.scalar() or "Your Organization"
    base_url = str(request.base_url).rstrip("/")
    frontend_base = base_url.replace(":8000", ":3000")

    if send_invite:
        # Create invite token and send invite email
        invite, raw_token = await InviteService.create_invite_token(
            db, user.id, current_user.tenant_id, created_by=current_user.id
        )
        activation_url = f"{frontend_base}/auth/activate?token={raw_token}"

        EmailService.fire_and_forget(
            lambda db, _email=data.email, _name=data.first_name,
                   _tenant=tenant_name, _url=activation_url:
                EmailService.send_invite_email(
                    db,
                    to_email=_email,
                    first_name=_name,
                    tenant_name=_tenant,
                    activation_url=_url,
                )
        )
    else:
        # Admin-set password. The password is deliberately NOT emailed: mail is
        # unencrypted at rest in most inboxes and is the wrong channel for a
        # credential. The admin communicates it out-of-band.
        login_url = f"{frontend_base}/auth/login"
        EmailService.fire_and_forget(
            lambda db, _email=data.email, _name=data.first_name, _url=login_url:
                EmailService.send_account_activated_email(
                    db,
                    to_email=_email,
                    first_name=_name,
                    login_url=_url,
                )
        )

    return UserResponse.model_validate(user)


@router.get("/me", response_model=UserResponse)
async def get_my_profile(current_user: User = Depends(get_current_user)):
    return UserResponse.model_validate(current_user)


@router.patch("/me", response_model=UserResponse)
async def update_my_profile(
    data: UserUpdateProfile,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    update_data = data.model_dump(exclude_unset=True)
    await UserService.update_user(db, current_user, update_data)

    # UserService.update_user calls db.refresh(), which expires the eagerly
    # loaded user_roles. UserResponse needs them for `roles`/`primary_role`, and
    # a lazy load here raises MissingGreenlet under asyncio, so re-fetch with
    # the relationship eager-loaded.
    user = await UserService.get_user_by_id(db, current_user.id, current_user.tenant_id)
    return UserResponse.model_validate(user)


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(["tenant_admin", "hr", "manager"])),
):
    user = await UserService.get_user_by_id(db, user_id, current_user.tenant_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse.model_validate(user)


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    data: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(["tenant_admin", "hr"])),
):
    user = await UserService.get_user_by_id(db, user_id, current_user.tenant_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    update_data = data.model_dump(exclude_unset=True)

    if "employee_type" in update_data:
        await _assert_valid_employee_type(
            db, current_user.tenant_id, update_data["employee_type"]
        )

    # Handle role updates separately
    role_codes = update_data.pop("role_codes", None)
    roles_changed = False
    if role_codes is not None:
        # Remove existing non-employee roles, then assign new ones
        current_codes = set(user.role_codes)
        new_codes = set(role_codes)
        if "employee" not in new_codes:
            new_codes.add("employee")

        _assert_may_assign_roles(current_user, list(new_codes - current_codes))
        _assert_may_revoke_roles(current_user, current_codes - new_codes)

        roles_changed = new_codes != current_codes

        # Remove roles no longer assigned
        for code in current_codes - new_codes:
            await RoleService.remove_role(db, user.id, code, current_user.tenant_id)

        # Add new roles
        for code in new_codes - current_codes:
            await RoleService.assign_role(
                db, user.id, code, current_user.tenant_id, assigned_by=current_user.id
            )

        # A role change alters the caller's effective authority, so drop every
        # existing session for that user and force re-authentication.
        user.tokens_valid_from = datetime.now(timezone.utc)

    user = await UserService.update_user(db, user, update_data)

    # Reload to get fresh role data
    user = await UserService.get_user_by_id(db, user.id, current_user.tenant_id)

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

    return UserResponse.model_validate(user)


@router.delete("/{user_id}", status_code=204)
async def delete_user(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(["tenant_admin"])),
):
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")

    user = await UserService.get_user_by_id(db, user_id, current_user.tenant_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Soft delete
    user.is_active = False
    await db.flush()

    # Send account deactivated email (fire-and-forget)
    EmailService.fire_and_forget(
        lambda db: EmailService.send_account_deactivated_email(
            db,
            to_email=user.email,
            first_name=user.first_name,
        )
    )


@router.post("/{user_id}/separate", response_model=UserResponse)
async def separate_employee(
    user_id: int,
    data: UserSeparateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(["tenant_admin"])),
):
    """Mark an employee as resigned or terminated."""
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot separate your own account")

    if data.separation_type not in ("resigned", "terminated"):
        raise HTTPException(status_code=400, detail="separation_type must be 'resigned' or 'terminated'")

    user = await UserService.get_user_by_id(db, user_id, current_user.tenant_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if not user.is_active:
        raise HTTPException(status_code=400, detail="Employee is already inactive")

    user.is_active = False
    user.separation_type = data.separation_type
    user.separation_date = data.separation_date
    user.separation_reason = data.separation_reason
    user.separated_by = current_user.id
    await db.flush()

    # Send notification email
    EmailService.fire_and_forget(
        lambda db: EmailService.send_account_deactivated_email(
            db,
            to_email=user.email,
            first_name=user.first_name,
        )
    )

    user = await UserService.get_user_by_id(db, user_id, current_user.tenant_id)
    return UserResponse.model_validate(user)


@router.post("/{user_id}/reinstate", response_model=UserResponse)
async def reinstate_employee(
    user_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(["tenant_admin"])),
):
    """Reinstate a separated employee back to active status."""
    user = await UserService.get_user_by_id(db, user_id, current_user.tenant_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.is_active:
        raise HTTPException(status_code=400, detail="Employee is already active")

    user.is_active = True
    user.separation_type = None
    user.separation_date = None
    user.separation_reason = None
    user.separated_by = None
    await db.flush()

    # Notify the reinstated user (fire-and-forget).
    base_url = str(request.base_url).rstrip("/")
    login_url = f"{base_url.replace(':8000', ':3000')}/auth/login"
    if user.email:
        EmailService.fire_and_forget(
            lambda db, email=user.email, first_name=user.first_name, url=login_url:
                EmailService.send_account_reinstated_email(
                    db, to_email=email, first_name=first_name, login_url=url,
                )
        )

    user = await UserService.get_user_by_id(db, user_id, current_user.tenant_id)
    return UserResponse.model_validate(user)


@router.post("/{user_id}/resend-invite")
async def resend_invite(
    user_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(["tenant_admin", "hr"])),
):
    user = await UserService.get_user_by_id(db, user_id, current_user.tenant_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

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

    invite, raw_token = await InviteService.resend_invite(
        db, user.id, current_user.tenant_id, created_by=current_user.id
    )

    tenant_result = await db.execute(
        select(Tenant.name).where(Tenant.id == current_user.tenant_id)
    )
    tenant_name = tenant_result.scalar() or "Your Organization"
    base_url = str(request.base_url).rstrip("/")
    frontend_base = base_url.replace(":8000", ":3000")
    activation_url = f"{frontend_base}/auth/activate?token={raw_token}"

    EmailService.fire_and_forget(
        lambda db, _email=user.email, _name=user.first_name,
               _tenant=tenant_name, _url=activation_url:
            EmailService.send_invite_email(
                db,
                to_email=_email,
                first_name=_name,
                tenant_name=_tenant,
                activation_url=_url,
            )
    )

    return {"message": "Invite resent successfully"}
