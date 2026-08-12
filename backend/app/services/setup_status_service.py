"""Tenant setup completeness, powering the dashboard onboarding checklist.

Each step is a cheap COUNT/EXISTS query. Results are cached briefly in-process
so the dashboard can poll without hammering the DB.
"""
import time
from dataclasses import dataclass
from datetime import date
from typing import Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.configurable_types import EmployeeType, ScheduleFormat
from app.models.leave import LeavePolicy, LeaveType
from app.models.org_hierarchy import OrgNode
from app.models.payroll import DeductionType, SalaryGrade
from app.models.schedule import DateRemark
from app.models.settings import EmailSettings
from app.models.user import User

_CACHE: dict[UUID, tuple[float, list[dict]]] = {}
_TTL = 60.0


@dataclass
class Step:
    key: str
    label: str
    done: bool
    count: int
    link: str


class SetupStatusService:

    @staticmethod
    async def _count(db: AsyncSession, model, *conds) -> int:
        stmt = select(func.count()).select_from(model)
        for c in conds:
            stmt = stmt.where(c)
        return int((await db.execute(stmt)).scalar() or 0)

    @staticmethod
    async def get_status(db: AsyncSession, tenant_id: UUID) -> list[dict]:
        cached = _CACHE.get(tenant_id)
        if cached and (time.monotonic() - cached[0]) < _TTL:
            return cached[1]

        year = date.today().year
        org = await SetupStatusService._count(db, OrgNode, OrgNode.tenant_id == tenant_id)
        emp_types = await SetupStatusService._count(
            db, EmployeeType, EmployeeType.tenant_id == tenant_id
        )
        formats = await SetupStatusService._count(
            db, ScheduleFormat, ScheduleFormat.tenant_id == tenant_id
        )
        users = await SetupStatusService._count(
            db, User, User.tenant_id == tenant_id, User.is_active == True  # noqa: E712
        )
        leave_types = await SetupStatusService._count(
            db, LeaveType, LeaveType.tenant_id == tenant_id, LeaveType.is_active == True  # noqa: E712
        )
        policies = await SetupStatusService._count(
            db, LeavePolicy, LeavePolicy.tenant_id == tenant_id, LeavePolicy.is_active == True  # noqa: E712
        )
        holidays = await SetupStatusService._count(
            db, DateRemark,
            DateRemark.tenant_id == tenant_id,
            DateRemark.is_holiday == True,  # noqa: E712
            DateRemark.date >= date(year, 1, 1),
            DateRemark.date <= date(year, 12, 31),
        )
        grades = await SetupStatusService._count(
            db, SalaryGrade, SalaryGrade.tenant_id == tenant_id
        )
        deductions = await SetupStatusService._count(
            db, DeductionType, DeductionType.tenant_id == tenant_id
        )
        email_cfg = (await db.execute(
            select(EmailSettings).where(EmailSettings.tenant_id == tenant_id)
        )).scalar_one_or_none()
        email_ok = bool(email_cfg and getattr(email_cfg, "is_configured", False))

        steps = [
            Step("org_structure", "Build your org structure", org > 0, org, "/organization"),
            Step("employee_types", "Review employee types", emp_types > 0, emp_types, "/settings?tab=types"),
            Step("schedule_formats", "Set up schedule formats", formats > 0, formats, "/settings?tab=types"),
            Step("employees_invited", "Add employees", users > 1, users, "/employees"),
            Step("leave_types", "Define leave types", leave_types > 0, leave_types, "/policies?tab=leave"),
            Step("leave_policy", "Create a leave policy", policies > 0, policies, "/policies?tab=leave"),
            Step("holidays", "Add this year's holidays", holidays > 0, holidays, "/policies?tab=holidays"),
            Step("salary_grades", "Set up salary grades", grades > 0, grades, "/finances"),
            Step("deduction_types", "Configure deductions", deductions > 0, deductions, "/finances"),
            Step("email", "Connect email (for notifications)", email_ok, 1 if email_ok else 0, "/settings?tab=email"),
        ]
        payload = [s.__dict__ for s in steps]
        _CACHE[tenant_id] = (time.monotonic(), payload)
        return payload

    @staticmethod
    def invalidate(tenant_id: UUID) -> None:
        _CACHE.pop(tenant_id, None)
