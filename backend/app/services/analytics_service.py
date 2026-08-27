from datetime import date as date_type, timedelta
from typing import List, Optional
from uuid import UUID

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models.attendance import AttendanceRecord, OvertimeLog
from app.models.leave import LeaveApplication, LeaveType, OvertimeCategory
from app.models.org_hierarchy import OrgNode
from app.models.settings import AppSettings
from app.models.user import User
from app.schemas.analytics import (
    MONTH_LABELS,
    AttendanceMonthSummary,
    AttendanceSummaryResponse,
    AnalyticsOverviewResponse,
    CategoryInfo,
    DashboardLeaveItem,
    DashboardOvertimeItem,
    DashboardResponse,
    LeaveMonthBreakdown,
    LeaveTypeInfo,
    LeaveTrendsResponse,
    OvertimeMonthBreakdown,
    OvertimePaidUnpaidResponse,
    OvertimeTrendsResponse,
    PaidUnpaidMonth,
)


def _empty_months_ot() -> dict:
    """Return a dict keyed 1..12 with empty OvertimeMonthBreakdown shells."""
    return {
        m: {"total_minutes": 0, "total_hours": 0, "by_category": {}, "log_count": 0, "total_pay": 0, "total_credits": 0}
        for m in range(1, 13)
    }


def _empty_months_pu() -> dict:
    return {
        m: {"paid_minutes": 0, "unpaid_minutes": 0, "total_minutes": 0}
        for m in range(1, 13)
    }


def _empty_months_leave() -> dict:
    return {
        m: {"total_days": 0, "application_count": 0, "by_type": {}}
        for m in range(1, 13)
    }


def _empty_months_att() -> dict:
    return {
        m: {
            "total_records": 0, "present_count": 0, "late_count": 0, "absent_count": 0,
            "sum_hours": 0, "total_tardiness_minutes": 0, "total_undertime_minutes": 0, "total_overtime_minutes": 0,
        }
        for m in range(1, 13)
    }


def _ot_statuses(status_filter: Optional[str]) -> Optional[List[str]]:
    """Resolve OT status filter. 'approved' includes 'converted' too."""
    if not status_filter:
        return None
    if status_filter == "approved":
        return ["approved", "converted"]
    return [status_filter]


def _leave_statuses(status_filter: Optional[str]) -> Optional[List[str]]:
    """Resolve leave status filter."""
    if not status_filter:
        return None
    return [status_filter]


