from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import require_role
from app.models.user import User
from app.schemas.analytics import (
    AnalyticsOverviewResponse,
    AttendanceSummaryResponse,
    DashboardResponse,
    LeaveTrendsResponse,
    OvertimePaidUnpaidResponse,
    OvertimeTrendsResponse,
)
from app.services.analytics_service import AnalyticsService

router = APIRouter(prefix="/analytics", tags=["Analytics"])

ANALYTICS_ROLES = ["tenant_admin", "hr", "manager"]


@router.get("/overtime/trends", response_model=OvertimeTrendsResponse)
async def get_overtime_trends(
    year: Optional[int] = Query(default=None, ge=2020, le=2100),
    status: Optional[str] = Query(default="approved"),
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    current_user: User = Depends(require_role(ANALYTICS_ROLES)),
    db: AsyncSession = Depends(get_db),
):
    """Monthly overtime trends grouped by overtime category."""
    if year is None:
        year = date.today().year
    return await AnalyticsService.get_overtime_monthly_trends(
        db, current_user.tenant_id, year,
        status_filter=status or None,
        start_date=start_date,
        end_date=end_date,
    )


@router.get("/overtime/paid-vs-unpaid", response_model=OvertimePaidUnpaidResponse)
async def get_overtime_paid_vs_unpaid(
    year: Optional[int] = Query(default=None, ge=2020, le=2100),
    status: Optional[str] = Query(default="approved"),
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    current_user: User = Depends(require_role(ANALYTICS_ROLES)),
    db: AsyncSession = Depends(get_db),
):
    """Monthly paid vs unpaid overtime breakdown."""
    if year is None:
        year = date.today().year
    return await AnalyticsService.get_overtime_paid_vs_unpaid(
        db, current_user.tenant_id, year,
        status_filter=status or None,
        start_date=start_date,
        end_date=end_date,
    )


@router.get("/leave/trends", response_model=LeaveTrendsResponse)
async def get_leave_trends(
    year: Optional[int] = Query(default=None, ge=2020, le=2100),
    status: Optional[str] = Query(default="approved"),
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    current_user: User = Depends(require_role(ANALYTICS_ROLES)),
    db: AsyncSession = Depends(get_db),
):
    """Monthly leave trends grouped by leave type."""
    if year is None:
        year = date.today().year
    return await AnalyticsService.get_leave_monthly_trends(
        db, current_user.tenant_id, year,
        status_filter=status or None,
        start_date=start_date,
        end_date=end_date,
    )


@router.get("/attendance/summary", response_model=AttendanceSummaryResponse)
async def get_attendance_summary(
    year: Optional[int] = Query(default=None, ge=2020, le=2100),
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
    current_user: User = Depends(require_role(ANALYTICS_ROLES)),
    db: AsyncSession = Depends(get_db),
):
    """Monthly attendance metrics summary."""
    if year is None:
        year = date.today().year
    return await AnalyticsService.get_attendance_summary(
        db, current_user.tenant_id, year,
        start_date=start_date,
        end_date=end_date,
    )


@router.get("/overview", response_model=AnalyticsOverviewResponse)
async def get_analytics_overview(
    current_user: User = Depends(require_role(ANALYTICS_ROLES)),
    db: AsyncSession = Depends(get_db),
):
    """Current headcount overview for KPI cards."""
    return await AnalyticsService.get_headcount_summary(db, current_user.tenant_id)


@router.get("/dashboard", response_model=DashboardResponse)
async def get_dashboard(
    current_user: User = Depends(require_role(ANALYTICS_ROLES)),
    db: AsyncSession = Depends(get_db),
):
    """Dashboard KPIs, today's attendance, and recent activity."""
    return await AnalyticsService.get_dashboard_data(db, current_user.tenant_id)
