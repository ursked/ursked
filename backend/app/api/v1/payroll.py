from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import (
    get_current_user,
    require_permission,
    require_salary_access,
    salary_visibility,
)
from app.models.payroll import SalaryGrade
from app.models.user import User
from app.schemas.payroll import (
    DeductionBracketResponse,
    DeductionBracketsReplace,
    DeductionTypeCreate,
    DeductionTypeResponse,
    DeductionTypeUpdate,
    EmployeeSalaryCreate,
    EmployeeSalaryResponse,
    PAY_RULE_FIELDS,
    MyPayslipDetail,
    MyPayslipSummary,
    PayRulesResponse,
    PayRulesUpdate,
    PayrollItemResponse,
    PayrollPeriodCreate,
    PayrollPeriodResponse,
    PayrollSummary,
    SalaryGradeCreate,
    SalaryGradeResponse,
    SalaryGradeUpdate,
)
from app.services import audit_service
from app.services.payroll_service import MakerCheckerError, PayrollService
from app.services.settings_service import SettingsService

router = APIRouter(prefix="/payroll", tags=["payroll"])

# The permission matrix governs the STRUCTURE here (finances: view / create /
# edit / delete; see the contract in permission_service): deduction types and
# their brackets, grade names, the period calendar. Every FIGURE additionally
# needs an approved salary-viewer enrollment, and nobody bypasses that,
# tenant_admin included. Endpoints that serve both (grades, periods) answer
# finances:view and strip the figures for a non-viewer; endpoints that are
# only figures (salaries, items, summaries, compute) refuse them.
#
# Approve and finalize are maker-checker: finances:edit plus viewer, and never
# the person who computed the run (PayrollService.assert_not_preparer).

_RATE_FIELDS = ("monthly_rate", "daily_rate", "hourly_rate")


def _grade_response(grade, can_see_pay: bool) -> SalaryGradeResponse:
    out = SalaryGradeResponse.model_validate(grade)
    if not can_see_pay:
        out = out.model_copy(update={f: None for f in _RATE_FIELDS} | {"rates_hidden": True})
    return out


def _progress_for(progress, can_see_pay: bool):
    """compute_progress for this caller. Its warnings can quote pay (a bracket
    that does not cover someone's gross), so a non-viewer gets the progress,
    the skipped names and any failure, but not the warnings themselves."""
    if can_see_pay or not progress or "warnings" not in progress:
        return progress
    return {k: v for k, v in progress.items() if k != "warnings"}


def _period_response(p, items=None, can_see_pay: bool = True) -> PayrollPeriodResponse:
    resp = _full_period_response(p, items)
    if can_see_pay:
        return resp
    # The payroll calendar is structure; its totals are figures.
    return resp.model_copy(update={
        "total_gross": None,
        "total_net": None,
        "figures_hidden": True,
        "compute_progress": _progress_for(p.compute_progress, False),
    })


def _full_period_response(p, items=None) -> PayrollPeriodResponse:
    items = items or []
    return PayrollPeriodResponse(
        id=p.id,
        name=p.name,
        period_type=p.period_type,
        start_date=p.start_date,
        end_date=p.end_date,
        payout_date=p.payout_date,
        schedule_id=p.schedule_id,
        status=p.status,
        compute_progress=p.compute_progress,
        computed_at=p.computed_at,
        computed_by=p.computed_by,
        approved_at=p.approved_at,
        approved_by=p.approved_by,
        finalized_at=p.finalized_at,
        finalized_by=p.finalized_by,
        notes=p.notes,
        item_count=len(items),
        total_gross=round(sum(i.gross_pay for i in items), 2) if items else 0,
        total_net=round(sum(i.net_pay for i in items), 2) if items else 0,
        created_at=p.created_at,
        updated_at=p.updated_at,
    )


async def _salary_response(db, es) -> EmployeeSalaryResponse:
    grade = await db.get(SalaryGrade, es.salary_grade_id)
    return EmployeeSalaryResponse(
        id=es.id,
        employee_id=es.employee_id,
        salary_grade_id=es.salary_grade_id,
        effective_date=es.effective_date,
        monthly_rate_override=es.monthly_rate_override,
        notes=es.notes,
        grade_code=grade.code if grade else None,
        grade_name=grade.name if grade else None,
        grade_monthly_rate=grade.monthly_rate if grade else None,
        created_at=es.created_at,
        updated_at=es.updated_at,
    )


