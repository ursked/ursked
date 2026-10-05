import asyncio
import logging
from datetime import date, timedelta
from typing import Dict, Iterable, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import AsyncSessionLocal
from app.models.payroll import (
    SalaryGrade,
    EmployeeSalary,
    DeductionType,
    DeductionBracket,
    PayrollPeriod,
    PayrollItem,
)
from app.models.user import User
from app.models.schedule import Shift
from app.models.settings import AppSettings
from app.models.leave import OvertimeCategory
from app.models.attendance import AttendanceRecord, OvertimeLog, TardinessRecord, LeaveCreditAdjustment
from app.models.compensation import CompensationItem
from app.services.payroll_compute import (
    deduction_amount,
    derive_rates,
    minutes_on_dates,
    night_minutes_in,
    period_fraction,
    span,
    validate_brackets,
)
from app.utils.timeutil import company_today, utcnow

# A period in one of these states has been signed off: its shifts, attendance
# and overtime are what was paid (or is about to be), so nothing may change
# them underneath it.
LOCKED_PERIOD_STATUSES = ("approved", "finalized")

logger = logging.getLogger(__name__)


class MakerCheckerError(PermissionError):
    """The person who computed a run tried to approve or finalize it.

    Approve and finalize used to be tenant_admin only. The owner's rule is
    maker-checker instead: anyone with finances:edit and salary access may sign
    a run off, but never the person who prepared it, whatever their role, so no
    one can both produce the figures and lock them. Raised here rather than in
    the router so every caller is held to it. Shown to the user (HTTP 403)."""


