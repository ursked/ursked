"""Self-host SMTP settings + email log (tenant-admin).

The hosted SaaS configures SMTP through the operator console; a self-hosted
(Community) install has no such console, so tenant admins manage the single
platform SMTP row here. The password is write-only: GET reports has_password
but never returns the value.
"""
import importlib.util
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import require_role
from app.models.email_log import EmailLog
from app.models.site_settings import SiteSettings
from app.models.user import User
from app.services import smtp_client

router = APIRouter(prefix="/smtp-settings", tags=["SMTP Settings"])


def _is_enterprise() -> bool:
    """Enterprise ships the app.ee package; its absence is the Community gate.

    Same signal the API router and capabilities endpoint use."""
    return importlib.util.find_spec("app.ee") is not None


def _forbid_tenant_admin_writes_on_enterprise() -> None:
    """On the hosted SaaS, the platform SMTP row is owned by the operator
    console (superadmin), not tenant admins — a single shared row must not be
    editable by any one tenant's admin. Community self-host has no console, so
    tenant admins manage it there. Reads stay allowed either way."""
    if _is_enterprise():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="SMTP is managed by the platform operator on this deployment.",
        )


async def _get_or_create_settings(db: AsyncSession) -> SiteSettings:
    result = await db.execute(select(SiteSettings).limit(1))
    row = result.scalar_one_or_none()
    if row is None:
        row = SiteSettings()
        db.add(row)
        await db.commit()
        await db.refresh(row)
    return row


class SmtpSettingsResponse(BaseModel):
    smtp_active: bool
    smtp_host: Optional[str] = None
    smtp_port: int = 587
    smtp_use_ssl: bool = False
    smtp_use_tls: bool = True
    smtp_username: Optional[str] = None
    has_password: bool = False
    smtp_from_email: Optional[str] = None
    smtp_from_name: Optional[str] = None


class SmtpSettingsUpdate(BaseModel):
    smtp_active: Optional[bool] = None
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    smtp_use_ssl: Optional[bool] = None
    smtp_use_tls: Optional[bool] = None
    smtp_username: Optional[str] = None
    smtp_password: Optional[str] = None  # write-only; omit to keep current
    smtp_from_email: Optional[str] = None
    smtp_from_name: Optional[str] = None


class SmtpTestRequest(BaseModel):
    recipient: Optional[str] = None  # if set, also send a test email


def _to_response(s: SiteSettings) -> SmtpSettingsResponse:
    return SmtpSettingsResponse(
        smtp_active=s.smtp_active,
        smtp_host=s.smtp_host,
        smtp_port=s.smtp_port,
        smtp_use_ssl=s.smtp_use_ssl,
        smtp_use_tls=s.smtp_use_tls,
        smtp_username=s.smtp_username,
        has_password=bool(s.smtp_password),
        smtp_from_email=s.smtp_from_email,
        smtp_from_name=s.smtp_from_name,
    )


@router.get("", response_model=SmtpSettingsResponse)
async def get_smtp_settings(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role(["tenant_admin"])),
):
    return _to_response(await _get_or_create_settings(db))


@router.put("", response_model=SmtpSettingsResponse)
async def update_smtp_settings(
    payload: SmtpSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role(["tenant_admin"])),
):
    _forbid_tenant_admin_writes_on_enterprise()
    s = await _get_or_create_settings(db)
    data = payload.model_dump(exclude_unset=True)
    # Password is write-only: only overwrite when a non-empty value is provided.
    if "smtp_password" in data and not data["smtp_password"]:
        data.pop("smtp_password")
    for field, value in data.items():
        setattr(s, field, value)
    await db.commit()
    await db.refresh(s)
    return _to_response(s)


class SmtpTestResult(BaseModel):
    success: bool
    message: str


@router.post("/test", response_model=SmtpTestResult)
async def test_smtp(
    payload: SmtpTestRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role(["tenant_admin"])),
):
    _forbid_tenant_admin_writes_on_enterprise()
    s = await _get_or_create_settings(db)
    if payload.recipient:
        result = await smtp_client.send_test_email(s, payload.recipient)
    else:
        result = await smtp_client.test_connection(s)
    return SmtpTestResult(**result)


class EmailLogEntry(BaseModel):
    id: int
    type: str
    to_email: str
    subject: str
    status: str
    error_message: Optional[str] = None
    sent_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


@router.get("/email-logs", response_model=List[EmailLogEntry])
async def list_email_logs(
    status: Optional[str] = Query(None, pattern="^(pending|sent|failed)$"),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(["tenant_admin"])),
):
    stmt = select(EmailLog)
    if _is_enterprise():
        # Multi-tenant SaaS: scope STRICTLY to the caller's tenant. Tenant-less
        # system sends (tenant_id IS NULL, e.g. signup welcome) are excluded —
        # exposing them to any tenant admin would leak other tenants' recipient
        # addresses and subjects. Those belong to the operator console.
        stmt = stmt.where(EmailLog.tenant_id == current_user.tenant_id)
    else:
        # Community (single-tenant self-host): there is only one tenant, so the
        # admin should also see tenant-less system sends (welcome/invite) to
        # answer "did that email go out?".
        stmt = stmt.where(
            (EmailLog.tenant_id == current_user.tenant_id) | (EmailLog.tenant_id.is_(None))
        )
    if status:
        stmt = stmt.where(EmailLog.status == status)
    stmt = stmt.order_by(EmailLog.created_at.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return list(rows)
