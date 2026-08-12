from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import get_current_user, require_salary_approver
from app.models.user import User
from app.schemas.salary_enrollment import (
    CreateRequestBody,
    DecisionBody,
    EnrollmentRow,
    MyStatusResponse,
    RequestByToken,
    RequestRow,
    RevokeBody,
)
from app.services.salary_enrollment_service import (
    SalaryEnrollmentError,
    SalaryEnrollmentService,
)

router = APIRouter(prefix="/salary-enrollment", tags=["salary-enrollment"])


@router.get("/enrollments", response_model=List[EnrollmentRow])
async def list_enrollments(
    current_user: User = Depends(require_salary_approver()),
    db: AsyncSession = Depends(get_db),
):
    return await SalaryEnrollmentService.list_enrollments(db, current_user.tenant_id)


@router.get("/requests", response_model=List[RequestRow])
async def list_requests(
    status: Optional[str] = Query(None),
    current_user: User = Depends(require_salary_approver()),
    db: AsyncSession = Depends(get_db),
):
    return await SalaryEnrollmentService.list_requests(db, current_user.tenant_id, status)


@router.get("/my-status", response_model=MyStatusResponse)
async def my_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await SalaryEnrollmentService.my_status(db, current_user.tenant_id, current_user.id)


@router.post("/requests", response_model=RequestRow, status_code=201)
async def create_request(
    data: CreateRequestBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Requesting on behalf of another user requires the caller to be an approver.
    target_user_id = data.user_id or current_user.id
    if target_user_id != current_user.id:
        if not await SalaryEnrollmentService.is_approver(db, current_user.tenant_id, current_user.id):
            raise HTTPException(403, "Only an approver can request access on behalf of another user.")
    try:
        req = await SalaryEnrollmentService.create_request(
            db, current_user.tenant_id, target_user_id, data.kind, data.reason, current_user.id
        )
        await db.commit()
    except SalaryEnrollmentError as e:
        raise HTTPException(400, str(e))
    rows = await SalaryEnrollmentService.list_requests(db, current_user.tenant_id)
    for r in rows:
        if r["id"] == req.id:
            return r
    raise HTTPException(500, "Request created but not found")


@router.post("/requests/{request_id}/approve", response_model=RequestRow)
async def approve_request(
    request_id: int,
    data: DecisionBody,
    current_user: User = Depends(require_salary_approver()),
    db: AsyncSession = Depends(get_db),
):
    try:
        await SalaryEnrollmentService.decide(
            db, current_user.tenant_id, request_id, current_user.id, True, data.note
        )
        await db.commit()
    except SalaryEnrollmentError as e:
        raise HTTPException(400, str(e))
    rows = await SalaryEnrollmentService.list_requests(db, current_user.tenant_id)
    for r in rows:
        if r["id"] == request_id:
            return r
    raise HTTPException(404, "Request not found")


@router.post("/requests/{request_id}/decline", response_model=RequestRow)
async def decline_request(
    request_id: int,
    data: DecisionBody,
    current_user: User = Depends(require_salary_approver()),
    db: AsyncSession = Depends(get_db),
):
    try:
        await SalaryEnrollmentService.decide(
            db, current_user.tenant_id, request_id, current_user.id, False, data.note
        )
        await db.commit()
    except SalaryEnrollmentError as e:
        raise HTTPException(400, str(e))
    rows = await SalaryEnrollmentService.list_requests(db, current_user.tenant_id)
    for r in rows:
        if r["id"] == request_id:
            return r
    raise HTTPException(404, "Request not found")


@router.post("/requests/{request_id}/cancel", status_code=204)
async def cancel_request(
    request_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        ok = await SalaryEnrollmentService.cancel_request(
            db, current_user.tenant_id, request_id, current_user.id
        )
    except SalaryEnrollmentError as e:
        raise HTTPException(400, str(e))
    if not ok:
        raise HTTPException(404, "Request not found or not pending")
    await db.commit()


@router.post("/enrollments/revoke", status_code=204)
async def revoke_enrollment(
    data: RevokeBody,
    current_user: User = Depends(require_salary_approver()),
    db: AsyncSession = Depends(get_db),
):
    try:
        ok = await SalaryEnrollmentService.revoke(
            db, current_user.tenant_id, data.user_id, data.kind, current_user.id
        )
        await db.commit()
    except SalaryEnrollmentError as e:
        raise HTTPException(400, str(e))
    if not ok:
        raise HTTPException(404, "No active enrollment to revoke")


@router.get("/requests/by-token", response_model=RequestByToken)
async def get_request_by_token(
    token: str = Query(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Resolve a request from an email deep-link token. Read-only — the approve/
    decline decision is still made through the authenticated endpoints above."""
    req = await SalaryEnrollmentService.get_request_by_token(db, token)
    if not req:
        raise HTTPException(404, "Request not found, already decided, or link expired")
    return req
