"""CSV employee import (CE scope: name + email + password).

Accepts a CSV file with columns: first_name, last_name, email, password.
Creates users one by one using the same code path as the single-user form
(UserService.create_user). Each row is validated; failures are collected and
returned so the admin can fix and retry the failed rows.

CE scope: simple CSV with four fixed columns, employee role only.
Paid (not built): column mapping UI, field preview, bulk role assignment,
advanced validation, duplicate detection, org-tree placement, import history.
"""
import csv
import io
import logging

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import get_current_user, require_role
from app.models.user import User
from app.services.user_service import UserService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/users", tags=["Users"])

REQUIRED_COLUMNS = {"first_name", "last_name", "email", "password"}
MAX_ROWS = 500  # Guard against accidental mega-imports.


@router.post("/import-csv")
async def import_csv(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_role(["tenant_admin", "hr"])),
):
    """Import employees from a CSV file (first_name, last_name, email, password)."""
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="File must be a .csv")

    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")  # handle BOM from Excel
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File must be UTF-8 encoded")

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="CSV is empty or has no header row")

    # Normalize column names (strip whitespace, lowercase).
    col_map = {c.strip().lower(): c for c in reader.fieldnames}
    missing = REQUIRED_COLUMNS - set(col_map.keys())
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Missing required columns: {', '.join(sorted(missing))}. "
                   f"Expected: first_name, last_name, email, password",
        )

    created = []
    errors = []
    for i, row in enumerate(reader, start=2):  # row 1 is header
        if i - 1 > MAX_ROWS:
            errors.append({"row": i, "error": f"Stopped at {MAX_ROWS} rows (limit)"})
            break

        # Normalize using the column map.
        first = (row.get(col_map.get("first_name", ""), "") or "").strip()
        last = (row.get(col_map.get("last_name", ""), "") or "").strip()
        email = (row.get(col_map.get("email", ""), "") or "").strip().lower()
        password = (row.get(col_map.get("password", ""), "") or "").strip()

        if not email:
            errors.append({"row": i, "email": email, "error": "email is required"})
            continue
        if not first:
            errors.append({"row": i, "email": email, "error": "first_name is required"})
            continue
        if len(password) < 8:
            errors.append({"row": i, "email": email, "error": "password must be at least 8 characters"})
            continue

        try:
            user = await UserService.create_user(
                db,
                tenant_id=current_user.tenant_id,
                data={
                    "first_name": first,
                    "last_name": last,
                    "email": email,
                    "username": email,
                    "password": password,
                    "send_invite": False,
                },
                role_codes=["employee"],
                assigned_by=current_user.id,
            )
            created.append({"row": i, "email": email, "user_id": user.id})
        except Exception as exc:
            # Catch duplicates, validation errors, etc.
            detail = str(exc)
            if "uq_tenant_email" in detail or "uq_tenant_username" in detail:
                detail = "email already exists"
            errors.append({"row": i, "email": email, "error": detail})

    if created:
        await db.commit()

    return {
        "created": len(created),
        "errors": len(errors),
        "created_rows": created,
        "error_rows": errors,
    }
