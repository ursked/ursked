from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import get_current_user, require_role, require_salary_access
from app.models.user import User
from app.schemas.payroll import (
    DeductionBracketResponse,
    DeductionBracketsReplace,
    DeductionTypeCreate,
    DeductionTypeResponse,
    DeductionTypeUpdate,
    EmployeeSalaryCreate,
    EmployeeSalaryResponse,
    MyPayslipDetail,
    MyPayslipSummary,
    PayrollItemResponse,
    PayrollPeriodCreate,
    PayrollPeriodResponse,
    PayrollSummary,
    SalaryGradeCreate,
    SalaryGradeResponse,
    SalaryGradeUpdate,
)
from app.services.payroll_service import PayrollService

router = APIRouter(prefix="/payroll", tags=["payroll"])

PAYROLL_ROLES = ["tenant_admin", "finance"]


# ── Salary Grades ─────────────────────────────────────────────────


@router.get("/salary-grades", response_model=List[SalaryGradeResponse])
async def list_salary_grades(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(PAYROLL_ROLES)),
    _sal=Depends(require_salary_access()),
):
    return await PayrollService.list_salary_grades(db, current_user.tenant_id)


@router.get("/salary-grades/all", response_model=List[SalaryGradeResponse])
async def list_all_salary_grades(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(PAYROLL_ROLES)),
    _sal=Depends(require_salary_access()),
):
    return await PayrollService.list_salary_grades(db, current_user.tenant_id, active_only=False)


@router.post("/salary-grades", response_model=SalaryGradeResponse, status_code=201)
async def create_salary_grade(
    data: SalaryGradeCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(PAYROLL_ROLES)),
    _sal=Depends(require_salary_access()),
):
    try:
        return await PayrollService.create_salary_grade(
            db, current_user.tenant_id, data.model_dump()
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.patch("/salary-grades/{grade_id}", response_model=SalaryGradeResponse)
async def update_salary_grade(
    grade_id: int,
    data: SalaryGradeUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(PAYROLL_ROLES)),
    _sal=Depends(require_salary_access()),
):
    try:
        return await PayrollService.update_salary_grade(
            db, current_user.tenant_id, grade_id, data.model_dump(exclude_unset=True)
        )
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.delete("/salary-grades/{grade_id}", status_code=204)
async def delete_salary_grade(
    grade_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(PAYROLL_ROLES)),
    _sal=Depends(require_salary_access()),
):
    try:
        await PayrollService.delete_salary_grade(db, current_user.tenant_id, grade_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


# ── Employee Salary ───────────────────────────────────────────────


@router.post("/employee-salary", response_model=EmployeeSalaryResponse, status_code=201)
async def assign_employee_salary(
    data: EmployeeSalaryCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(PAYROLL_ROLES)),
    _sal=Depends(require_salary_access()),
):
    es = await PayrollService.assign_employee_salary(
        db, current_user.tenant_id, data.model_dump()
    )
    # Enrich response with grade info
    from app.models.payroll import SalaryGrade
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


@router.get("/employee-salary/{employee_id}", response_model=EmployeeSalaryResponse)
async def get_employee_salary(
    employee_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(PAYROLL_ROLES)),
    _sal=Depends(require_salary_access()),
):
    es = await PayrollService.get_employee_current_salary(
        db, current_user.tenant_id, employee_id
    )
    if not es:
        raise HTTPException(404, "No salary assignment found for this employee")
    from app.models.payroll import SalaryGrade
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


@router.get("/employee-salary/{employee_id}/history", response_model=List[EmployeeSalaryResponse])
async def get_employee_salary_history(
    employee_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(PAYROLL_ROLES)),
    _sal=Depends(require_salary_access()),
):
    records = await PayrollService.get_employee_salary_history(
        db, current_user.tenant_id, employee_id
    )
    results = []
    for es in records:
        from app.models.payroll import SalaryGrade
        grade = await db.get(SalaryGrade, es.salary_grade_id)
        results.append(EmployeeSalaryResponse(
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
        ))
    return results


# ── Deduction Types ───────────────────────────────────────────────


