from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import get_current_user, require_role, require_salary_access
from app.models.user import User
from app.schemas.compensation import (
    BulkCompensationCreate,
    CompensationItemCreate,
    CompensationItemResponse,
    CompensationItemVoid,
    CurrentSalaryRow,
    ExpandRecurringRequest,
    PayoutPreviewRequest,
    PayoutPreviewResponse,
    PayoutScheduleCreate,
    PayoutScheduleResponse,
    PayoutScheduleUpdate,
    RaiseRequest,
    RaiseResultRow,
    SalaryAssign,
)
from app.services.compensation_service import CompensationService
from app.services.payout_schedule_service import PayoutScheduleService
from app.services.payroll_service import PayrollService

router = APIRouter(prefix="/compensation", tags=["compensation"])

ROLES = ["tenant_admin", "finance"]


# ── Payout schedules ─────────────────────────────────────────────────

@router.get("/payout-schedules", response_model=List[PayoutScheduleResponse])
async def list_payout_schedules(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(ROLES)),
):
    return await PayoutScheduleService.list_schedules(db, current_user.tenant_id)


@router.get("/payout-schedules/active", response_model=Optional[PayoutScheduleResponse])
async def get_active_payout_schedule(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(ROLES)),
):
    return await PayoutScheduleService.get_active(db, current_user.tenant_id)


@router.post("/payout-schedules", response_model=PayoutScheduleResponse, status_code=201)
async def create_payout_schedule(
    data: PayoutScheduleCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(ROLES)),
):
    payload = data.model_dump()
    payload["cutoffs"] = [c if isinstance(c, dict) else c.model_dump() for c in data.cutoffs]
    sched = await PayoutScheduleService.create(db, current_user.tenant_id, payload)
    await db.commit()
    await db.refresh(sched)
    return sched


@router.patch("/payout-schedules/{schedule_id}", response_model=PayoutScheduleResponse)
async def update_payout_schedule(
    schedule_id: int,
    data: PayoutScheduleUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(ROLES)),
):
    payload = data.model_dump(exclude_unset=True)
    if "cutoffs" in payload and payload["cutoffs"] is not None:
        payload["cutoffs"] = [c if isinstance(c, dict) else c for c in payload["cutoffs"]]
    sched = await PayoutScheduleService.update(db, current_user.tenant_id, schedule_id, payload)
    if not sched:
        raise HTTPException(status_code=404, detail="Payout schedule not found")
    await db.commit()
    await db.refresh(sched)
    return sched


@router.delete("/payout-schedules/{schedule_id}", status_code=204)
async def delete_payout_schedule(
    schedule_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(ROLES)),
):
    ok = await PayoutScheduleService.delete(db, current_user.tenant_id, schedule_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Payout schedule not found")
    await db.commit()


@router.post("/payout-schedules/preview", response_model=PayoutPreviewResponse)
async def preview_payout_date(
    data: PayoutPreviewRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(ROLES)),
):
    payout = await PayoutScheduleService.resolve(db, current_user.tenant_id, data.earned_on)
    return PayoutPreviewResponse(earned_on=data.earned_on, payout_date=payout)


# ── Compensation items ───────────────────────────────────────────────

@router.get("/items", response_model=List[CompensationItemResponse])
async def list_compensation_items(
    employee_id: Optional[int] = None,
    kind: Optional[str] = None,
    status: Optional[str] = None,
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(ROLES)),
    _sal=Depends(require_salary_access()),
):
    return await CompensationService.list_items(
        db, current_user.tenant_id,
        employee_id=employee_id, kind=kind, status=status,
        date_from=date_from, date_to=date_to,
    )


@router.post("/items", response_model=CompensationItemResponse, status_code=201)
async def create_compensation_item(
    data: CompensationItemCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(ROLES)),
    _sal=Depends(require_salary_access()),
):
    item = await CompensationService.add_item(
        db, current_user.tenant_id, data.model_dump(), created_by=current_user.id
    )
    await db.commit()
    await db.refresh(item)
    return item


@router.post("/items/{item_id}/void", response_model=CompensationItemResponse)
async def void_compensation_item(
    item_id: int,
    data: CompensationItemVoid,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(ROLES)),
    _sal=Depends(require_salary_access()),
):
    item = await CompensationService.void_item(db, current_user.tenant_id, item_id, data.reason)
    if not item:
        raise HTTPException(status_code=400, detail="Item not found or already paid (post a correction instead)")
    await db.commit()
    await db.refresh(item)
    return item


# ── Salary assignment / raise (central Finances screen) ──────────────

@router.get("/salaries", response_model=List[CurrentSalaryRow])
async def list_current_salaries(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(ROLES)),
    _sal=Depends(require_salary_access()),
):
    return await PayrollService.list_current_salaries(db, current_user.tenant_id)


@router.post("/salaries", response_model=CurrentSalaryRow, status_code=201)
async def assign_salary(
    data: SalaryAssign,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(ROLES)),
    _sal=Depends(require_salary_access()),
):
    """Assign or change an employee's salary grade. A raise is the same call with
    a later effective_date (salary history is effective-dated)."""
    await PayrollService.assign_employee_salary(db, current_user.tenant_id, data.model_dump())
    rows = await PayrollService.list_current_salaries(db, current_user.tenant_id)
    for r in rows:
        if r["employee_id"] == data.employee_id:
            return r
    raise HTTPException(status_code=404, detail="Employee not found after assignment")


@router.post("/salaries/raise", response_model=List[RaiseResultRow])
async def give_raise(
    data: RaiseRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(ROLES)),
    _sal=Depends(require_salary_access()),
):
    """Apply a percent/fixed/grade salary increase to one or more employees.
    Writes a new effective-dated salary row per employee and a ledger audit line."""
    try:
        results = await PayrollService.give_raise(
            db, current_user.tenant_id,
            employee_ids=data.employee_ids, mode=data.mode, value=data.value,
            effective_date=data.effective_date, new_grade_id=data.new_grade_id,
            reason=data.reason, created_by=current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return results


@router.post("/items/bulk", response_model=List[CompensationItemResponse], status_code=201)
async def bulk_create_compensation(
    data: BulkCompensationCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(ROLES)),
    _sal=Depends(require_salary_access()),
):
    """Grant the same compensation line to many employees at once."""
    payload_base = data.model_dump()
    emp_ids = payload_base.pop("employee_ids")
    created = []
    for emp_id in emp_ids:
        item = await CompensationService.add_item(
            db, current_user.tenant_id, {**payload_base, "employee_id": emp_id},
            created_by=current_user.id,
        )
        created.append(item)
    await db.commit()
    for c in created:
        await db.refresh(c)
    return created


@router.post("/items/expand-recurring")
async def expand_recurring(
    data: ExpandRecurringRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(ROLES)),
):
    """Materialize recurring allowance/incentive templates into concrete
    scheduled rows across the given horizon (idempotent)."""
    count = await CompensationService.expand_recurring(
        db, current_user.tenant_id, data.horizon_start, data.horizon_end
    )
    await db.commit()
    return {"created": count}