# ── Salary Grades ─────────────────────────────────────────────────


@router.get("/salary-grades", response_model=List[SalaryGradeResponse])
async def list_salary_grades(
    current_user: User = Depends(require_permission("finances", "view")),
    db: AsyncSession = Depends(get_db),
    can_see_pay: bool = Depends(salary_visibility()),
):
    grades = await PayrollService.list_salary_grades(db, current_user.tenant_id)
    return [_grade_response(g, can_see_pay) for g in grades]


@router.get("/salary-grades/all", response_model=List[SalaryGradeResponse])
async def list_all_salary_grades(
    current_user: User = Depends(require_permission("finances", "view")),
    db: AsyncSession = Depends(get_db),
    can_see_pay: bool = Depends(salary_visibility()),
):
    grades = await PayrollService.list_salary_grades(db, current_user.tenant_id, active_only=False)
    return [_grade_response(g, can_see_pay) for g in grades]


@router.post("/salary-grades", response_model=SalaryGradeResponse, status_code=201)
async def create_salary_grade(
    data: SalaryGradeCreate,
    current_user: User = Depends(require_permission("finances", "create")),
    db: AsyncSession = Depends(get_db),
    _sal=Depends(require_salary_access()),
):
    """A new grade always carries a monthly rate, which is a figure, so
    creating one needs salary access as well as finances:create."""
    try:
        grade = await PayrollService.create_salary_grade(
            db, current_user.tenant_id, data.model_dump()
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _grade_response(grade, True)


@router.patch("/salary-grades/{grade_id}", response_model=SalaryGradeResponse)
async def update_salary_grade(
    grade_id: int,
    data: SalaryGradeUpdate,
    current_user: User = Depends(require_permission("finances", "edit")),
    db: AsyncSession = Depends(get_db),
    can_see_pay: bool = Depends(salary_visibility()),
):
    """Renaming, describing, reordering or retiring a grade is structure. Setting
    a rate is a figure, so it needs salary access too."""
    changes = data.model_dump(exclude_unset=True)
    if not can_see_pay and any(f in changes for f in _RATE_FIELDS):
        raise HTTPException(
            403,
            "Changing a grade's rates needs salary access. You can still rename, "
            "describe or retire the grade.",
        )
    try:
        grade = await PayrollService.update_salary_grade(
            db, current_user.tenant_id, grade_id, changes
        )
    except ValueError as e:
        raise HTTPException(404, str(e))
    return _grade_response(grade, can_see_pay)


@router.delete("/salary-grades/{grade_id}", status_code=204)
async def delete_salary_grade(
    grade_id: int,
    current_user: User = Depends(require_permission("finances", "delete")),
    db: AsyncSession = Depends(get_db),
):
    # Structure: removing (or, when in use, retiring) a grade reveals no figure.
    try:
        await PayrollService.delete_salary_grade(db, current_user.tenant_id, grade_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


# ── Employee Salary ───────────────────────────────────────────────


@router.post("/employee-salary", response_model=EmployeeSalaryResponse, status_code=201)
async def assign_employee_salary(
    data: EmployeeSalaryCreate,
    current_user: User = Depends(require_permission("finances", "edit")),
    db: AsyncSession = Depends(get_db),
    _sal=Depends(require_salary_access()),
):
    from app.services.access_scope import assert_not_own_record

    # Conflict of interest: see access_scope.OWN_RECORD_MESSAGES.
    assert_not_own_record(current_user, [data.employee_id], "pay")
    try:
        es = await PayrollService.assign_employee_salary(
            db, current_user.tenant_id, data.model_dump(), actor=current_user
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return await _salary_response(db, es)


@router.get("/employee-salary/{employee_id}", response_model=EmployeeSalaryResponse)
async def get_employee_salary(
    employee_id: int,
    current_user: User = Depends(require_permission("finances", "view")),
    db: AsyncSession = Depends(get_db),
    _sal=Depends(require_salary_access()),
):
    es = await PayrollService.get_employee_current_salary(
        db, current_user.tenant_id, employee_id
    )
    if not es:
        raise HTTPException(404, "No salary assignment found for this employee")
    return await _salary_response(db, es)


@router.get("/employee-salary/{employee_id}/history", response_model=List[EmployeeSalaryResponse])
async def get_employee_salary_history(
    employee_id: int,
    current_user: User = Depends(require_permission("finances", "view")),
    db: AsyncSession = Depends(get_db),
    _sal=Depends(require_salary_access()),
):
    records = await PayrollService.get_employee_salary_history(
        db, current_user.tenant_id, employee_id
    )
    return [await _salary_response(db, es) for es in records]


# ── Deduction Types ───────────────────────────────────────────────
# Structure, not figures: finances:view / create / edit / delete, no salary
# access. Assumption, stated because it is a judgment call: a deduction type's
# fixed amount or rate and a bracket table (the statutory contribution tables
# are the usual case) are company-wide or published rules that apply to
# everyone alike. They do not say what any one person earns, which is what the
# owner asked to keep confidential. The amount a table produces for a given
# employee IS a figure and only appears in payroll items and payslips.


@router.get("/deduction-types", response_model=List[DeductionTypeResponse])
async def list_deduction_types(
    current_user: User = Depends(require_permission("finances", "view")),
    db: AsyncSession = Depends(get_db),
):
    return await PayrollService.list_deduction_types(db, current_user.tenant_id)


@router.get("/deduction-types/all", response_model=List[DeductionTypeResponse])
async def list_all_deduction_types(
    current_user: User = Depends(require_permission("finances", "view")),
    db: AsyncSession = Depends(get_db),
):
    return await PayrollService.list_deduction_types(db, current_user.tenant_id, active_only=False)


@router.post("/deduction-types", response_model=DeductionTypeResponse, status_code=201)
async def create_deduction_type(
    data: DeductionTypeCreate,
    current_user: User = Depends(require_permission("finances", "create")),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await PayrollService.create_deduction_type(
            db, current_user.tenant_id, data.model_dump()
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.patch("/deduction-types/{dt_id}", response_model=DeductionTypeResponse)
async def update_deduction_type(
    dt_id: int,
    data: DeductionTypeUpdate,
    current_user: User = Depends(require_permission("finances", "edit")),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await PayrollService.update_deduction_type(
            db, current_user.tenant_id, dt_id, data.model_dump(exclude_unset=True)
        )
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.delete("/deduction-types/{dt_id}", status_code=204)
async def delete_deduction_type(
    dt_id: int,
    current_user: User = Depends(require_permission("finances", "delete")),
    db: AsyncSession = Depends(get_db),
):
    try:
        await PayrollService.delete_deduction_type(db, current_user.tenant_id, dt_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


# ── Deduction Brackets (tiered tables) ────────────────────────────


@router.get("/deduction-types/{dt_id}/brackets", response_model=List[DeductionBracketResponse])
async def list_deduction_brackets(
    dt_id: int,
    current_user: User = Depends(require_permission("finances", "view")),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await PayrollService.list_deduction_brackets(db, current_user.tenant_id, dt_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.put("/deduction-types/{dt_id}/brackets", response_model=List[DeductionBracketResponse])
async def replace_deduction_brackets(
    dt_id: int,
    data: DeductionBracketsReplace,
    current_user: User = Depends(require_permission("finances", "edit")),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await PayrollService.replace_deduction_brackets(
            db, current_user.tenant_id, dt_id,
            [b.model_dump() for b in data.brackets],
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


# ── Payroll Periods ───────────────────────────────────────────────


@router.get("/periods", response_model=List[PayrollPeriodResponse])
async def list_payroll_periods(
    current_user: User = Depends(require_permission("finances", "view")),
    db: AsyncSession = Depends(get_db),
    can_see_pay: bool = Depends(salary_visibility()),
):
    """The payroll calendar. Totals only for salary viewers."""
    periods = await PayrollService.list_payroll_periods(db, current_user.tenant_id)
    results = []
    for p in periods:
        items = await PayrollService.get_payroll_items(db, current_user.tenant_id, p.id)
        results.append(_period_response(p, items, can_see_pay))
    return results


@router.get("/periods/{period_id}", response_model=PayrollPeriodResponse)
async def get_payroll_period(
    period_id: int,
    current_user: User = Depends(require_permission("finances", "view")),
    db: AsyncSession = Depends(get_db),
    can_see_pay: bool = Depends(salary_visibility()),
):
    """One period, including compute_progress: {done, total} while computing,
    then who was skipped (no salary), any warnings, or the failure reason.
    The Payroll screen polls this after starting a compute. Totals and
    warnings only for salary viewers."""
    period = await PayrollService.get_payroll_period(db, current_user.tenant_id, period_id)
    if not period:
        raise HTTPException(404, "Payroll period not found")
    items = await PayrollService.get_payroll_items(db, current_user.tenant_id, period_id)
    return _period_response(period, items, can_see_pay)


@router.post("/periods", response_model=PayrollPeriodResponse, status_code=201)
async def create_payroll_period(
    data: PayrollPeriodCreate,
    current_user: User = Depends(require_permission("finances", "create")),
    db: AsyncSession = Depends(get_db),
    can_see_pay: bool = Depends(salary_visibility()),
):
    """Structure: a new period is a name and dates, no figures yet."""
    if data.end_date < data.start_date:
        raise HTTPException(400, "The end date must be on or after the start date.")
    try:
        period = await PayrollService.create_payroll_period(
            db, current_user.tenant_id, data.model_dump()
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _period_response(period, None, can_see_pay)


@router.post("/periods/{period_id}/compute", response_model=PayrollPeriodResponse, status_code=202)
async def compute_payroll(
    period_id: int,
    current_user: User = Depends(require_permission("finances", "edit")),
    db: AsyncSession = Depends(get_db),
    _sal=Depends(require_salary_access()),
):
    """Kick off a background compute and return immediately with status
    'computing'. Poll GET /payroll/periods/{id} for compute_progress and the
    terminal 'computed' / 'compute_failed' status.

    Computing produces everyone's figures, so it needs salary access as well
    as finances:edit, and it makes the caller this run's preparer."""
    try:
        period = await PayrollService.start_compute(
            db, current_user.tenant_id, period_id, current_user.id
        )
        return _period_response(period)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/periods/{period_id}/approve", response_model=PayrollPeriodResponse)
async def approve_payroll(
    period_id: int,
    current_user: User = Depends(require_permission("finances", "edit")),
    db: AsyncSession = Depends(get_db),
    _sal=Depends(require_salary_access()),
):
    """Maker-checker: anyone with finances:edit and salary access, except the
    person who computed the run (403 with a readable reason)."""
    try:
        period = await PayrollService.approve_payroll(
            db, current_user.tenant_id, period_id, current_user.id
        )
    except MakerCheckerError as e:
        raise HTTPException(403, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    items = await PayrollService.get_payroll_items(db, current_user.tenant_id, period_id)
    return _period_response(period, items)


@router.post("/periods/{period_id}/finalize", response_model=PayrollPeriodResponse)
async def finalize_payroll(
    period_id: int,
    current_user: User = Depends(require_permission("finances", "edit")),
    db: AsyncSession = Depends(get_db),
    _sal=Depends(require_salary_access()),
):
    """Same rule as approve: never the person who computed the run."""
    try:
        period = await PayrollService.finalize_payroll(
            db, current_user.tenant_id, period_id, current_user.id
        )
    except MakerCheckerError as e:
        raise HTTPException(403, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    items = await PayrollService.get_payroll_items(db, current_user.tenant_id, period_id)
    return _period_response(period, items)


def _item_response(item, employee_name, grade_name) -> PayrollItemResponse:
    return PayrollItemResponse(
        id=item.id,
        payroll_period_id=item.payroll_period_id,
        employee_id=item.employee_id,
        employee_name=employee_name,
        salary_grade_id=item.salary_grade_id,
        grade_name=grade_name,
        base_pay=item.base_pay,
        overtime_pay=item.overtime_pay,
        gross_pay=item.gross_pay,
        total_deductions=item.total_deductions,
        total_contributions=item.total_contributions,
        net_pay=item.net_pay,
        breakdown=item.breakdown,
        notes=item.notes,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


@router.get("/periods/{period_id}/items", response_model=List[PayrollItemResponse])
async def get_payroll_items(
    period_id: int,
    current_user: User = Depends(require_permission("finances", "view")),
    db: AsyncSession = Depends(get_db),
    _sal=Depends(require_salary_access()),
):
    items = await PayrollService.get_payroll_items(db, current_user.tenant_id, period_id)
    results = []
    for item in items:
        employee = await db.get(User, item.employee_id)
        grade = await db.get(SalaryGrade, item.salary_grade_id) if item.salary_grade_id else None
        results.append(_item_response(
            item,
            f"{employee.first_name} {employee.last_name}" if employee else "Unknown",
            grade.name if grade else None,
        ))
    return results


@router.get("/periods/{period_id}/summary", response_model=PayrollSummary)
async def get_payroll_summary(
    period_id: int,
    current_user: User = Depends(require_permission("finances", "view")),
    db: AsyncSession = Depends(get_db),
    _sal=Depends(require_salary_access()),
):
    try:
        summary = await PayrollService.get_payroll_summary(
            db, current_user.tenant_id, period_id
        )
    except ValueError as e:
        raise HTTPException(404, str(e))

    period = summary["period"]
    period_resp = _period_response(period, [e["item"] for e in summary["items"]])
    item_responses = [
        _item_response(e["item"], e["employee_name"], e["grade_name"]) for e in summary["items"]
    ]
    return PayrollSummary(
        period=period_resp,
        total_employees=summary["total_employees"],
        total_base_pay=summary["total_base_pay"],
        total_overtime_pay=summary["total_overtime_pay"],
        total_gross_pay=summary["total_gross_pay"],
        total_deductions=summary["total_deductions"],
        total_contributions=summary["total_contributions"],
        total_net_pay=summary["total_net_pay"],
        items=item_responses,
    )


# ── Pay rules ─────────────────────────────────────────────────────
# Working days per month and the night and holiday premiums. Structure, so
# finances:view reads them and finances:edit changes them, with no salary
# access needed: they say how pay is worked out, not what anyone earns.
# Settings no longer changes them (PATCH /settings/app refuses).

@router.get("/pay-rules", response_model=PayRulesResponse)
async def get_pay_rules(
    current_user: User = Depends(require_permission("finances", "view")),
    db: AsyncSession = Depends(get_db),
):
    settings = await SettingsService.get_or_create_app_settings(db, current_user.tenant_id)
    return PayRulesResponse.model_validate(settings)


@router.put("/pay-rules", response_model=PayRulesResponse)
async def update_pay_rules(
    data: PayRulesUpdate,
    request: Request,
    current_user: User = Depends(require_permission("finances", "edit")),
    db: AsyncSession = Depends(get_db),
):
    settings = await SettingsService.get_or_create_app_settings(db, current_user.tenant_id)
    before = {f: getattr(settings, f) for f in PAY_RULE_FIELDS}
    after = data.model_dump()
    for field, value in after.items():
        setattr(settings, field, value)
    # These change what every future payroll pays, so who changed which rule,
    # and from what, is written down.
    changes = audit_service.diff(before, after)
    if changes:
        audit_service.record(
            db, actor=current_user, action="pay_rules_update", resource_type="app_settings",
            resource_id=settings.id, details={"changes": changes}, request=request,
        )
    await db.flush()
    await db.refresh(settings)
    return PayRulesResponse.model_validate(settings)


# ── Employee self-service payslips ────────────────────────────────
# NOTE: intentionally NOT gated by the permission matrix. Any authenticated
# user may read ONLY their own released payslips; the service scopes every
# query to current_user.id and only exposes approved/finalized runs.

@router.get("/my-payslips", response_model=List[MyPayslipSummary])
async def list_my_payslips(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await PayrollService.list_my_payslips(
        db, current_user.tenant_id, current_user.id
    )


@router.get("/my-payslips/{period_id}", response_model=MyPayslipDetail)
async def get_my_payslip(
    period_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    payslip = await PayrollService.get_my_payslip(
        db, current_user.tenant_id, current_user.id, period_id
    )
    if payslip is None:
        # Unreleased period, or no item for this employee — same 404 either way so
        # an employee cannot distinguish "not mine" from "doesn't exist".
        raise HTTPException(status_code=404, detail="Payslip not found")
    return payslip