class AnalyticsService:

    @staticmethod
    async def get_overtime_monthly_trends(
        db: AsyncSession,
        tenant_id: UUID,
        year: int,
        status_filter: Optional[str] = "approved",
        start_date: Optional[date_type] = None,
        end_date: Optional[date_type] = None,
    ) -> OvertimeTrendsResponse:
        # 1. Fetch tenant's overtime categories
        cat_stmt = (
            select(OvertimeCategory)
            .where(OvertimeCategory.tenant_id == tenant_id)
            .order_by(OvertimeCategory.sort_order, OvertimeCategory.id)
        )
        cat_result = await db.execute(cat_stmt)
        categories = list(cat_result.scalars().all())

        # 2. Aggregate query
        month_col = func.extract("month", OvertimeLog.date).label("month")
        stmt = (
            select(
                month_col,
                func.coalesce(OvertimeCategory.code, "uncategorized").label("cat_code"),
                func.sum(OvertimeLog.overtime_minutes).label("total_minutes"),
                func.count(OvertimeLog.id).label("log_count"),
                func.coalesce(func.sum(OvertimeLog.pay_amount), 0).label("total_pay"),
                func.coalesce(func.sum(OvertimeLog.leave_credits_earned), 0).label("total_credits"),
            )
            .outerjoin(OvertimeCategory, OvertimeCategory.id == OvertimeLog.overtime_category_id)
            .where(
                OvertimeLog.tenant_id == tenant_id,
                func.extract("year", OvertimeLog.date) == year,
            )
        )
        if start_date:
            stmt = stmt.where(OvertimeLog.date >= start_date)
        if end_date:
            stmt = stmt.where(OvertimeLog.date <= end_date)
        ot_stats = _ot_statuses(status_filter)
        if ot_stats:
            stmt = stmt.where(OvertimeLog.status.in_(ot_stats))

        stmt = stmt.group_by(month_col, OvertimeCategory.code).order_by(month_col)
        result = await db.execute(stmt)
        rows = result.all()

        # 3. Build 12 months
        months_data = _empty_months_ot()
        for row in rows:
            m = int(row.month)
            d = months_data[m]
            d["total_minutes"] += float(row.total_minutes or 0)
            d["total_hours"] = round(d["total_minutes"] / 60, 1)
            d["log_count"] += int(row.log_count or 0)
            d["total_pay"] += float(row.total_pay or 0)
            d["total_credits"] += float(row.total_credits or 0)
            d["by_category"][row.cat_code] = float(row.total_minutes or 0)

        return OvertimeTrendsResponse(
            year=year,
            categories=[
                CategoryInfo(code=c.code, name=c.name, compensation_type=c.compensation_type)
                for c in categories
            ],
            months=[
                OvertimeMonthBreakdown(
                    month=m,
                    month_label=MONTH_LABELS[m],
                    **months_data[m],
                )
                for m in range(1, 13)
            ],
        )

    @staticmethod
    async def get_overtime_paid_vs_unpaid(
        db: AsyncSession,
        tenant_id: UUID,
        year: int,
        status_filter: Optional[str] = "approved",
        start_date: Optional[date_type] = None,
        end_date: Optional[date_type] = None,
    ) -> OvertimePaidUnpaidResponse:
        month_col = func.extract("month", OvertimeLog.date).label("month")

        paid_case = case(
            (OvertimeCategory.compensation_type.in_(["paid", "both"]), OvertimeLog.overtime_minutes),
            else_=0,
        )
        unpaid_case = case(
            (OvertimeCategory.compensation_type.in_(["leave_credit", "none"]), OvertimeLog.overtime_minutes),
            else_=0,
        )
        # If no category (NULL), treat as uncategorized/unpaid
        null_case = case(
            (OvertimeCategory.id.is_(None), OvertimeLog.overtime_minutes),
            else_=0,
        )

        stmt = (
            select(
                month_col,
                func.sum(paid_case).label("paid_minutes"),
                func.sum(unpaid_case + null_case).label("unpaid_minutes"),
                func.sum(OvertimeLog.overtime_minutes).label("total_minutes"),
            )
            .outerjoin(OvertimeCategory, OvertimeCategory.id == OvertimeLog.overtime_category_id)
            .where(
                OvertimeLog.tenant_id == tenant_id,
                func.extract("year", OvertimeLog.date) == year,
            )
        )
        if start_date:
            stmt = stmt.where(OvertimeLog.date >= start_date)
        if end_date:
            stmt = stmt.where(OvertimeLog.date <= end_date)
        ot_stats = _ot_statuses(status_filter)
        if ot_stats:
            stmt = stmt.where(OvertimeLog.status.in_(ot_stats))

        stmt = stmt.group_by(month_col).order_by(month_col)
        result = await db.execute(stmt)
        rows = result.all()

        months_data = _empty_months_pu()
        for row in rows:
            m = int(row.month)
            months_data[m]["paid_minutes"] = float(row.paid_minutes or 0)
            months_data[m]["unpaid_minutes"] = float(row.unpaid_minutes or 0)
            months_data[m]["total_minutes"] = float(row.total_minutes or 0)

        return OvertimePaidUnpaidResponse(
            year=year,
            months=[
                PaidUnpaidMonth(
                    month=m,
                    month_label=MONTH_LABELS[m],
                    paid_minutes=months_data[m]["paid_minutes"],
                    paid_hours=round(months_data[m]["paid_minutes"] / 60, 1),
                    unpaid_minutes=months_data[m]["unpaid_minutes"],
                    unpaid_hours=round(months_data[m]["unpaid_minutes"] / 60, 1),
                    total_minutes=months_data[m]["total_minutes"],
                    total_hours=round(months_data[m]["total_minutes"] / 60, 1),
                )
                for m in range(1, 13)
            ],
        )

    @staticmethod
    async def get_leave_monthly_trends(
        db: AsyncSession,
        tenant_id: UUID,
        year: int,
        status_filter: Optional[str] = "approved",
        start_date: Optional[date_type] = None,
        end_date: Optional[date_type] = None,
    ) -> LeaveTrendsResponse:
        # 1. Fetch tenant's leave types
        lt_stmt = (
            select(LeaveType)
            .where(LeaveType.tenant_id == tenant_id, LeaveType.is_active.is_(True))
            .order_by(LeaveType.sort_order, LeaveType.id)
        )
        lt_result = await db.execute(lt_stmt)
        leave_types = list(lt_result.scalars().all())

        # 2. Aggregate query - join on code+tenant_id since leave_type is a string
        month_col = func.extract("month", LeaveApplication.start_date).label("month")
        stmt = (
            select(
                month_col,
                LeaveApplication.leave_type.label("lt_code"),
                func.coalesce(LeaveType.name, LeaveApplication.leave_type).label("lt_name"),
                func.sum(LeaveApplication.days_requested).label("total_days"),
                func.count(LeaveApplication.id).label("app_count"),
            )
            .outerjoin(
                LeaveType,
                and_(
                    LeaveType.code == LeaveApplication.leave_type,
                    LeaveType.tenant_id == LeaveApplication.tenant_id,
                ),
            )
            .where(
                LeaveApplication.tenant_id == tenant_id,
                func.extract("year", LeaveApplication.start_date) == year,
            )
        )
        if start_date:
            stmt = stmt.where(LeaveApplication.start_date >= start_date)
        if end_date:
            stmt = stmt.where(LeaveApplication.start_date <= end_date)
        lv_stats = _leave_statuses(status_filter)
        if lv_stats:
            stmt = stmt.where(LeaveApplication.status.in_(lv_stats))

        stmt = stmt.group_by(month_col, LeaveApplication.leave_type, LeaveType.name).order_by(month_col)
        result = await db.execute(stmt)
        rows = result.all()

        # 3. Build 12 months
        months_data = _empty_months_leave()
        for row in rows:
            m = int(row.month)
            d = months_data[m]
            days = float(row.total_days or 0)
            count = int(row.app_count or 0)
            d["total_days"] += days
            d["application_count"] += count
            d["by_type"][row.lt_code] = days

        return LeaveTrendsResponse(
            year=year,
            leave_types=[
                LeaveTypeInfo(code=lt.code, name=lt.name)
                for lt in leave_types
            ],
            months=[
                LeaveMonthBreakdown(
                    month=m,
                    month_label=MONTH_LABELS[m],
                    **months_data[m],
                )
                for m in range(1, 13)
            ],
        )

    @staticmethod
    async def get_attendance_summary(
        db: AsyncSession,
        tenant_id: UUID,
        year: int,
        start_date: Optional[date_type] = None,
        end_date: Optional[date_type] = None,
    ) -> AttendanceSummaryResponse:
        month_col = func.extract("month", AttendanceRecord.date).label("month")
        stmt = (
            select(
                month_col,
                AttendanceRecord.status.label("att_status"),
                func.count(AttendanceRecord.id).label("record_count"),
                func.coalesce(func.sum(AttendanceRecord.hours_worked), 0).label("sum_hours"),
                func.coalesce(func.sum(AttendanceRecord.tardiness_minutes), 0).label("sum_tardiness"),
                func.coalesce(func.sum(AttendanceRecord.undertime_minutes), 0).label("sum_undertime"),
                func.coalesce(func.sum(AttendanceRecord.overtime_minutes), 0).label("sum_overtime"),
            )
            .where(
                AttendanceRecord.tenant_id == tenant_id,
                func.extract("year", AttendanceRecord.date) == year,
            )
        )
        if start_date:
            stmt = stmt.where(AttendanceRecord.date >= start_date)
        if end_date:
            stmt = stmt.where(AttendanceRecord.date <= end_date)
        stmt = stmt.group_by(month_col, AttendanceRecord.status).order_by(month_col)
        result = await db.execute(stmt)
        rows = result.all()

        months_data = _empty_months_att()
        for row in rows:
            m = int(row.month)
            d = months_data[m]
            cnt = int(row.record_count or 0)
            d["total_records"] += cnt
            d["sum_hours"] += float(row.sum_hours or 0)
            d["total_tardiness_minutes"] += int(row.sum_tardiness or 0)
            d["total_undertime_minutes"] += int(row.sum_undertime or 0)
            d["total_overtime_minutes"] += int(row.sum_overtime or 0)

            status = row.att_status or "present"
            if status in ("present", "half_day", "excused"):
                d["present_count"] += cnt
            elif status == "late":
                d["late_count"] += cnt
            elif status == "absent":
                d["absent_count"] += cnt
            else:
                d["present_count"] += cnt

        return AttendanceSummaryResponse(
            year=year,
            months=[
                AttendanceMonthSummary(
                    month=m,
                    month_label=MONTH_LABELS[m],
                    total_records=months_data[m]["total_records"],
                    present_count=months_data[m]["present_count"],
                    late_count=months_data[m]["late_count"],
                    absent_count=months_data[m]["absent_count"],
                    avg_hours_worked=round(months_data[m]["sum_hours"] / months_data[m]["total_records"], 1) if months_data[m]["total_records"] else 0,
                    total_tardiness_minutes=months_data[m]["total_tardiness_minutes"],
                    total_undertime_minutes=months_data[m]["total_undertime_minutes"],
                    total_overtime_minutes=months_data[m]["total_overtime_minutes"],
                )
                for m in range(1, 13)
            ],
        )

    @staticmethod
    async def _analytics_user_filter(db: AsyncSession, tenant_id: UUID):
        """Condition excluding long-separated employees from computed headcount.

        AppSettings.analytics_exclusion_days is the grace window: a separated
        employee keeps counting for that many days after their separation date,
        then drops out of the metrics. 0 (the default) drops them immediately.
        Employees with no separation date always count.
        """
        days = (await db.execute(
            select(AppSettings.analytics_exclusion_days).where(
                AppSettings.tenant_id == tenant_id
            )
        )).scalar()
        cutoff = date_type.today() - timedelta(days=days or 0)
        return or_(
            User.separation_date.is_(None),
            User.separation_date >= cutoff,
        )

    @staticmethod
    async def get_headcount_summary(
        db: AsyncSession,
        tenant_id: UUID,
    ) -> AnalyticsOverviewResponse:
        not_excluded = await AnalyticsService._analytics_user_filter(db, tenant_id)

        total = (await db.execute(
            select(func.count(User.id)).where(User.tenant_id == tenant_id, not_excluded)
        )).scalar() or 0

        active = (await db.execute(
            select(func.count(User.id)).where(User.tenant_id == tenant_id, User.is_active.is_(True))
        )).scalar() or 0

        return AnalyticsOverviewResponse(
            total=total,
            active=active,
            inactive=total - active,
        )

    @staticmethod
    async def get_dashboard_data(
        db: AsyncSession,
        tenant_id: UUID,
    ) -> DashboardResponse:
        today = date_type.today()
        month_start = today.replace(day=1)

        # Employee counts
        not_excluded = await AnalyticsService._analytics_user_filter(db, tenant_id)
        total_employees = (await db.execute(
            select(func.count(User.id)).where(User.tenant_id == tenant_id, not_excluded)
        )).scalar() or 0

        active_employees = (await db.execute(
            select(func.count(User.id)).where(User.tenant_id == tenant_id, User.is_active.is_(True))
        )).scalar() or 0

        # Department count
        departments = (await db.execute(
            select(func.count(OrgNode.id)).where(OrgNode.tenant_id == tenant_id)
        )).scalar() or 0

        # Pending leaves
        pending_leaves = (await db.execute(
            select(func.count(LeaveApplication.id)).where(
                LeaveApplication.tenant_id == tenant_id,
                LeaveApplication.status == "pending",
            )
        )).scalar() or 0

        # Pending overtime
        pending_overtime = (await db.execute(
            select(func.count(OvertimeLog.id)).where(
                OvertimeLog.tenant_id == tenant_id,
                OvertimeLog.status == "pending",
            )
        )).scalar() or 0

        # Today's attendance
        today_stmt = (
            select(
                AttendanceRecord.status,
                func.count(AttendanceRecord.id).label("cnt"),
            )
            .where(
                AttendanceRecord.tenant_id == tenant_id,
                AttendanceRecord.date == today,
            )
            .group_by(AttendanceRecord.status)
        )
        today_result = await db.execute(today_stmt)
        today_present = 0
        today_late = 0
        today_absent = 0
        for row in today_result.all():
            status = row.status or "present"
            cnt = int(row.cnt)
            if status == "late":
                today_late += cnt
            elif status == "absent":
                today_absent += cnt
            else:
                today_present += cnt

        # Month-to-date attendance
        month_att_stmt = (
            select(
                AttendanceRecord.status,
                func.count(AttendanceRecord.id).label("cnt"),
            )
            .where(
                AttendanceRecord.tenant_id == tenant_id,
                AttendanceRecord.date >= month_start,
                AttendanceRecord.date <= today,
            )
            .group_by(AttendanceRecord.status)
        )
        month_att = await db.execute(month_att_stmt)
        month_total = 0
        month_present = 0
        month_late_count = 0
        for row in month_att.all():
            cnt = int(row.cnt)
            month_total += cnt
            status = row.status or "present"
            if status == "late":
                month_late_count += cnt
            elif status != "absent":
                month_present += cnt

        month_attendance_rate = round((month_present + month_late_count) / month_total * 100, 1) if month_total else 0

        # Month OT hours (approved + converted)
        month_ot = (await db.execute(
            select(func.coalesce(func.sum(OvertimeLog.overtime_minutes), 0)).where(
                OvertimeLog.tenant_id == tenant_id,
                OvertimeLog.date >= month_start,
                OvertimeLog.date <= today,
                OvertimeLog.status.in_(["approved", "converted"]),
            )
        )).scalar() or 0
        month_ot_hours = round(float(month_ot) / 60, 1)

        # Month leave days (approved)
        month_leave_days = (await db.execute(
            select(func.coalesce(func.sum(LeaveApplication.days_requested), 0)).where(
                LeaveApplication.tenant_id == tenant_id,
                LeaveApplication.start_date >= month_start,
                LeaveApplication.start_date <= today,
                LeaveApplication.status == "approved",
            )
        )).scalar() or 0

        # Recent leave applications (latest 5)
        recent_leaves_stmt = (
            select(LeaveApplication)
            .options(joinedload(LeaveApplication.employee))
            .where(LeaveApplication.tenant_id == tenant_id)
            .order_by(LeaveApplication.created_at.desc())
            .limit(5)
        )
        recent_leaves_result = await db.execute(recent_leaves_stmt)
        recent_leaves = recent_leaves_result.scalars().all()

        recent_leave_items = [
            DashboardLeaveItem(
                id=la.id,
                employee_name=f"{la.employee.first_name} {la.employee.last_name}" if la.employee else "Unknown",
                leave_type=la.leave_type,
                start_date=str(la.start_date),
                end_date=str(la.end_date),
                days=float(la.days_requested),
                status=la.status,
            )
            for la in recent_leaves
        ]

        # Recent overtime logs (latest 5)
        recent_ot_stmt = (
            select(OvertimeLog)
            .options(
                joinedload(OvertimeLog.employee),
                joinedload(OvertimeLog.overtime_category),
            )
            .where(OvertimeLog.tenant_id == tenant_id)
            .order_by(OvertimeLog.created_at.desc())
            .limit(5)
        )
        recent_ot_result = await db.execute(recent_ot_stmt)
        recent_ots = recent_ot_result.unique().scalars().all()

        recent_ot_items = [
            DashboardOvertimeItem(
                id=ot.id,
                employee_name=f"{ot.employee.first_name} {ot.employee.last_name}" if ot.employee else "Unknown",
                category=ot.overtime_category.name if ot.overtime_category else "Uncategorized",
                date=str(ot.date),
                hours=round(float(ot.overtime_minutes or 0) / 60, 1),
                status=ot.status,
            )
            for ot in recent_ots
        ]

        return DashboardResponse(
            total_employees=total_employees,
            active_employees=active_employees,
            departments=departments,
            pending_leaves=pending_leaves,
            pending_overtime=pending_overtime,
            today_present=today_present,
            today_late=today_late,
            today_absent=today_absent,
            month_attendance_rate=month_attendance_rate,
            month_late_count=month_late_count,
            month_ot_hours=month_ot_hours,
            month_leave_days=float(month_leave_days),
            recent_leave_applications=recent_leave_items,
            recent_overtime_logs=recent_ot_items,
        )
