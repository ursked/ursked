"""Analytics dashboards and the home-screen dashboard.

Access follows the permission contract: reports:view is "analytics dashboards".
Until 2026-09 these endpoints checked three hard-coded role codes, so unticking
reports:view on the Permissions screen changed nothing, and a manager saw
company-wide leave and overtime. Scope now comes from access_scope: roles in
FULL_SCOPE_ROLES["reports"] see everyone, anyone else sees the employees they
manage.

The dashboard is the exception: it is everyone's home screen, so it answers
every signed-in user and decides inside what to include.
"""

from datetime import date
from typing import Optional, Set

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import get_current_user, require_permission
from app.models.user import User
from app.schemas.analytics import (
    AnalyticsOverviewResponse,
    AttendanceSummaryResponse,
    DashboardResponse,
    LeaveTrendsResponse,
    OvertimePaidUnpaidResponse,
    OvertimeTrendsResponse,
)
from app.services.access_scope import managed_employee_ids
from app.services.analytics_service import AnalyticsService
from app.services.permission_service import PermissionService
from app.utils.timeutil import company_today


def _no_store(response: Response) -> None:
    """Team figures must never be kept by a browser, proxy or the app's service
    worker once the session that fetched them is gone."""
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(
    prefix="/analytics",
    tags=["Analytics"],
    dependencies=[Depends(_no_store)],
)

# "approved" stays the default when the parameter is absent; "all"
# (analytics_service.ALL_STATUSES) switches the filter off.
STATUS_PATTERN = "^(all|approved|pending|rejected|cancelled|converted)?$"


async def _scope(db: AsyncSession, user: User) -> Optional[Set[int]]:
    return await managed_employee_ids(db, user, "reports")


async def _can_view_reports(db: AsyncSession, user: User) -> bool:
    if user.has_role("tenant_admin"):
        return True
    role_ids = [ur.role_id for ur in user.user_roles]
    return await PermissionService.check_permission(
        db, user.tenant_id, role_ids, "reports", "view"
    )


@router.get("/overtime/trends", response_model=OvertimeTrendsResponse)
async def get_overtime_trends(
    year: Optional[int] = Query(default=None, ge=2020, le=2100),
    status: Optional[str] = Query(default="approved", pattern=STATUS_PATTERN),
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    current_user: User = Depends(require_permission("reports", "view")),
    db: AsyncSession = Depends(get_db),
):
    """Monthly overtime trends grouped by overtime category."""
    if year is None:
        year = (await company_today(db, current_user.tenant_id)).year
    return await AnalyticsService.get_overtime_monthly_trends(
        db, current_user.tenant_id, year,
        status_filter=status or None,
        start_date=start_date,
        end_date=end_date,
        employee_ids=await _scope(db, current_user),
    )


@router.get("/overtime/paid-vs-unpaid", response_model=OvertimePaidUnpaidResponse)
async def get_overtime_paid_vs_unpaid(
    year: Optional[int] = Query(default=None, ge=2020, le=2100),
    status: Optional[str] = Query(default="approved", pattern=STATUS_PATTERN),
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    current_user: User = Depends(require_permission("reports", "view")),
    db: AsyncSession = Depends(get_db),
):
    """Monthly paid vs unpaid overtime breakdown."""
    if year is None:
        year = (await company_today(db, current_user.tenant_id)).year
    return await AnalyticsService.get_overtime_paid_vs_unpaid(
        db, current_user.tenant_id, year,
        status_filter=status or None,
        start_date=start_date,
        end_date=end_date,
        employee_ids=await _scope(db, current_user),
    )


@router.get("/leave/trends", response_model=LeaveTrendsResponse)
async def get_leave_trends(
    year: Optional[int] = Query(default=None, ge=2020, le=2100),
    status: Optional[str] = Query(default="approved", pattern=STATUS_PATTERN),
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    current_user: User = Depends(require_permission("reports", "view")),
    db: AsyncSession = Depends(get_db),
):
    """Monthly leave trends grouped by leave type."""
    if year is None:
        year = (await company_today(db, current_user.tenant_id)).year
    return await AnalyticsService.get_leave_monthly_trends(
        db, current_user.tenant_id, year,
        status_filter=status or None,
        start_date=start_date,
        end_date=end_date,
        employee_ids=await _scope(db, current_user),
    )


@router.get("/attendance/summary", response_model=AttendanceSummaryResponse)
async def get_attendance_summary(
    year: Optional[int] = Query(default=None, ge=2020, le=2100),
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    current_user: User = Depends(require_permission("reports", "view")),
    db: AsyncSession = Depends(get_db),
):
    """Monthly attendance metrics summary."""
    if year is None:
        year = (await company_today(db, current_user.tenant_id)).year
    return await AnalyticsService.get_attendance_summary(
        db, current_user.tenant_id, year,
        start_date=start_date,
        end_date=end_date,
        employee_ids=await _scope(db, current_user),
    )


@router.get("/overview", response_model=AnalyticsOverviewResponse)
async def get_analytics_overview(
    current_user: User = Depends(require_permission("reports", "view")),
    db: AsyncSession = Depends(get_db),
):
    """Current headcount overview for KPI cards."""
    return await AnalyticsService.get_headcount_summary(
        db, current_user.tenant_id, employee_ids=await _scope(db, current_user)
    )


@router.get("/dashboard", response_model=DashboardResponse)
async def get_dashboard(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The home screen for whoever is signed in.

    Everyone gets their own summary (next shifts, leave left, pending requests,
    clock status). reports:view holders also get the metrics block: company-wide
    for full-scope roles, their own teams otherwise. An employee used to get a
    403 here on every load and every 60-second refresh.
    """
    personal = await AnalyticsService.get_personal_summary(db, current_user)
    if not await _can_view_reports(db, current_user):
        return DashboardResponse(view="personal", metrics=None, personal=personal)

    ids = await _scope(db, current_user)
    metrics = await AnalyticsService.get_dashboard_data(
        db, current_user.tenant_id, employee_ids=ids, viewer_id=current_user.id
    )
    return DashboardResponse(
        view="company" if ids is None else "team",
        metrics=metrics,
        personal=personal,
    )