@router.get("/deduction-types", response_model=List[DeductionTypeResponse])
async def list_deduction_types(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(PAYROLL_ROLES)),
):
    return await PayrollService.list_deduction_types(db, current_user.tenant_id)


@router.get("/deduction-types/all", response_model=List[DeductionTypeResponse])
async def list_all_deduction_types(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(PAYROLL_ROLES)),
):
    return await PayrollService.list_deduction_types(db, current_user.tenant_id, active_only=False)


@router.post("/deduction-types", response_model=DeductionTypeResponse, status_code=201)
async def create_deduction_type(
    data: DeductionTypeCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(PAYROLL_ROLES)),
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
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(PAYROLL_ROLES)),
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
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(PAYROLL_ROLES)),
):
    try:
        await PayrollService.delete_deduction_type(db, current_user.tenant_id, dt_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


# ── Deduction Brackets (tiered tables) ────────────────────────────


@router.get("/deduction-types/{dt_id}/brackets", response_model=List[DeductionBracketResponse])
async def list_deduction_brackets(
    dt_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(PAYROLL_ROLES)),
):
    try:
        return await PayrollService.list_deduction_brackets(db, current_user.tenant_id, dt_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.put("/deduction-types/{dt_id}/brackets", response_model=List[DeductionBracketResponse])
async def replace_deduction_brackets(
    dt_id: int,
    data: DeductionBracketsReplace,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(PAYROLL_ROLES)),
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
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(PAYROLL_ROLES)),
    _sal=Depends(require_salary_access()),
):
    periods = await PayrollService.list_payroll_periods(db, current_user.tenant_id)
    results = []
    for p in periods:
        # Get item counts and totals
        items = await PayrollService.get_payroll_items(db, current_user.tenant_id, p.id)
        results.append(PayrollPeriodResponse(
            id=p.id,
            name=p.name,
            period_type=p.period_type,
            start_date=p.start_date,
            end_date=p.end_date,
            status=p.status,
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
        ))
    return results


@router.post("/periods", response_model=PayrollPeriodResponse, status_code=201)
async def create_payroll_period(
    data: PayrollPeriodCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(PAYROLL_ROLES)),
):
    period = await PayrollService.create_payroll_period(
        db, current_user.tenant_id, data.model_dump()
    )
    return PayrollPeriodResponse(
        id=period.id,
        name=period.name,
        period_type=period.period_type,
        start_date=period.start_date,
        end_date=period.end_date,
        status=period.status,
        notes=period.notes,
        item_count=0,
        total_gross=0,
        total_net=0,
        created_at=period.created_at,
        updated_at=period.updated_at,
    )


