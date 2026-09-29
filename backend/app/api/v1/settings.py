from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import get_current_user, require_permission, require_role
from app.models.user import User
from app.schemas.payroll import PAY_RULE_FIELDS
from app.schemas.settings import (
    AppSettingsResponse,
    AppSettingsUpdate,
    ShiftStatusTypeCreate,
    ShiftStatusTypeResponse,
    ShiftStatusTypeUpdate,
    UserPreferencesResponse,
    UserPreferencesUpdate,
)
from app.services.settings_service import NULLABLE_APP_SETTINGS, SettingsService

router = APIRouter(prefix="/settings", tags=["Settings"])


# ── App Settings ─────────────────────────────────────────────────────

@router.get("/app", response_model=AppSettingsResponse)
async def get_app_settings(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    settings = await SettingsService.get_or_create_app_settings(db, current_user.tenant_id)
    return AppSettingsResponse.model_validate(settings)


@router.patch("/app", response_model=AppSettingsResponse)
async def update_app_settings(
    data: AppSettingsUpdate,
    current_user: User = Depends(require_permission("settings", "edit")),
    db: AsyncSession = Depends(get_db),
):
    """Company settings are settings:edit, per the permission contract. This
    was hard-coded to tenant_admin, so the Permissions screen could not grant
    or withhold it."""
    changes = data.model_dump(exclude_unset=True)
    current = await SettingsService.get_or_create_app_settings(db, current_user.tenant_id)
    # Pay rules (working days per month, night and holiday premiums) belong to
    # Finances and change only through PUT /payroll/pay-rules, under
    # finances:edit: editing settings must not let someone change what
    # everyone is paid. A client that sends them back unchanged (an older
    # screen saving the whole object) is not refused; a real change is.
    for field in PAY_RULE_FIELDS:
        if field not in changes:
            continue
        value = changes.pop(field)
        if value is None and field not in NULLABLE_APP_SETTINGS:
            continue  # None means "no change" for these, as everywhere else
        if value != getattr(current, field):
            raise HTTPException(status_code=403, detail="Pay rules are managed in Finances.")
    settings = await SettingsService.update_app_settings(db, current_user.tenant_id, changes)
    return AppSettingsResponse.model_validate(settings)


# ── Shift Status Types ───────────────────────────────────────────────
# Managed from Policies -> Shift Status Types; the screen mirrors these gates
# (tests/test_status_types_gate.py). Reading stays open to every signed-in
# user because the schedule grid and My Schedule draw every shift with it.

@router.get("/status-types", response_model=List[ShiftStatusTypeResponse])
async def get_status_types(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    types = await SettingsService.get_status_types(db, current_user.tenant_id)
    return [ShiftStatusTypeResponse.model_validate(t) for t in types]


@router.post("/status-types", response_model=ShiftStatusTypeResponse, status_code=201)
async def create_status_type(
    data: ShiftStatusTypeCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(["tenant_admin"])),
):
    try:
        status_type = await SettingsService.create_status_type(
            db, current_user.tenant_id, data.model_dump()
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return ShiftStatusTypeResponse.model_validate(status_type)


@router.patch("/status-types/{status_id}", response_model=ShiftStatusTypeResponse)
async def update_status_type(
    status_id: int,
    data: ShiftStatusTypeUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(["tenant_admin"])),
):
    status_type = await SettingsService.update_status_type(
        db, status_id, current_user.tenant_id, data.model_dump(exclude_unset=True)
    )
    if not status_type:
        raise HTTPException(status_code=404, detail="Status type not found")
    return ShiftStatusTypeResponse.model_validate(status_type)


@router.delete("/status-types/{status_id}", status_code=204)
async def delete_status_type(
    status_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(["tenant_admin"])),
):
    try:
        deleted = await SettingsService.delete_status_type(
            db, status_id, current_user.tenant_id
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not deleted:
        raise HTTPException(status_code=404, detail="Status type not found")


# ── User Preferences ─────────────────────────────────────────────

@router.get("/preferences", response_model=UserPreferencesResponse)
async def get_user_preferences(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get current user's preferences. Any authenticated user can access their own."""
    prefs = await SettingsService.get_user_preferences(
        db, current_user.id, current_user.tenant_id
    )
    resp = UserPreferencesResponse.model_validate(prefs)
    resp.org_timezone = await SettingsService.get_tenant_timezone(db, current_user.tenant_id)
    return resp


@router.patch("/preferences", response_model=UserPreferencesResponse)
async def update_user_preferences(
    data: UserPreferencesUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update current user's preferences. Any authenticated user can update their own."""
    prefs = await SettingsService.update_user_preferences(
        db, current_user.id, current_user.tenant_id,
        data.model_dump(exclude_unset=True),
    )
    resp = UserPreferencesResponse.model_validate(prefs)
    resp.org_timezone = await SettingsService.get_tenant_timezone(db, current_user.tenant_id)
    return resp


# ── Area A: setup checklist, background jobs, data retention ─────────
#
# The tenant audit trail is served by GET /audit/logs (the Audit Log page);
# the duplicate GET /settings/audit-log that used to live here had no caller.

def _is_enterprise() -> bool:
    from app.api.v1.smtp_settings import _is_enterprise as check

    return check()


def _own_or_system(column, tenant_id):
    """Rows for this tenant, plus tenant-less system rows on Community (a
    single-tenant install, where they can only be this company's). On the
    multi-tenant SaaS those belong to the operator, not to any one tenant."""
    if _is_enterprise():
        return column == tenant_id
    return or_(column == tenant_id, column.is_(None))


@router.get("/setup-status")
async def get_setup_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(["tenant_admin", "hr"])),
):
    """Onboarding checklist for the dashboard: which setup steps are done.

    Same audience as the card (administrators and HR). Exists in both
    editions; the card used to call an Enterprise-only route and showed an
    error on every Community dashboard."""
    from app.services.setup_status_service import SetupStatusService

    steps = await SetupStatusService.get_status(db, current_user.tenant_id)
    done = sum(1 for step in steps if step["done"])
    return {"steps": steps, "completed": done, "total": len(steps)}


@router.get("/background-jobs")
async def get_background_jobs(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(["tenant_admin"])),
    limit: int = Query(100, ge=1, le=500),
):
    """Read-only view of the scheduler: its jobs, recent runs, and the email
    outbox. Bodies of queued emails are never returned (they can carry
    activation and reset links)."""
    from app.models.email_outbox import EmailOutbox
    from app.models.job_run import JobRun
    from app.services.email_service import MAX_ATTEMPTS
    from app.services.job_service import STALE_AFTER
    from app.services.scheduler import JOBS, TICK_SECONDS
    from app.utils.timeutil import as_utc

    def _iso(value):
        value = as_utc(value)
        return value.isoformat() if value else None

    tid = current_user.tenant_id
    runs = (await db.execute(
        sa_select(JobRun)
        .where(_own_or_system(JobRun.tenant_id, tid))
        .order_by(JobRun.started_at.desc(), JobRun.id.desc())
        .limit(limit)
    )).scalars().all()

    outbox_filter = _own_or_system(EmailOutbox.tenant_id, tid)
    counts = dict((await db.execute(
        sa_select(EmailOutbox.status, func.count())
        .where(outbox_filter)
        .group_by(EmailOutbox.status)
    )).all())
    pending = (await db.execute(
        sa_select(EmailOutbox)
        .where(outbox_filter, EmailOutbox.status.in_(("queued", "failed", "skipped")))
        .order_by(EmailOutbox.created_at.desc(), EmailOutbox.id.desc())
        .limit(limit)
    )).scalars().all()

    return {
        "tick_seconds": TICK_SECONDS,
        "stale_after_minutes": int(STALE_AFTER.total_seconds() // 60),
        "max_email_attempts": MAX_ATTEMPTS,
        "jobs": [{"name": j.name, "cadence": j.cadence} for j in JOBS],
        "runs": [
            {
                "id": r.id,
                "job_name": r.job_name,
                "period_key": r.period_key,
                "status": r.status,
                "started_at": _iso(r.started_at),
                "finished_at": _iso(r.finished_at),
                "error": r.error,
                "meta": r.meta,
            }
            for r in runs
        ],
        "outbox": {
            "counts": {k: int(counts.get(k, 0)) for k in ("queued", "sent", "failed", "skipped")},
            "items": [
                {
                    "id": o.id,
                    "to_email": o.to_email,
                    "subject": o.subject,
                    "type": o.log_type,
                    "status": o.status,
                    "attempts": o.attempts,
                    "next_attempt_at": _iso(o.next_attempt_at),
                    "last_error": o.last_error,
                    "created_at": _iso(o.created_at),
                }
                for o in pending
            ],
        },
    }


@router.post("/background-jobs/outbox/{outbox_id}/retry")
async def retry_outbox_email(
    outbox_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(["tenant_admin"])),
):
    """Queue a failed or skipped email again; it goes out on the next tick."""
    from app.services.email_service import EmailService

    ok = await EmailService.retry_outbox(
        db, outbox_id, current_user.tenant_id, include_untenanted=not _is_enterprise()
    )
    if not ok:
        raise HTTPException(
            status_code=404,
            detail="That email is not waiting to be retried. It may have been sent already.",
        )
    await db.commit()
    return {"id": outbox_id, "status": "queued"}


@router.get("/retention-report")
async def get_retention_report(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(["tenant_admin"])),
):
    """Records due for deletion under the data retention setting, by type.
    Read-only: nothing is ever deleted automatically."""
    from app.services.housekeeping_service import retention_report

    return await retention_report(db, current_user.tenant_id)
