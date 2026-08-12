import asyncio
import logging
from datetime import date, datetime
from typing import List, Optional
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
from app.models.schedule import Shift, DateRemark
from app.models.settings import AppSettings
from app.models.leave import OvertimeCategory
from app.models.attendance import OvertimeLog, TardinessRecord, LeaveCreditAdjustment
from app.models.compensation import CompensationItem
from app.services.payroll_compute import (
    deduction_amount,
    derive_rates,
    night_diff_minutes,
    period_fraction,
)

logger = logging.getLogger(__name__)


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
        db: AsyncSession, tenant_id: UUID, data: dict
    ) -> EmployeeSalary:
        es = EmployeeSalary(tenant_id=tenant_id, **data)
        db.add(es)
        await db.commit()
        await db.refresh(es)
        return es

    @staticmethod
    async def get_employee_current_salary(
        db: AsyncSession, tenant_id: UUID, employee_id: int, as_of: Optional[date] = None
    ) -> Optional[EmployeeSalary]:
        ref_date = as_of or date.today()
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
        ref_date = as_of or date.today()
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

        ordered = sorted(brackets, key=lambda b: b.get("over_amount", 0) or 0)
        prev_upper = None
        for b in ordered:
            over = b.get("over_amount", 0) or 0
            up_to = b.get("up_to_amount")
            if up_to is not None and up_to <= over:
                raise ValueError("Bracket up_to_amount must be greater than over_amount")
            if prev_upper is not None and over < prev_upper:
                raise ValueError("Bracket bands must not overlap")
            prev_upper = up_to if up_to is not None else float("inf")

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
        """{date: 'regular'|'special'} for holidays in the period."""
        rows = (await db.execute(
            select(DateRemark).where(
                DateRemark.tenant_id == tenant_id,
                DateRemark.date >= start,
                DateRemark.date <= end,
                DateRemark.is_holiday == True,  # noqa: E712
            )
        )).scalars().all()
        out = {}
        for r in rows:
            out[r.date] = "special" if getattr(r, "is_special", False) else "regular"
        return out

    @staticmethod
    async def _compute_one(
        db: AsyncSession, tenant_id: UUID, period: PayrollPeriod, employee: User,
        ctx: dict, holidays: dict,
    ) -> Optional[PayrollItem]:
        salary = await PayrollService.get_employee_current_salary(
            db, tenant_id, employee.id, as_of=period.end_date
        )
        if not salary:
            return None

        grade = await db.get(SalaryGrade, salary.salary_grade_id)
        monthly_rate = salary.monthly_rate_override or (grade.monthly_rate if grade else 0.0)

        settings = ctx["settings"]
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

        # Base pay prorated by period type (fixes semi-monthly double-pay).
        base_pay = monthly_rate * period_fraction(period.period_type)

        overtime_pay = 0.0
        overtime_details: list[dict] = []
        premium_details: list[dict] = []

        # ── OT: OvertimeLog is authoritative. Track dates to dedupe shift OT. ──
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
            )
        )).scalars().all()
        for log in ot_logs:
            ot_log_dates.add(log.date)
            hours = (log.overtime_minutes or 0) / 60.0
            # Resolve multiplier: explicit on the log, else premium settings by
            # log_type, else the category multiplier, else 1.0.
            multiplier = log.pay_multiplier
            if multiplier is None:
                if log.log_type == "night_differential":
                    multiplier = getattr(settings, "night_diff_multiplier", 1.10) or 1.10
                elif log.log_type == "holiday_shift":
                    klass = holidays.get(log.date, "regular")
                    if klass == "special":
                        multiplier = getattr(settings, "special_holiday_worked_multiplier", 1.3) or 1.3
                    else:
                        multiplier = getattr(settings, "holiday_worked_multiplier", 2.0) or 2.0
                elif log.overtime_category and log.overtime_category.multiplier_rate:
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
            })

        # ── Legacy shift-status OT (deprecated), skipping dates already logged ──
        shift_ot = (await db.execute(
            select(Shift).where(
                Shift.tenant_id == tenant_id,
                Shift.employee_id == employee.id,
                Shift.date >= period.start_date,
                Shift.date <= period.end_date,
                Shift.status.in_(["overtime", "ot"]),
            )
        )).scalars().all()
        for shift in shift_ot:
            if shift.date in ot_log_dates:
                continue  # OvertimeLog wins
            if not (shift.start_time and shift.end_time):
                continue
            start_dt = datetime.combine(shift.date, shift.start_time)
            end_dt = datetime.combine(shift.date, shift.end_time)
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

        # ── Holiday / night premiums on regular worked shifts ──
        premium_pay = 0.0
        worked = (await db.execute(
            select(Shift).where(
                Shift.tenant_id == tenant_id,
                Shift.employee_id == employee.id,
                Shift.date >= period.start_date,
                Shift.date <= period.end_date,
                Shift.status.in_(["worked", "scheduled"]),
            )
        )).scalars().all()
        night_start = getattr(settings, "night_shift_start", None)
        night_end = getattr(settings, "night_shift_end", None)
        night_mult = getattr(settings, "night_diff_multiplier", 1.10) or 1.10
        for shift in worked:
            if not (shift.start_time and shift.end_time):
                continue
            hrs = (datetime.combine(shift.date, shift.end_time)
                   - datetime.combine(shift.date, shift.start_time)).total_seconds() / 3600
            if hrs <= 0:
                continue
            # Holiday premium (worked hours × (multiplier − 1))
            if shift.date in holidays:
                klass = holidays[shift.date]
                mult = (getattr(settings, "special_holiday_worked_multiplier", 1.3) or 1.3) \
                    if klass == "special" else (getattr(settings, "holiday_worked_multiplier", 2.0) or 2.0)
                extra = hrs * hourly_rate * (mult - 1)
                if extra:
                    premium_pay += extra
                    premium_details.append({
                        "date": str(shift.date), "kind": f"holiday_{klass}",
                        "hours": round(hrs, 2), "multiplier": mult, "amount": round(extra, 2),
                    })
            # Night differential premium
            nd_min = night_diff_minutes(shift.start_time, shift.end_time, night_start, night_end)
            if nd_min > 0:
                extra = (nd_min / 60.0) * hourly_rate * (night_mult - 1)
                if extra:
                    premium_pay += extra
                    premium_details.append({
                        "date": str(shift.date), "kind": "night_diff",
                        "hours": round(nd_min / 60.0, 2), "multiplier": night_mult,
                        "amount": round(extra, 2),
                    })

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
            amount = tard.deduction_amount or 0.0
            if amount > 0:
                tardiness_deduction += amount
                tardiness_details.append({
                    "date": str(tard.date),
                    "minutes_late": tard.tardiness_minutes,
                    "amount": round(amount, 2),
                })

        # ── Variable compensation due in this run (bonus/incentive/allowance/
        #    salary_adjustment/leave_cash/correction). When the run has a
        #    payout_date, pay everything scheduled for that date (this is how a
        #    Jan-1 holiday earned amount can be paid in a later run). Otherwise
        #    fall back to earned_on within the range so legacy runs still work. ──
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
        deduction_details: list[dict] = []
        total_deductions = tardiness_deduction
        total_contributions = 0.0
        for ded in ctx["deductions"]:
            amount, entry = deduction_amount(ded, gross_pay, base_pay, list(ded.brackets))
            deduction_details.append(entry)
            if ded.is_employer_contribution:
                total_contributions += amount
            else:
                total_deductions += amount

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
                "overtime": overtime_details,
                "premiums": premium_details,
                "leave_conversions": conversion_details,
                "earnings": earnings_details,
                "tardiness": tardiness_details,
                "rates": {"daily": daily_rate, "hourly": hourly_rate,
                          "period_fraction": period_fraction(period.period_type)},
            },
        )

    @staticmethod
    async def _run_compute(
        db: AsyncSession, tenant_id: UUID, period: PayrollPeriod, *,
        progress: bool = False,
    ) -> List[dict]:
        """Recompute all items for a period in `db`. Assumes status already set.

        Returns a list of skipped-employee dicts (those with no effective salary
        as of the period end) so the caller can surface who was excluded instead
        of silently dropping them from payroll."""
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
        total = len(employees)
        for idx, employee in enumerate(employees, start=1):
            item = await PayrollService._compute_one(
                db, tenant_id, period, employee, ctx, holidays
            )
            if item is not None:
                db.add(item)
            else:
                skipped.append({
                    "employee_id": employee.id,
                    "employee_name": f"{employee.first_name} {employee.last_name}",
                    "reason": "no_salary_assigned",
                })
            if progress and (idx % 25 == 0 or idx == total):
                period.compute_progress = {"done": idx, "total": total}
                await db.flush()

        return skipped

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

        skipped = await PayrollService._run_compute(db, tenant_id, period)
        period.status = "computed"
        # Retain the skipped list (employees without a salary) so it can be
        # surfaced; clear otherwise so no stale progress lingers.
        period.compute_progress = {"skipped": skipped} if skipped else None
        period.computed_at = datetime.utcnow()
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
                skipped = await PayrollService._run_compute(
                    db, tenant_id, period, progress=True
                )
                period.status = "computed"
                period.compute_progress = {"skipped": skipped} if skipped else None
                period.computed_at = datetime.utcnow()
                period.computed_by = computed_by
                await db.commit()
            except Exception as exc:  # noqa: BLE001
                logger.exception("Background payroll compute failed for period %s", period_id)
                await db.rollback()
                period = await db.get(PayrollPeriod, period_id)
                if period:
                    period.status = "compute_failed"
                    period.notes = f"Compute failed: {exc}"
                    period.compute_progress = None
                    await db.commit()

    @staticmethod
    async def approve_payroll(
        db: AsyncSession, tenant_id: UUID, period_id: int, approved_by: int
    ) -> PayrollPeriod:
        period = await db.get(PayrollPeriod, period_id)
        if not period or period.tenant_id != tenant_id:
            raise ValueError("Payroll period not found")
        if period.status != "computed":
            raise ValueError(f"Cannot approve payroll in '{period.status}' status")
        period.status = "approved"
        period.approved_at = datetime.utcnow()
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

        # Mark the compensation lines that were swept into each item as paid, so
        # they cannot be double-paid by a later run. The item's breakdown records
        # exactly which CompensationItem ids were included.
        items = (await db.execute(
            select(PayrollItem).where(
                PayrollItem.tenant_id == tenant_id,
                PayrollItem.payroll_period_id == period.id,
            )
        )).scalars().all()
        for item in items:
            comp_ids = [
                e.get("id") for e in ((item.breakdown or {}).get("earnings") or [])
                if e.get("id") is not None
            ]
            if not comp_ids:
                continue
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

        period.status = "finalized"
        period.finalized_at = datetime.utcnow()
        period.finalized_by = finalized_by
        await db.commit()
        await db.refresh(period)
        return period

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
        return {
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