@router.post("/periods/{period_id}/compute", response_model=PayrollPeriodResponse, status_code=202)
async def compute_payroll(
    period_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(PAYROLL_ROLES)),
):
    """Kick off a background compute and return immediately with status
    'computing'. Poll GET /payroll/periods/{id} for compute_progress and the
    terminal 'computed' / 'compute_failed' status."""
    try:
        period = await PayrollService.start_compute(
            db, current_user.tenant_id, period_id, current_user.id
        )
        return PayrollPeriodResponse(
            id=period.id,
            name=period.name,
            period_type=period.period_type,
            start_date=period.start_date,
            end_date=period.end_date,
            status=period.status,
            compute_progress=period.compute_progress,
            computed_at=period.computed_at,
            computed_by=period.computed_by,
            notes=period.notes,
            item_count=0,
            total_gross=0,
            total_net=0,
            created_at=period.created_at,
            updated_at=period.updated_at,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/periods/{period_id}/approve", response_model=PayrollPeriodResponse)
async def approve_payroll(
    period_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(["tenant_admin"])),
):
    try:
        period = await PayrollService.approve_payroll(
            db, current_user.tenant_id, period_id, current_user.id
        )
        items = await PayrollService.get_payroll_items(db, current_user.tenant_id, period_id)
        return PayrollPeriodResponse(
            id=period.id,
            name=period.name,
            period_type=period.period_type,
            start_date=period.start_date,
            end_date=period.end_date,
            status=period.status,
            computed_at=period.computed_at,
            computed_by=period.computed_by,
            approved_at=period.approved_at,
            approved_by=period.approved_by,
            notes=period.notes,
            item_count=len(items),
            total_gross=round(sum(i.gross_pay for i in items), 2) if items else 0,
            total_net=round(sum(i.net_pay for i in items), 2) if items else 0,
            created_at=period.created_at,
            updated_at=period.updated_at,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/periods/{period_id}/finalize", response_model=PayrollPeriodResponse)
async def finalize_payroll(
    period_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(["tenant_admin"])),
):
    try:
        period = await PayrollService.finalize_payroll(
            db, current_user.tenant_id, period_id, current_user.id
        )
        items = await PayrollService.get_payroll_items(db, current_user.tenant_id, period_id)
        return PayrollPeriodResponse(
            id=period.id,
            name=period.name,
            period_type=period.period_type,
            start_date=period.start_date,
            end_date=period.end_date,
            status=period.status,
            computed_at=period.computed_at,
            computed_by=period.computed_by,
            approved_at=period.approved_at,
            approved_by=period.approved_by,
            finalized_at=period.finalized_at,
            finalized_by=period.finalized_by,
            notes=period.notes,
            item_count=len(items),
            total_gross=round(sum(i.gross_pay for i in items), 2) if items else 0,
            total_net=round(sum(i.net_pay for i in items), 2) if items else 0,
            created_at=period.created_at,
            updated_at=period.updated_at,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/periods/{period_id}/items", response_model=List[PayrollItemResponse])
async def get_payroll_items(
    period_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(PAYROLL_ROLES)),
    _sal=Depends(require_salary_access()),
):
    items = await PayrollService.get_payroll_items(db, current_user.tenant_id, period_id)
    results = []
    for item in items:
        employee = await db.get(User, item.employee_id)
        from app.models.payroll import SalaryGrade
        grade = await db.get(SalaryGrade, item.salary_grade_id) if item.salary_grade_id else None
        results.append(PayrollItemResponse(
            id=item.id,
            payroll_period_id=item.payroll_period_id,
            employee_id=item.employee_id,
            employee_name=f"{employee.first_name} {employee.last_name}" if employee else "Unknown",
            salary_grade_id=item.salary_grade_id,
            grade_name=grade.name if grade else None,
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
        ))
    return results


@router.get("/periods/{period_id}/summary", response_model=PayrollSummary)
async def get_payroll_summary(
    period_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(PAYROLL_ROLES)),
    _sal=Depends(require_salary_access()),
):
    try:
        summary = await PayrollService.get_payroll_summary(
            db, current_user.tenant_id, period_id
        )
    except ValueError as e:
        raise HTTPException(404, str(e))

    period = summary["period"]
    items_data = summary["items"]

    period_resp = PayrollPeriodResponse(
        id=period.id,
        name=period.name,
        period_type=period.period_type,
        start_date=period.start_date,
        end_date=period.end_date,
        status=period.status,
        computed_at=period.computed_at,
        computed_by=period.computed_by,
        approved_at=period.approved_at,
        approved_by=period.approved_by,
        finalized_at=period.finalized_at,
        finalized_by=period.finalized_by,
        notes=period.notes,
        item_count=summary["total_employees"],
        total_gross=summary["total_gross_pay"],
        total_net=summary["total_net_pay"],
        created_at=period.created_at,
        updated_at=period.updated_at,
    )

    item_responses = []
    for entry in items_data:
        item = entry["item"]
        item_responses.append(PayrollItemResponse(
            id=item.id,
            payroll_period_id=item.payroll_period_id,
            employee_id=item.employee_id,
            employee_name=entry["employee_name"],
            salary_grade_id=item.salary_grade_id,
            grade_name=entry["grade_name"],
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
        ))

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


# ── Employee self-service payslips ────────────────────────────────
# NOTE: intentionally NOT guarded by PAYROLL_ROLES. Any authenticated user may
# read ONLY their own released payslips; the service scopes every query to
# current_user.id and only exposes approved/finalized runs.

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