class PayrollService:
    # ── Salary Grades ─────────────────────────────────────────────

    @staticmethod
    async def list_salary_grades(
        db: AsyncSession, tenant_id: UUID, active_only: bool = True
    ) -> List[SalaryGrade]:
        stmt = select(SalaryGrade).where(SalaryGrade.tenant_id == tenant_id)
        if active_only:
            stmt = stmt.where(SalaryGrade.is_active == True)
        stmt = stmt.order_by(SalaryGrade.sort_order, SalaryGrade.name)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def create_salary_grade(
        db: AsyncSession, tenant_id: UUID, data: dict
    ) -> SalaryGrade:
        existing = await db.execute(
            select(SalaryGrade).where(
                SalaryGrade.tenant_id == tenant_id,
                SalaryGrade.code == data["code"],
            )
        )
        if existing.scalar_one_or_none():
            raise ValueError(f"Salary grade code '{data['code']}' already exists")

        grade = SalaryGrade(tenant_id=tenant_id, **data)
        db.add(grade)
        await db.commit()
        await db.refresh(grade)
        return grade

    @staticmethod
    async def update_salary_grade(
        db: AsyncSession, tenant_id: UUID, grade_id: int, data: dict
    ) -> SalaryGrade:
        grade = await db.get(SalaryGrade, grade_id)
        if not grade or grade.tenant_id != tenant_id:
            raise ValueError("Salary grade not found")
        for key, value in data.items():
            setattr(grade, key, value)
        await db.commit()
        await db.refresh(grade)
        return grade

    @staticmethod
    async def delete_salary_grade(
        db: AsyncSession, tenant_id: UUID, grade_id: int
    ) -> None:
        grade = await db.get(SalaryGrade, grade_id)
        if not grade or grade.tenant_id != tenant_id:
            raise ValueError("Salary grade not found")
        # Check if any employee salaries reference this grade
        usage = await db.execute(
            select(EmployeeSalary.id)
            .where(EmployeeSalary.salary_grade_id == grade_id)
            .limit(1)
        )
        if usage.scalar_one_or_none():
            grade.is_active = False
            await db.commit()
            return
        await db.delete(grade)
        await db.commit()

    # ── Employee Salary ───────────────────────────────────────────

    @staticmethod
    async def assign_employee_salary(
        db: AsyncSession, tenant_id: UUID, data: dict, actor: Optional[User] = None,
    ) -> EmployeeSalary:
        """Assign a salary grade from an effective date.

        (employee, effective_date) is unique, so assigning twice on the same
        date used to be an IntegrityError and a 500. It is a correction of that
        day's assignment instead, done in place like give_raise, and the audit
        log records what it was and what it became.
        """
        from app.services import audit_service

        employee = await db.get(User, data["employee_id"])
        if not employee or employee.tenant_id != tenant_id:
            raise ValueError("Employee not found")
        grade = await db.get(SalaryGrade, data["salary_grade_id"])
        if not grade or grade.tenant_id != tenant_id:
            raise ValueError("Salary grade not found")

        es = (await db.execute(
            select(EmployeeSalary).where(
                EmployeeSalary.tenant_id == tenant_id,
                EmployeeSalary.employee_id == data["employee_id"],
                EmployeeSalary.effective_date == data["effective_date"],
            )
        )).scalar_one_or_none()
        fields = ("salary_grade_id", "monthly_rate_override", "notes")
        before = None
        if es is not None:
            before = {f: getattr(es, f) for f in fields}
            es.salary_grade_id = data["salary_grade_id"]
            es.monthly_rate_override = data.get("monthly_rate_override")
            if data.get("notes") is not None:
                es.notes = data.get("notes")
        else:
            es = EmployeeSalary(tenant_id=tenant_id, **data)
            db.add(es)
        await db.flush()
        audit_service.record(
            db, actor=actor, tenant_id=tenant_id,
            action="salary_assignment_updated" if before else "salary_assigned",
            resource_type="employee_salary", resource_id=es.id,
            details={
                "employee_id": es.employee_id,
                "effective_date": es.effective_date,
                "before": before,
                "after": {f: getattr(es, f) for f in fields},
            },
        )
        await db.commit()
        await db.refresh(es)
        return es

    @staticmethod
    async def employee_rates(
        db: AsyncSession, tenant_id: UUID, employee_id: int, as_of: date,
        settings: Optional[AppSettings] = None,
    ) -> Optional[dict]:
        """The employee's pay rates on `as_of`: monthly, daily and hourly.

        The one derivation of daily/hourly pay, shared by payroll and by the
        tardiness deduction (minutes late x hourly / 60), so a deduction can
        never be worked out on a different rate from the payslip it lands on.
        None when no salary is assigned on that date.
        """
        salary = await PayrollService.get_employee_current_salary(
            db, tenant_id, employee_id, as_of=as_of
        )
        if not salary:
            return None
        if settings is None:
            settings = (await db.execute(
                select(AppSettings).where(AppSettings.tenant_id == tenant_id)
            )).scalar_one_or_none()
        grade = await db.get(SalaryGrade, salary.salary_grade_id)
        monthly_rate = salary.monthly_rate_override or (grade.monthly_rate if grade else 0.0)
        wdpm = getattr(settings, "working_days_per_month", 22) or 22
        shift_hours = getattr(settings, "default_shift_duration_hours", 8) or 8
        # Effective grade for rate derivation honors a monthly override.
        eff_grade = grade
        if grade is None or salary.monthly_rate_override:
            eff_grade = type("G", (), {
                "monthly_rate": monthly_rate,
                "daily_rate": grade.daily_rate if grade else None,
                "hourly_rate": grade.hourly_rate if grade else None,
            })()
        daily_rate, hourly_rate = derive_rates(eff_grade, wdpm, shift_hours)
        return {
            "salary": salary, "grade": grade, "monthly": monthly_rate,
            "daily": daily_rate, "hourly": hourly_rate,
        }

    @staticmethod
    async def get_employee_current_salary(
        db: AsyncSession, tenant_id: UUID, employee_id: int, as_of: Optional[date] = None
    ) -> Optional[EmployeeSalary]:
        ref_date = as_of or await company_today(db, tenant_id)
        stmt = (
            select(EmployeeSalary)
            .where(
                EmployeeSalary.tenant_id == tenant_id,
                EmployeeSalary.employee_id == employee_id,
                EmployeeSalary.effective_date <= ref_date,
            )
            .order_by(EmployeeSalary.effective_date.desc())
            .limit(1)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_employee_salary_history(
        db: AsyncSession, tenant_id: UUID, employee_id: int
    ) -> List[EmployeeSalary]:
        stmt = (
            select(EmployeeSalary)
            .where(
                EmployeeSalary.tenant_id == tenant_id,
                EmployeeSalary.employee_id == employee_id,
            )
            .order_by(EmployeeSalary.effective_date.desc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def list_current_salaries(
        db: AsyncSession, tenant_id: UUID, as_of: Optional[date] = None
    ) -> List[dict]:
        """Every active employee with their current effective salary (or None).

        Drives the central Employee Salaries table so an admin can see who has a
        grade assigned and who doesn't, and assign/raise from one place."""
        ref_date = as_of or await company_today(db, tenant_id)
        users = (await db.execute(
            select(User).where(User.tenant_id == tenant_id, User.is_active == True)  # noqa: E712
            .order_by(User.first_name, User.last_name)
        )).scalars().all()

        grades = {g.id: g for g in (await db.execute(
            select(SalaryGrade).where(SalaryGrade.tenant_id == tenant_id)
        )).scalars().all()}

        out: List[dict] = []
        for u in users:
            sal = await PayrollService.get_employee_current_salary(db, tenant_id, u.id, as_of=ref_date)
            grade = grades.get(sal.salary_grade_id) if sal else None
            monthly = None
            if sal:
                monthly = sal.monthly_rate_override or (grade.monthly_rate if grade else None)
            out.append({
                "employee_id": u.id,
                "employee_name": f"{u.first_name} {u.last_name}",
                "email": u.email,
                "employee_type": u.employee_type,
                "salary_grade_id": sal.salary_grade_id if sal else None,
                "salary_grade_code": grade.code if grade else None,
                "salary_grade_name": grade.name if grade else None,
                "monthly_rate": monthly,
                "effective_date": sal.effective_date if sal else None,
            })
        return out

    @staticmethod
    async def give_raise(
        db: AsyncSession, tenant_id: UUID, *,
        employee_ids: List[int], mode: str, value: float,
        effective_date: date, new_grade_id: Optional[int] = None,
        reason: Optional[str] = None, created_by: Optional[int] = None,
    ) -> List[dict]:
        """Apply a salary increase to one or more employees.

        mode:
          - 'percent': new basic = current_basic * (1 + value/100)  (value in %)
          - 'fixed'  : new basic = current_basic + value            (value in currency)
          - 'grade'  : move to new_grade_id (override cleared; value ignored)

        Writes a new effective-dated EmployeeSalary per employee (idempotent per
        (employee, effective_date) — updates the row if one already exists on that
        date) and posts a CompensationItem(kind='salary_adjustment') audit line for
        the delta so the change is reconstructible from the ledger. Payroll reads
        salary as-of period.end_date, so the raise applies automatically to any
        run whose end date is on/after effective_date.

        Returns a per-employee result list (skipped employees are flagged).
        """
        if mode not in ("percent", "fixed", "grade"):
            raise ValueError(f"invalid raise mode: {mode}")
        if mode == "grade" and not new_grade_id:
            raise ValueError("grade raise requires new_grade_id")

        grades = {g.id: g for g in (await db.execute(
            select(SalaryGrade).where(SalaryGrade.tenant_id == tenant_id)
        )).scalars().all()}

        results: List[dict] = []
        for emp_id in employee_ids:
            current = await PayrollService.get_employee_current_salary(
                db, tenant_id, emp_id, as_of=effective_date
            )
            # Resolve the current basic monthly rate as-of the effective date.
            current_basic = None
            if current:
                cg = grades.get(current.salary_grade_id)
                current_basic = current.monthly_rate_override or (cg.monthly_rate if cg else None)

            if mode == "grade":
                target_grade_id = new_grade_id
                override = None
                tg = grades.get(new_grade_id)
                new_basic = tg.monthly_rate if tg else None
            else:
                if current is None or current_basic is None:
                    # Cannot compute a relative raise without a base salary.
                    results.append({
                        "employee_id": emp_id, "status": "skipped",
                        "reason": "no current salary to raise from",
                    })
                    continue
                target_grade_id = current.salary_grade_id
                if mode == "percent":
                    new_basic = round(current_basic * (1 + value / 100.0), 2)
                else:  # fixed
                    new_basic = round(current_basic + value, 2)
                override = new_basic

            # Idempotent upsert on (employee, effective_date).
            existing = (await db.execute(
                select(EmployeeSalary).where(
                    EmployeeSalary.tenant_id == tenant_id,
                    EmployeeSalary.employee_id == emp_id,
                    EmployeeSalary.effective_date == effective_date,
                )
            )).scalar_one_or_none()
            if existing:
                existing.salary_grade_id = target_grade_id
                existing.monthly_rate_override = override
                existing.notes = reason or existing.notes
            else:
                db.add(EmployeeSalary(
                    tenant_id=tenant_id,
                    employee_id=emp_id,
                    salary_grade_id=target_grade_id,
                    effective_date=effective_date,
                    monthly_rate_override=override,
                    notes=reason,
                ))

            # Ledger audit line for the delta (0 when we can't compute a prior basic).
            delta = None
            if current_basic is not None and new_basic is not None:
                delta = round(new_basic - current_basic, 2)
            db.add(CompensationItem(
                tenant_id=tenant_id,
                employee_id=emp_id,
                kind="salary_adjustment",
                amount=delta or 0.0,
                earned_on=effective_date,
                payout_date=effective_date,
                recurrence="once",
                status="scheduled",
                reason=reason or f"Salary raise ({mode})",
                meta={
                    "mode": mode, "value": value,
                    "from_basic": current_basic, "to_basic": new_basic,
                    "grade_id": target_grade_id,
                },
                created_by=created_by,
            ))
            results.append({
                "employee_id": emp_id, "status": "applied",
                "from_basic": current_basic, "to_basic": new_basic,
                "delta": delta, "effective_date": str(effective_date),
            })

        await db.commit()
        return results

    # ── Deduction Types ───────────────────────────────────────────

    @staticmethod
    async def list_deduction_types(
        db: AsyncSession, tenant_id: UUID, active_only: bool = True
    ) -> List[DeductionType]:
        stmt = select(DeductionType).where(DeductionType.tenant_id == tenant_id)
        if active_only:
            stmt = stmt.where(DeductionType.is_active == True)
        stmt = stmt.order_by(DeductionType.sort_order, DeductionType.name)
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def create_deduction_type(
        db: AsyncSession, tenant_id: UUID, data: dict
    ) -> DeductionType:
        existing = await db.execute(
            select(DeductionType).where(
                DeductionType.tenant_id == tenant_id,
                DeductionType.code == data["code"],
            )
        )
        if existing.scalar_one_or_none():
            raise ValueError(f"Deduction type code '{data['code']}' already exists")

        dt = DeductionType(tenant_id=tenant_id, **data)
        db.add(dt)
        await db.commit()
        await db.refresh(dt)
        return dt

    @staticmethod
    async def update_deduction_type(
        db: AsyncSession, tenant_id: UUID, dt_id: int, data: dict
    ) -> DeductionType:
        dt = await db.get(DeductionType, dt_id)
        if not dt or dt.tenant_id != tenant_id:
            raise ValueError("Deduction type not found")
        for key, value in data.items():
            setattr(dt, key, value)
        await db.commit()
        await db.refresh(dt)
        return dt

    @staticmethod
    async def delete_deduction_type(
        db: AsyncSession, tenant_id: UUID, dt_id: int
    ) -> None:
        dt = await db.get(DeductionType, dt_id)
        if not dt or dt.tenant_id != tenant_id:
            raise ValueError("Deduction type not found")
        await db.delete(dt)
        await db.commit()

    # ── Deduction Brackets (tiered tables) ─────────────────────────

    @staticmethod
    async def list_deduction_brackets(
        db: AsyncSession, tenant_id: UUID, dt_id: int
    ) -> List[DeductionBracket]:
        dt = await db.get(DeductionType, dt_id)
        if not dt or dt.tenant_id != tenant_id:
            raise ValueError("Deduction type not found")
        stmt = (
            select(DeductionBracket)
            .where(DeductionBracket.deduction_type_id == dt_id)
            .order_by(DeductionBracket.over_amount)
        )
        return list((await db.execute(stmt)).scalars().all())

    @staticmethod
    async def replace_deduction_brackets(
        db: AsyncSession, tenant_id: UUID, dt_id: int, brackets: list[dict]
    ) -> List[DeductionBracket]:
        """Replace all brackets for a deduction type in one shot. Validates
        that bands are ordered and non-overlapping."""
        dt = await db.get(DeductionType, dt_id)
        if not dt or dt.tenant_id != tenant_id:
            raise ValueError("Deduction type not found")

        # Ascending, no gaps, no overlaps, only the last open-ended: a basis in
        # a gap matched no band and deducted nothing.
        ordered = validate_brackets(brackets)

        for existing in (await db.execute(
            select(DeductionBracket).where(DeductionBracket.deduction_type_id == dt_id)
        )).scalars().all():
            await db.delete(existing)
        await db.flush()

        for b in ordered:
            db.add(DeductionBracket(
                tenant_id=tenant_id,
                deduction_type_id=dt_id,
                over_amount=b.get("over_amount", 0) or 0,
                up_to_amount=b.get("up_to_amount"),
                base_amount=b.get("base_amount", 0) or 0,
                rate=b.get("rate", 0) or 0,
                rate_basis=b.get("rate_basis", "excess"),
            ))
        await db.commit()
        return await PayrollService.list_deduction_brackets(db, tenant_id, dt_id)

    # ── Payroll Periods ───────────────────────────────────────────

    @staticmethod
    async def list_payroll_periods(
        db: AsyncSession, tenant_id: UUID
    ) -> List[PayrollPeriod]:
        stmt = (
            select(PayrollPeriod)
            .where(PayrollPeriod.tenant_id == tenant_id)
            .order_by(PayrollPeriod.start_date.desc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def create_payroll_period(
        db: AsyncSession, tenant_id: UUID, data: dict
    ) -> PayrollPeriod:
        from app.models.compensation import PayoutSchedule

        dup = (await db.execute(
            select(PayrollPeriod.name).where(
                PayrollPeriod.tenant_id == tenant_id,
                PayrollPeriod.start_date == data["start_date"],
                PayrollPeriod.end_date == data["end_date"],
            )
        )).scalar_one_or_none()
        if dup:
            raise ValueError(f'"{dup}" already covers exactly these dates.')
        if data.get("schedule_id") is not None:
            sched = await db.get(PayoutSchedule, data["schedule_id"])
            if not sched or sched.tenant_id != tenant_id:
                raise ValueError("That payout schedule does not exist.")
        period = PayrollPeriod(tenant_id=tenant_id, **data)
        db.add(period)
        await db.commit()
        await db.refresh(period)
        return period

    @staticmethod
    async def get_payroll_period(
        db: AsyncSession, tenant_id: UUID, period_id: int
    ) -> Optional[PayrollPeriod]:
        period = await db.get(PayrollPeriod, period_id)
        if not period or period.tenant_id != tenant_id:
            return None
        return period

    # ── Payroll Computation ───────────────────────────────────────

    @staticmethod
    async def _load_compute_context(db: AsyncSession, tenant_id: UUID) -> dict:
        """Load the tenant-wide config used by every employee's computation."""
        settings = (await db.execute(
            select(AppSettings).where(AppSettings.tenant_id == tenant_id)
        )).scalar_one_or_none()

        deductions = list((await db.execute(
            select(DeductionType)
            .options(selectinload(DeductionType.brackets))
            .where(
                DeductionType.tenant_id == tenant_id,
                DeductionType.is_mandatory == True,  # noqa: E712
                DeductionType.is_active == True,  # noqa: E712
            )
        )).scalars().all())

        ot_categories = {
            oc.code: oc for oc in (await db.execute(
                select(OvertimeCategory).where(
                    OvertimeCategory.tenant_id == tenant_id,
                    OvertimeCategory.is_active == True,  # noqa: E712
                )
            )).scalars().all()
        }
        return {"settings": settings, "deductions": deductions, "ot_categories": ot_categories}

    @staticmethod
    async def _holiday_map(db: AsyncSession, tenant_id: UUID, start: date, end: date) -> dict:
        """{date: HolidayDay} for holidays touching the period.

        Through holiday_calendar, so recurring holidays count every year (the
        literal-date query this replaced stopped paying them after year one).
        One day either side, because a night shift that starts on the period's
        last day ends in the next.
        """
        from app.services.holiday_calendar import holidays_between

        return await holidays_between(
            db, tenant_id, start - timedelta(days=1), end + timedelta(days=1)
        )

    @staticmethod
    def _holiday_multiplier(settings, holiday) -> float:
        if holiday is not None and holiday.is_special:
            return getattr(settings, "special_holiday_worked_multiplier", 1.3) or 1.3
        return getattr(settings, "holiday_worked_multiplier", 2.0) or 2.0

    @staticmethod
    async def _premiums(
        db: AsyncSession, tenant_id: UUID, period: PayrollPeriod, employee: User,
        settings, holidays: dict, hourly_rate: float,
    ) -> Tuple[float, List[dict], List[int]]:
        """Holiday and night-differential premiums for what was WORKED.

        Until 2026-09 these were paid from the schedule: drafts, days nobody
        worked and unpaid breaks all earned premium, while every overnight
        shift (end before start on one date) earned nothing. Now the hours
        are the attendance record's worked intervals (paired punches, or the
        entered times with an overnight end on the next day), net of the
        unpaid break, and a draft or an unworked shift earns nothing.

        One source of truth per day and kind. When the policy engine created
        a holiday_shift or night_differential log for the day, that log
        decides: approved is paid (its minutes, at its category multiplier if
        it has one), pending is held until someone approves it, rejected or
        converted-to-leave is not paid in cash. Only when there is no such log
        does payroll work the premium out itself with the company's
        multipliers. Either way the log itself is never also paid as
        overtime, so the same hours cannot be paid twice.

        A premium is the extra over base pay, hours x rate x (multiplier - 1):
        a monthly salary already pays those hours once. Logs used to be paid
        at the full multiplier on top of base, paying the base hours twice.

        Returns (amount, breakdown lines, ids of the logs this run pays).
        """
        from app.services.attendance_service import AttendanceService

        records = list((await db.execute(
            select(AttendanceRecord).where(
                AttendanceRecord.tenant_id == tenant_id,
                AttendanceRecord.employee_id == employee.id,
                AttendanceRecord.date >= period.start_date,
                AttendanceRecord.date <= period.end_date,
            ).order_by(AttendanceRecord.date)
        )).scalars().all())
        if not records:
            return 0.0, [], []

        logs: Dict[Tuple[int, str], OvertimeLog] = {}
        for log in (await db.execute(
            select(OvertimeLog).where(
                OvertimeLog.attendance_record_id.in_([r.id for r in records]),
                OvertimeLog.log_type.in_(["holiday_shift", "night_differential"]),
            )
        )).scalars().all():
            logs[(log.attendance_record_id, log.log_type)] = log

        night_start = getattr(settings, "night_shift_start", None)
        night_end = getattr(settings, "night_shift_end", None)
        night_mult = getattr(settings, "night_diff_multiplier", 1.10) or 1.10

        total = 0.0
        lines: List[dict] = []
        consumed: List[int] = []

        def pay(d, kind, minutes, mult, **extra):
            nonlocal total
            hours = minutes / 60.0
            amount = hours * hourly_rate * max(0.0, mult - 1)
            if amount <= 0:
                return
            total += amount
            lines.append({
                "date": str(d), "kind": kind, "hours": round(hours, 2),
                "multiplier": mult, "amount": round(amount, 2), **extra,
            })

        def gated(rec, log, kind, fallback_mult):
            """Apply a policy-engine log's decision. True if the log decided."""
            if log is None:
                return False
            if log.status == "approved" and not log.paid_at:
                pay(rec.date, kind, log.overtime_minutes or 0,
                    log.pay_multiplier or fallback_mult, log_id=log.id, source="overtime_log")
                consumed.append(log.id)
            elif log.status == "pending":
                lines.append({
                    "date": str(rec.date), "kind": kind,
                    "hours": round((log.overtime_minutes or 0) / 60.0, 2),
                    "amount": 0.0, "log_id": log.id, "held": True,
                    "note": "Waiting for approval under Attendance, Overtime.",
                })
            return True

        for rec in records:
            facts = await AttendanceService._facts(db, rec, employee, settings)
            if not facts.intervals:
                continue
            ratio = (facts.paid_worked_minutes / facts.worked_minutes) if facts.worked_minutes else 1.0

            on_holidays = minutes_on_dates(facts.intervals, holidays.keys())
            first_holiday = holidays.get(min(on_holidays)) if on_holidays else None
            if not gated(rec, logs.get((rec.id, "holiday_shift")),
                         f"holiday_{'special' if first_holiday and first_holiday.is_special else 'regular'}",
                         PayrollService._holiday_multiplier(settings, first_holiday)):
                for d, mins in sorted(on_holidays.items()):
                    h = holidays[d]
                    pay(d, f"holiday_{'special' if h.is_special else 'regular'}",
                        int(round(mins * ratio)), PayrollService._holiday_multiplier(settings, h),
                        holiday=h.title)

            if not gated(rec, logs.get((rec.id, "night_differential")), "night_diff", night_mult):
                nd = night_minutes_in(facts.intervals, night_start, night_end)
                if nd > 0:
                    pay(rec.date, "night_diff", int(round(nd * ratio)), night_mult)

        return total, lines, consumed

    @staticmethod
    async def _compute_one(
        db: AsyncSession, tenant_id: UUID, period: PayrollPeriod, employee: User,
        ctx: dict, holidays: dict,
    ) -> Optional[PayrollItem]:
        settings = ctx["settings"]
        rates = await PayrollService.employee_rates(
            db, tenant_id, employee.id, period.end_date, settings
        )
        if rates is None:
            return None
        salary = rates["salary"]
        monthly_rate = rates["monthly"]
        daily_rate, hourly_rate = rates["daily"], rates["hourly"]
        warnings: list[str] = []

        # Base pay prorated by period type (fixes semi-monthly double-pay).
        base_pay = monthly_rate * period_fraction(period.period_type)

        overtime_pay = 0.0
        overtime_details: list[dict] = []

        # ── OT: OvertimeLog is authoritative. Track dates to dedupe shift OT. ──
        # Only ordinary overtime here. Holiday and night-differential logs are
        # premiums on hours base pay already covers; _premiums pays them.
        ot_log_dates: set[date] = set()
        ot_logs = (await db.execute(
            select(OvertimeLog)
            .options(selectinload(OvertimeLog.overtime_category))
            .where(
                OvertimeLog.tenant_id == tenant_id,
                OvertimeLog.employee_id == employee.id,
                OvertimeLog.date >= period.start_date,
                OvertimeLog.date <= period.end_date,
                OvertimeLog.status == "approved",
                OvertimeLog.paid_at.is_(None),
                OvertimeLog.log_type.notin_(["holiday_shift", "night_differential"]),
            )
        )).scalars().all()
        for log in ot_logs:
            ot_log_dates.add(log.date)
            hours = (log.overtime_minutes or 0) / 60.0
            # Resolve multiplier: explicit on the log, else the category
            # multiplier, else 1.0.
            multiplier = log.pay_multiplier
            if multiplier is None:
                if log.overtime_category and log.overtime_category.multiplier_rate:
                    multiplier = log.overtime_category.multiplier_rate
                else:
                    multiplier = 1.0
            amount = hours * hourly_rate * multiplier
            overtime_pay += amount
            overtime_details.append({
                "date": str(log.date),
                "hours": round(hours, 2),
                "multiplier": multiplier,
                "log_type": log.log_type,
                "amount": round(amount, 2),
                "source": "overtime_log",
                "log_id": log.id,
            })

        # ── Legacy shift-status OT (deprecated), skipping dates already logged.
        #    Published shifts only, and only on days the employee actually
        #    worked: a planned overtime shift nobody turned up for is not pay. ──
        worked_dates = {
            d for (d,) in (await db.execute(
                select(AttendanceRecord.date).where(
                    AttendanceRecord.tenant_id == tenant_id,
                    AttendanceRecord.employee_id == employee.id,
                    AttendanceRecord.date >= period.start_date,
                    AttendanceRecord.date <= period.end_date,
                    AttendanceRecord.actual_start_time.isnot(None),
                )
            )).all()
        }
        shift_ot = (await db.execute(
            select(Shift).where(
                Shift.tenant_id == tenant_id,
                Shift.employee_id == employee.id,
                Shift.date >= period.start_date,
                Shift.date <= period.end_date,
                Shift.status.in_(["overtime", "ot"]),
                Shift.is_published == True,  # noqa: E712
            )
        )).scalars().all()
        for shift in shift_ot:
            if shift.date in ot_log_dates or shift.date not in worked_dates:
                continue  # OvertimeLog wins; unworked plans are not paid
            if not (shift.start_time and shift.end_time):
                continue
            start_dt, end_dt = span(shift.date, shift.start_time, shift.end_time)
            hours = (end_dt - start_dt).total_seconds() / 3600
            multiplier = 1.25
            if shift.remarks and shift.remarks in ctx["ot_categories"]:
                multiplier = ctx["ot_categories"][shift.remarks].multiplier_rate
                logger.warning(
                    "Payroll: resolving OT category from Shift.remarks is "
                    "deprecated (employee=%s date=%s)", employee.id, shift.date
                )
            amount = hours * hourly_rate * multiplier
            overtime_pay += amount
            overtime_details.append({
                "date": str(shift.date),
                "hours": round(hours, 2),
                "multiplier": multiplier,
                "amount": round(amount, 2),
                "source": "shift_status",
            })

        # ── Holiday / night premiums on what was worked ──
        premium_pay, premium_details, premium_log_ids = await PayrollService._premiums(
            db, tenant_id, period, employee, settings, holidays, hourly_rate
        )
        if any(p.get("held") for p in premium_details):
            warnings.append(
                "Some holiday or night-differential pay is waiting for approval under "
                "Attendance, Overtime, and was not paid in this run."
            )

        # ── Leave cash-conversion line items falling in this period ──
        conversion_pay = 0.0
        conversion_details: list[dict] = []
        conversions = (await db.execute(
            select(LeaveCreditAdjustment).where(
                LeaveCreditAdjustment.tenant_id == tenant_id,
                LeaveCreditAdjustment.employee_id == employee.id,
                LeaveCreditAdjustment.adjustment_type == "cash_conversion",
                LeaveCreditAdjustment.effective_date >= period.start_date,
                LeaveCreditAdjustment.effective_date <= period.end_date,
            )
        )).scalars().all()
        for conv in conversions:
            meta = conv.meta or {}
            days = meta.get("days", abs(conv.credits))
            rate = meta.get("rate", 1.0)
            amount = days * daily_rate * rate
            conversion_pay += amount
            conversion_details.append({
                "leave_type": conv.leave_type,
                "days": round(days, 2),
                "rate": rate,
                "amount": round(amount, 2),
            })

        # ── Tardiness salary deductions ──
        # A record resolved before the amount was worked out (it deducted 0)
        # gets the employee's per-minute rate x minutes late now.
        tardiness_deduction = 0.0
        tardiness_details: list[dict] = []
        for tard in (await db.execute(
            select(TardinessRecord).where(
                TardinessRecord.tenant_id == tenant_id,
                TardinessRecord.employee_id == employee.id,
                TardinessRecord.date >= period.start_date,
                TardinessRecord.date <= period.end_date,
                TardinessRecord.resolution_type == "salary_deduction",
            )
        )).scalars().all():
            amount = tard.deduction_amount
            if amount is None:
                amount = round(hourly_rate / 60.0 * (tard.tardiness_minutes or 0), 2)
            if amount > 0:
                tardiness_deduction += amount
                tardiness_details.append({
                    "date": str(tard.date),
                    "minutes_late": tard.tardiness_minutes,
                    "amount": round(amount, 2),
                })

        # ── Variable compensation due in this run (bonus/incentive/allowance/
        #    leave_cash/correction). When the run has a payout_date, pay
        #    everything scheduled for that date (this is how a Jan-1 holiday
        #    earned amount can be paid in a later run). Otherwise fall back to
        #    earned_on within the range so legacy runs still work. ──
        earnings_pay = 0.0
        earnings_details: list[dict] = []
        comp_stmt = select(CompensationItem).where(
            CompensationItem.tenant_id == tenant_id,
            CompensationItem.employee_id == employee.id,
            CompensationItem.status == "scheduled",
            # salary_adjustment rows are an AUDIT trail of a raise; the raise is
            # already reflected in base pay via the new EmployeeSalary, so paying
            # them here would double-count the increase.
            CompensationItem.kind != "salary_adjustment",
        )
        if period.payout_date is not None:
            comp_stmt = comp_stmt.where(CompensationItem.payout_date == period.payout_date)
        else:
            comp_stmt = comp_stmt.where(
                CompensationItem.earned_on >= period.start_date,
                CompensationItem.earned_on <= period.end_date,
            )
        comp_items = (await db.execute(comp_stmt)).scalars().all()
        for ci in comp_items:
            earnings_pay += ci.amount
            earnings_details.append({
                "id": ci.id,
                "kind": ci.kind,
                "amount": round(ci.amount, 2),
                "earned_on": str(ci.earned_on),
                "payout_date": str(ci.payout_date),
                "reason": ci.reason,
            })

        gross_pay = base_pay + overtime_pay + premium_pay + conversion_pay + earnings_pay

        # ── Statutory / mandatory deductions (fixed/percentage/tiered) ──
        # Employee deductions and employer contributions are kept in separate
        # lists: the payslip listed both under "deductions", so its lines did
        # not add up to Total deductions and employees read the employer's
        # share as money taken from them.
        deduction_details: list[dict] = []
        employee_deductions: list[dict] = [
            {"name": f"Late {t['date']} ({t['minutes_late']} min)", "amount": t["amount"], "kind": "tardiness"}
            for t in tardiness_details
        ]
        employer_contributions: list[dict] = []
        total_deductions = tardiness_deduction
        total_contributions = 0.0
        for ded in ctx["deductions"]:
            amount, entry = deduction_amount(ded, gross_pay, base_pay, list(ded.brackets))
            deduction_details.append(entry)
            if entry.get("warning"):
                warnings.append(entry["warning"])
            line = {"code": ded.code, "name": ded.name, "amount": entry["amount"]}
            if ded.is_employer_contribution:
                total_contributions += amount
                employer_contributions.append(line)
            else:
                total_deductions += amount
                employee_deductions.append(line)

        net_pay = gross_pay - total_deductions

        return PayrollItem(
            tenant_id=tenant_id,
            payroll_period_id=period.id,
            employee_id=employee.id,
            salary_grade_id=salary.salary_grade_id,
            base_pay=round(base_pay, 2),
            overtime_pay=round(overtime_pay + premium_pay, 2),
            gross_pay=round(gross_pay, 2),
            total_deductions=round(total_deductions, 2),
            total_contributions=round(total_contributions, 2),
            net_pay=round(net_pay, 2),
            breakdown={
                "deductions": deduction_details,
                "employee_deductions": employee_deductions,
                "employer_contributions": employer_contributions,
                "overtime": overtime_details,
                "premiums": premium_details,
                "premium_log_ids": premium_log_ids,
                "leave_conversions": conversion_details,
                "earnings": earnings_details,
                "tardiness": tardiness_details,
                "warnings": warnings,
                "rates": {"daily": daily_rate, "hourly": hourly_rate,
                          "period_fraction": period_fraction(period.period_type)},
            },
        )

    @staticmethod
    async def _run_compute(
        db: AsyncSession, tenant_id: UUID, period: PayrollPeriod, *,
        progress: bool = False,
    ) -> dict:
        """Recompute all items for a period in `db`. Assumes status already set.

        Returns {"skipped": [...], "warnings": [...]}: employees left out
        because they have no salary as of the period end (so the caller can
        surface who was excluded instead of silently dropping them), and
        per-employee problems such as a tiered deduction with no brackets."""
        from app.services.compensation_service import CompensationService

        # Recurring allowances ("every month" / "every cutoff") are expanded
        # here, for this run, so they are paid every time without a separate
        # job or button. Idempotent: an occurrence already made for a template
        # and date is never made twice.
        await CompensationService.expand_for_period(db, tenant_id, period)

        ctx = await PayrollService._load_compute_context(db, tenant_id)
        holidays = await PayrollService._holiday_map(
            db, tenant_id, period.start_date, period.end_date
        )
        employees = list((await db.execute(
            select(User).where(
                User.tenant_id == tenant_id,
                User.is_active == True,  # noqa: E712
            )
        )).scalars().all())

        # Clear prior items.
        for item in (await db.execute(
            select(PayrollItem).where(PayrollItem.payroll_period_id == period.id)
        )).scalars().all():
            await db.delete(item)
        await db.flush()

        skipped: List[dict] = []
        warnings: List[dict] = []
        total = len(employees)
        for idx, employee in enumerate(employees, start=1):
            item = await PayrollService._compute_one(
                db, tenant_id, period, employee, ctx, holidays
            )
            name = f"{employee.first_name} {employee.last_name}"
            if item is not None:
                db.add(item)
                for msg in (item.breakdown or {}).get("warnings") or []:
                    warnings.append({"employee_id": employee.id, "employee_name": name, "message": msg})
            else:
                skipped.append({
                    "employee_id": employee.id,
                    "employee_name": name,
                    "reason": "no_salary_assigned",
                })
            if progress and (idx % 25 == 0 or idx == total):
                period.compute_progress = {"done": idx, "total": total}
                await db.flush()

        return {"skipped": skipped, "warnings": warnings}

    @staticmethod
    def _outcome_progress(outcome: dict) -> Optional[dict]:
        """What stays on the period after a compute: who was skipped and why,
        and any warnings, so the Payroll screen can list them."""
        kept = {k: v for k, v in outcome.items() if v}
        return kept or None

    @staticmethod
    async def compute_payroll(
        db: AsyncSession, tenant_id: UUID, period_id: int, computed_by: int
    ) -> PayrollPeriod:
        """Synchronous compute (kept for tests and small tenants)."""
        period = await db.get(PayrollPeriod, period_id)
        if not period or period.tenant_id != tenant_id:
            raise ValueError("Payroll period not found")
        if period.status not in ("draft", "computed", "compute_failed"):
            raise ValueError(f"Cannot compute payroll in '{period.status}' status")

        PayrollService._reset_signoff(period, computed_by)
        outcome = await PayrollService._run_compute(db, tenant_id, period)
        period.status = "computed"
        period.compute_progress = PayrollService._outcome_progress(outcome)
        period.computed_at = utcnow()
        period.computed_by = computed_by
        await db.commit()
        await db.refresh(period)
        return period

    @staticmethod
    async def start_compute(
        db: AsyncSession, tenant_id: UUID, period_id: int, computed_by: int
    ) -> PayrollPeriod:
        """Kick off a backgrounded compute and return immediately. The period
        moves draft/computed → computing; a task recomputes with progress and
        lands on computed / compute_failed. Poll GET /payroll/periods/{id}."""
        period = await db.get(PayrollPeriod, period_id)
        if not period or period.tenant_id != tenant_id:
            raise ValueError("Payroll period not found")
        if period.status == "computing":
            raise ValueError("Payroll is already computing")
        if period.status not in ("draft", "computed", "compute_failed"):
            raise ValueError(f"Cannot compute payroll in '{period.status}' status")

        period.status = "computing"
        period.compute_progress = {"done": 0, "total": 0}
        PayrollService._reset_signoff(period, computed_by)
        await db.commit()

        asyncio.create_task(
            PayrollService._compute_task(tenant_id, period_id, computed_by)
        )
        await db.refresh(period)
        return period

    @staticmethod
    async def _compute_task(tenant_id: UUID, period_id: int, computed_by: int) -> None:
        """Background worker; owns its own session."""
        async with AsyncSessionLocal() as db:
            period = await db.get(PayrollPeriod, period_id)
            if not period:
                return
            try:
                outcome = await PayrollService._run_compute(
                    db, tenant_id, period, progress=True
                )
                period.status = "computed"
                period.compute_progress = PayrollService._outcome_progress(outcome)
                period.computed_at = utcnow()
                period.computed_by = computed_by
                await db.commit()
            except Exception as exc:  # noqa: BLE001
                logger.exception("Background payroll compute failed for period %s", period_id)
                await db.rollback()
                period = await db.get(PayrollPeriod, period_id)
                if period:
                    period.status = "compute_failed"
                    # Shown on the Payroll screen next to Retry.
                    period.compute_progress = {
                        "error": f"Compute failed: {exc}".strip()[:500],
                    }
                    await db.commit()

    @staticmethod
    def _reset_signoff(period: PayrollPeriod, computed_by: int) -> None:
        """A (re)compute makes the new figures the recomputer's work: they are
        the preparer from the moment it starts (so they cannot approve a run
        while it computes either), and no approval of earlier figures survives."""
        period.computed_by = computed_by
        period.approved_by = None
        period.approved_at = None

    @staticmethod
    def assert_not_preparer(period: PayrollPeriod, user_id: int, verb: str) -> None:
        """Maker-checker (see MakerCheckerError). A run with no recorded
        preparer (computed before 2026-09, or the preparer's account deleted)
        has nobody to exclude, so it is allowed."""
        if period.computed_by is not None and period.computed_by == user_id:
            raise MakerCheckerError(
                f"You computed this payroll run, so someone else must {verb} it."
            )

    @staticmethod
    async def approve_payroll(
        db: AsyncSession, tenant_id: UUID, period_id: int, approved_by: int
    ) -> PayrollPeriod:
        period = await db.get(PayrollPeriod, period_id)
        if not period or period.tenant_id != tenant_id:
            raise ValueError("Payroll period not found")
        if period.status != "computed":
            raise ValueError(f"Cannot approve payroll in '{period.status}' status")
        PayrollService.assert_not_preparer(period, approved_by, "approve")
        period.status = "approved"
        period.approved_at = utcnow()
        period.approved_by = approved_by
        await db.commit()
        await db.refresh(period)
        return period

    @staticmethod
    async def finalize_payroll(
        db: AsyncSession, tenant_id: UUID, period_id: int, finalized_by: int
    ) -> PayrollPeriod:
        period = await db.get(PayrollPeriod, period_id)
        if not period or period.tenant_id != tenant_id:
            raise ValueError("Payroll period not found")
        if period.status != "approved":
            raise ValueError(f"Cannot finalize payroll in '{period.status}' status")
        PayrollService.assert_not_preparer(period, finalized_by, "finalize")

        now = utcnow()
        # Mark what each item paid, so none of it can be paid again or
        # silently changed. The item's breakdown records exactly which
        # compensation lines and overtime logs were included.
        items = (await db.execute(
            select(PayrollItem).where(
                PayrollItem.tenant_id == tenant_id,
                PayrollItem.payroll_period_id == period.id,
            )
        )).scalars().all()
        for item in items:
            breakdown = item.breakdown or {}
            comp_ids = [
                e.get("id") for e in (breakdown.get("earnings") or [])
                if e.get("id") is not None
            ]
            if comp_ids:
                comps = (await db.execute(
                    select(CompensationItem).where(
                        CompensationItem.tenant_id == tenant_id,
                        CompensationItem.id.in_(comp_ids),
                        CompensationItem.status == "scheduled",
                    )
                )).scalars().all()
                for c in comps:
                    c.status = "paid"
                    c.payroll_item_id = item.id

            # Overtime this run paid. Until 2026-09 finalize left it looking
            # unpaid, and the next attendance edit purged it and re-created it
            # as pending, so approved overtime vanished from a closed payroll.
            log_ids = [
                e.get("log_id") for e in (breakdown.get("overtime") or [])
                if e.get("log_id") is not None
            ] + list(breakdown.get("premium_log_ids") or [])
            if log_ids:
                for log in (await db.execute(
                    select(OvertimeLog).where(
                        OvertimeLog.tenant_id == tenant_id,
                        OvertimeLog.id.in_(log_ids),
                    )
                )).scalars().all():
                    log.payroll_period_id = period.id
                    log.paid_at = now

        period.status = "finalized"
        period.finalized_at = now
        period.finalized_by = finalized_by
        from app.services import plugin_events

        await plugin_events.payroll_finalized(db, period, finalized_by)
        await db.commit()
        await db.refresh(period)
        return period

    # ── Locked periods ────────────────────────────────────────────

    @staticmethod
    async def locked_periods_for(
        db: AsyncSession, tenant_id: UUID, pairs: Iterable[Tuple[int, date]],
    ) -> Dict[Tuple[int, date], PayrollPeriod]:
        """For each (employee_id, date), the approved or finalized payroll
        period that already paid that employee for that date, if any.

        "Paid that employee" means the period has a payroll item for them: an
        employee skipped by a run (no salary yet) is not locked by it."""
        pairs = {(e, d) for e, d in pairs if e is not None and d is not None}
        if not pairs:
            return {}
        dates = [d for _, d in pairs]
        periods = list((await db.execute(
            select(PayrollPeriod).where(
                PayrollPeriod.tenant_id == tenant_id,
                PayrollPeriod.status.in_(LOCKED_PERIOD_STATUSES),
                PayrollPeriod.start_date <= max(dates),
                PayrollPeriod.end_date >= min(dates),
            ).order_by(PayrollPeriod.start_date)
        )).scalars().all())
        if not periods:
            return {}
        covered = {
            (pid, eid) for pid, eid in (await db.execute(
                select(PayrollItem.payroll_period_id, PayrollItem.employee_id).where(
                    PayrollItem.payroll_period_id.in_([p.id for p in periods]),
                    PayrollItem.employee_id.in_({e for e, _ in pairs}),
                )
            )).all()
        }
        out: Dict[Tuple[int, date], PayrollPeriod] = {}
        for e, d in pairs:
            for p in periods:
                if p.start_date <= d <= p.end_date and (p.id, e) in covered:
                    out[(e, d)] = p
                    break
        return out

    @staticmethod
    def locked_message(period: PayrollPeriod, employee_name: str, d: date, extra: int = 0) -> str:
        state = "finalized" if period.status == "finalized" else "approved and waiting to be finalized"
        more = f" (and {extra} other day{'s' if extra != 1 else ''})" if extra else ""
        return (
            f'The payroll period "{period.name}" is {state}, and it has already paid '
            f"{employee_name} for {d.strftime('%d %b %Y')}{more}. That day can no longer be "
            "changed; post a correction under Finances, Bonuses & Allowances instead."
        )

    # ── Payroll Items / Summary ───────────────────────────────────

    @staticmethod
    async def get_payroll_items(
        db: AsyncSession, tenant_id: UUID, period_id: int
    ) -> List[PayrollItem]:
        stmt = (
            select(PayrollItem)
            .where(
                PayrollItem.tenant_id == tenant_id,
                PayrollItem.payroll_period_id == period_id,
            )
            .order_by(PayrollItem.employee_id)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_payroll_summary(
        db: AsyncSession, tenant_id: UUID, period_id: int
    ) -> dict:
        period = await db.get(PayrollPeriod, period_id)
        if not period or period.tenant_id != tenant_id:
            raise ValueError("Payroll period not found")

        items = await PayrollService.get_payroll_items(db, tenant_id, period_id)

        # Enrich items with employee name and grade name
        enriched = []
        for item in items:
            employee = await db.get(User, item.employee_id)
            grade = await db.get(SalaryGrade, item.salary_grade_id) if item.salary_grade_id else None
            enriched.append({
                "item": item,
                "employee_name": f"{employee.first_name} {employee.last_name}" if employee else "Unknown",
                "grade_name": grade.name if grade else None,
            })

        return {
            "period": period,
            "items": enriched,
            "total_employees": len(items),
            "total_base_pay": round(sum(i.base_pay for i in items), 2),
            "total_overtime_pay": round(sum(i.overtime_pay for i in items), 2),
            "total_gross_pay": round(sum(i.gross_pay for i in items), 2),
            "total_deductions": round(sum(i.total_deductions for i in items), 2),
            "total_contributions": round(sum(i.total_contributions for i in items), 2),
            "total_net_pay": round(sum(i.net_pay for i in items), 2),
        }

    # ── Employee self-service payslips ────────────────────────────
    # Employees are NOT granted the admin payroll endpoints; these two methods
    # scope strictly to a single employee and only expose runs that have been
    # released (approved or finalized) so drafts/in-progress figures never leak.

    _PAYSLIP_VISIBLE_STATUSES = ("approved", "finalized")

    @staticmethod
    def split_deductions(breakdown: dict) -> Tuple[List[dict], List[dict]]:
        """(what was deducted from the employee, what the employer paid on
        top). The first list adds up to Total deductions; the second is not
        taken from anyone's pay. Runs computed before 2026-09 only have the
        mixed `deductions` list, so it is split by its is_employer flag."""
        if "employee_deductions" in breakdown or "employer_contributions" in breakdown:
            return (
                list(breakdown.get("employee_deductions") or []),
                list(breakdown.get("employer_contributions") or []),
            )
        emp: List[dict] = [
            {"name": f"Late {t.get('date')} ({t.get('minutes_late')} min)",
             "amount": t.get("amount", 0), "kind": "tardiness"}
            for t in (breakdown.get("tardiness") or [])
        ]
        er: List[dict] = []
        for d in breakdown.get("deductions") or []:
            line = {"code": d.get("code"), "name": d.get("name") or d.get("code"), "amount": d.get("amount", 0)}
            (er if d.get("is_employer") else emp).append(line)
        return emp, er

    @staticmethod
    async def list_my_payslips(
        db: AsyncSession, tenant_id: UUID, employee_id: int
    ) -> List[dict]:
        """Released payroll runs this employee has an item in (newest first)."""
        rows = (await db.execute(
            select(PayrollItem, PayrollPeriod)
            .join(PayrollPeriod, PayrollItem.payroll_period_id == PayrollPeriod.id)
            .where(
                PayrollItem.tenant_id == tenant_id,
                PayrollItem.employee_id == employee_id,
                PayrollPeriod.status.in_(PayrollService._PAYSLIP_VISIBLE_STATUSES),
            )
            .order_by(PayrollPeriod.end_date.desc())
        )).all()
        out: List[dict] = []
        for item, period in rows:
            out.append({
                "period_id": period.id,
                "period_name": period.name,
                "start_date": period.start_date,
                "end_date": period.end_date,
                "payout_date": period.payout_date,
                "status": period.status,
                "gross_pay": item.gross_pay,
                "total_deductions": item.total_deductions,
                "net_pay": item.net_pay,
            })
        return out

    @staticmethod
    async def get_my_payslip(
        db: AsyncSession, tenant_id: UUID, employee_id: int, period_id: int
    ) -> Optional[dict]:
        """One released payslip for this employee, with the full line breakdown.

        Returns None if the period isn't released or the employee has no item in
        it — the caller maps that to 404 so one employee can never probe another's
        pay by iterating period ids."""
        period = await db.get(PayrollPeriod, period_id)
        if (not period or period.tenant_id != tenant_id
                or period.status not in PayrollService._PAYSLIP_VISIBLE_STATUSES):
            return None
        item = (await db.execute(
            select(PayrollItem).where(
                PayrollItem.tenant_id == tenant_id,
                PayrollItem.payroll_period_id == period_id,
                PayrollItem.employee_id == employee_id,
            )
        )).scalar_one_or_none()
        if not item:
            return None

        employee = await db.get(User, employee_id)
        grade = await db.get(SalaryGrade, item.salary_grade_id) if item.salary_grade_id else None
        employee_deductions, employer_contributions = PayrollService.split_deductions(item.breakdown or {})
        return {
            "employee_deductions": employee_deductions,
            "employer_contributions": employer_contributions,
            "period_id": period.id,
            "period_name": period.name,
            "start_date": period.start_date,
            "end_date": period.end_date,
            "payout_date": period.payout_date,
            "status": period.status,
            "employee_name": f"{employee.first_name} {employee.last_name}" if employee else "",
            "grade_name": grade.name if grade else None,
            "base_pay": item.base_pay,
            "overtime_pay": item.overtime_pay,
            "gross_pay": item.gross_pay,
            "total_deductions": item.total_deductions,
            "total_contributions": item.total_contributions,
            "net_pay": item.net_pay,
            "breakdown": item.breakdown or {},
        }
