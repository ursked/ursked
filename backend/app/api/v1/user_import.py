"""CSV employee import (Employees > Import).

There used to be two `POST /users/import-csv` handlers; the one in users.py was
registered first and shadowed this one, it took four columns, could only
create, and one duplicate row could fail the whole file (audit E-4). This is
now the only handler.

How it behaves:

  * Preview first. `?dry_run=true` runs every row exactly as a real import
    would, inside a savepoint that is then rolled back, and returns what WOULD
    happen per row (create / update / unchanged / error, with reasons). Rows
    that depend on earlier rows (a line manager created three lines up) preview
    correctly because the whole file runs in order.
  * One bad row never fails the batch: each row runs in its own savepoint.
  * Upsert: a row matches an existing employee by email, or by employee
    number when the email cell is empty. Blank cells leave existing values
    alone, so a file with just `email,job_title` updates job titles only.
  * Creating needs employees:create; updating needs employees:edit and the
    employee in your scope. Only an administrator can grant Administrator or
    touch an administrator's sign-in details, exactly as in the form.
  * No password column (or an empty cell) creates the employee as invited and
    emails the normal activation link, after the import commits.
  * Cells that a spreadsheet would run as a formula (=, @, or +/- followed by
    anything but a number) are refused, so an imported value can never become
    an injected formula when the data is exported again.
"""

import csv
import io
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware.auth import get_current_user
from app.models.configurable_types import EmployeeType, ScheduleFormat
from app.models.org_hierarchy import OrgNode
from app.models.role import Role
from app.models.user import User
from app.schemas.user import validate_password_strength
from app.services import audit_service, employee_access, employee_field_service as efs
from app.services import employee_record_service as records
from app.services.email_service import EmailService
from app.services.invite_service import InviteService
from app.services.user_service import UserService, normalize_email

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/users", tags=["Users"])

MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 2000

# Built-in columns in template order, with the header spellings accepted for
# each. Headers are compared lowercased with spaces, dashes and '#' folded to
# underscores, so "First Name" and "first-name" both work.
BUILTIN_COLUMNS: List[Tuple[str, Tuple[str, ...]]] = [
    ("first_name", ("first_name", "firstname", "given_name")),
    ("middle_name", ("middle_name", "middlename")),
    ("last_name", ("last_name", "lastname", "surname", "family_name")),
    ("email", ("email", "email_address", "e_mail")),
    ("username", ("username", "user_name")),
    ("personnel_number", ("personnel_number", "personnel_no", "personnel_", "employee_number", "employee_no")),
    ("employee_type", ("employee_type", "employment_type")),
    ("schedule_format", ("schedule_format",)),
    ("job_title", ("job_title", "title", "position")),
    ("hiring_date", ("hiring_date", "hire_date", "date_hired", "start_date")),
    ("contact_number", ("contact_number", "phone", "mobile", "contact")),
    ("org_unit", ("org_unit", "department", "unit", "organization_unit")),
    ("reports_to", ("reports_to", "line_manager", "manager")),
    ("roles", ("roles", "role")),
    ("typecode", ("typecode", "type_code")),
    ("id_number", ("id_number", "id_no")),
    ("rank", ("rank",)),
    ("password", ("password",)),
]
TEMPLATE_BUILTINS = [c for c, _ in BUILTIN_COLUMNS if c not in ("typecode", "id_number", "rank")]

_PLAIN_FIELDS = ("first_name", "middle_name", "last_name", "username", "job_title",
                 "contact_number", "typecode", "id_number", "rank")
_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%Y/%m/%d")
_NUMERIC_SIGNED = re.compile(r"^[+-][\d\s().-]*$")


def _norm_header(h: str) -> str:
    h = (h or "").strip().lower()
    h = re.sub(r"[\s\-#./]+", "_", h)
    return re.sub(r"_+", "_", h).strip("_") or h


def _formula_like(value: str) -> bool:
    if not value:
        return False
    if value[0] in "=@\t\r":
        return True
    return value[0] in "+-" and not _NUMERIC_SIGNED.match(value)


def _parse_date(value: str):
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Hiring date '{value}' is not a date (use YYYY-MM-DD).")


class _Lookups:
    """Name-or-code lookups for the reference columns, loaded once per file."""

    def __init__(self):
        self.types: Dict[str, str] = {}
        self.formats: Dict[str, str] = {}
        self.units: Dict[str, List[int]] = {}
        self.roles: Dict[str, str] = {}

    @classmethod
    async def load(cls, db: AsyncSession, tenant_id) -> "_Lookups":
        me = cls()
        for code, name in (await db.execute(
            select(EmployeeType.code, EmployeeType.name).where(
                EmployeeType.tenant_id == tenant_id, EmployeeType.is_active == True  # noqa: E712
            )
        )).all():
            me.types[code.lower()] = code
            me.types.setdefault(name.lower(), code)
        for code, name in (await db.execute(
            select(ScheduleFormat.code, ScheduleFormat.name).where(
                ScheduleFormat.tenant_id == tenant_id, ScheduleFormat.is_active == True  # noqa: E712
            )
        )).all():
            me.formats[code.lower()] = code
            me.formats.setdefault(name.lower(), code)
        for nid, name, code in (await db.execute(
            select(OrgNode.id, OrgNode.name, OrgNode.code).where(
                OrgNode.tenant_id == tenant_id, OrgNode.is_active == True  # noqa: E712
            )
        )).all():
            if code:
                me.units.setdefault(code.lower(), []).append(nid)
            me.units.setdefault(name.lower(), []).append(nid)
        for code, name in (await db.execute(
            select(Role.code, Role.name).where(Role.tenant_id == tenant_id, Role.is_active == True)  # noqa: E712
        )).all():
            me.roles[code.lower()] = code
            me.roles.setdefault(name.lower(), code)
        me.roles.setdefault("administrator", "tenant_admin")
        return me


async def _find_user(db: AsyncSession, tenant_id, *, email: Optional[str] = None, number: Optional[str] = None) -> Optional[User]:
    if email:
        u = await UserService.get_user_by_email(db, email, tenant_id)
    elif number:
        u = await UserService.get_user_by_personnel_number(db, number, tenant_id)
    else:
        return None
    return await UserService.get_user_by_id(db, u.id, tenant_id) if u else None


def _map_headers(fieldnames: List[str], label_norm: str, defs) -> Tuple[Dict[str, str], Dict[str, Any], List[str]]:
    """(builtin column -> header, custom header -> definition, ignored headers)."""
    alias = {}
    for col, spellings in BUILTIN_COLUMNS:
        for s in spellings:
            alias[s] = col
    if label_norm:
        alias.setdefault(label_norm, "personnel_number")
    by_key = {d.key: d for d in defs}
    by_label = {_norm_header(d.label): d for d in defs}
    builtins, custom, ignored = {}, {}, []
    for h in fieldnames:
        n = _norm_header(h)
        if n in alias and alias[n] not in builtins:
            builtins[alias[n]] = h
        elif n in by_key and h not in custom:
            custom[h] = by_key[n]
        elif n in by_label and h not in custom:
            custom[h] = by_label[n]
        elif h and h.strip():
            ignored.append(h)
    return builtins, custom, ignored


@router.get("/import-csv/template")
async def import_template(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """A CSV header row with the columns this company's import accepts,
    including the custom fields the caller may fill in."""
    await employee_access.require(db, current_user, "employees", "create")
    access = await records.creation_access(db, current_user)
    defs = [
        d for d in await efs.list_definitions(db, current_user.tenant_id)
        if efs.definition_visible_to(d, access) and (access.hr_level or d.visibility != "hr_only")
    ]
    buf = io.StringIO()
    csv.writer(buf).writerow(TEMPLATE_BUILTINS + [d.key for d in defs])
    return Response(
        content="﻿" + buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="employee-import-template.csv"'},
    )


@router.post("/import-csv")
async def import_csv(
    request: Request,
    file: UploadFile = File(...),
    dry_run: bool = Query(False, description="Preview only: validate every row and roll back"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = current_user.tenant_id
    can_create = await employee_access.has_permission(db, current_user, "employees", "create")
    can_edit = await employee_access.has_permission(db, current_user, "employees", "edit")
    if not can_create and not can_edit:
        raise HTTPException(status_code=403, detail="You do not have permission to add or edit employees.")

    if file.filename and not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="The file must be a .csv file.")
    raw = await file.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise HTTPException(status_code=400, detail="The file is larger than 2 MB. Split it into smaller files.")
    try:
        text = raw.decode("utf-8-sig")  # Excel's "CSV UTF-8" starts with a BOM
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=400,
            detail="The file is not UTF-8 text. In Excel, save it as \"CSV UTF-8 (Comma delimited)\".",
        )

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="The file is empty or has no header row.")
    try:
        rows = list(reader)
    except csv.Error as exc:
        raise HTTPException(status_code=400, detail=f"The file could not be read as CSV: {exc}.")
    if len(rows) > MAX_ROWS:
        raise HTTPException(status_code=400, detail=f"The file has {len(rows)} rows; the limit is {MAX_ROWS} per import.")

    label = await UserService.employee_number_label(db, tenant_id)
    defs = await efs.list_definitions(db, tenant_id)
    builtins, custom_cols, ignored = _map_headers(reader.fieldnames, _norm_header(label), defs)
    if "email" not in builtins and "personnel_number" not in builtins:
        raise HTTPException(
            status_code=400,
            detail=f"The file needs an 'email' column (or a '{label}' column to update existing employees).",
        )

    lookups = await _Lookups.load(db, tenant_id)
    create_access = await records.creation_access(db, current_user)
    edit_access = await efs.viewer_access(db, current_user)
    frontend_base = ""
    if not dry_run:
        from app.api.v1.auth import _frontend_base

        frontend_base = await _frontend_base(db, request)

    seen_email: Dict[str, int] = {}
    seen_number: Dict[str, int] = {}
    results: List[Dict[str, Any]] = []
    emails_to_send: list = []

    outer = await db.begin_nested()
    for index, row in enumerate(rows, start=2):  # row 1 is the header
        cells = {col: (row.get(h) or "").strip() for col, h in builtins.items()}
        cf_cells = {d.key: (row.get(h) or "").strip() for h, d in custom_cols.items()}
        if not any(cells.values()) and not any(cf_cells.values()):
            continue  # blank line
        email = normalize_email(cells.get("email")) or None
        number = cells.get("personnel_number") or None
        name = " ".join(p for p in (cells.get("first_name"), cells.get("last_name")) if p)
        result: Dict[str, Any] = {"row": index, "email": email, "name": name, "action": "error", "errors": [], "changes": []}
        results.append(result)

        try:
            bad = [col for col, v in list(cells.items()) + list(cf_cells.items()) if col != "password" and _formula_like(v)]
            if bad:
                raise ValueError(
                    f"{', '.join(bad)}: starts with a character spreadsheets treat as a formula (=, +, -, @)."
                )
            if email and email in seen_email:
                raise ValueError(f"This email also appears on row {seen_email[email]}.")
            if number and number.lower() in seen_number:
                raise ValueError(f"This {label} also appears on row {seen_number[number.lower()]}.")
            if email:
                seen_email[email] = index
            if number:
                seen_number[number.lower()] = index

            target = await _find_user(db, tenant_id, email=email, number=None if email else number)
            if target is None and not email:
                raise ValueError(f"No employee has {label} {number}, and there is no email to create one.")

            data: Dict[str, Any] = {k: cells[k] for k in _PLAIN_FIELDS if cells.get(k)}
            if email and target is None:
                data["email"] = email
            if number:
                data["personnel_number"] = number
            if cells.get("hiring_date"):
                data["hiring_date"] = _parse_date(cells["hiring_date"])
            if cells.get("employee_type"):
                code = lookups.types.get(cells["employee_type"].lower())
                if not code:
                    raise ValueError(f"Unknown employee type '{cells['employee_type']}'.")
                data["employee_type"] = code
            if cells.get("schedule_format"):
                code = lookups.formats.get(cells["schedule_format"].lower())
                if not code:
                    raise ValueError(f"Unknown schedule format '{cells['schedule_format']}'.")
                data["schedule_format"] = code
            if cells.get("org_unit"):
                matches = lookups.units.get(cells["org_unit"].lower(), [])
                if not matches:
                    raise ValueError(f"No organization unit is called '{cells['org_unit']}'.")
                if len(set(matches)) > 1:
                    raise ValueError(f"More than one unit is called '{cells['org_unit']}'; use its code.")
                data["org_node_id"] = matches[0]
            roles = None
            if cells.get("roles"):
                roles = []
                for part in re.split(r"[,;|]", cells["roles"]):
                    part = part.strip()
                    if not part:
                        continue
                    code = lookups.roles.get(part.lower()) or lookups.roles.get(_norm_header(part))
                    if not code:
                        raise ValueError(f"Unknown role '{part}'.")
                    roles.append(code)
            password = cells.get("password") or None
            if password:
                validate_password_strength(password)
            custom_values = {k: v for k, v in cf_cells.items() if v}

            async with db.begin_nested():
                if cells.get("reports_to"):
                    ref = cells["reports_to"]
                    mgr = await _find_user(db, tenant_id, email=normalize_email(ref)) if "@" in ref else \
                        await _find_user(db, tenant_id, number=ref)
                    if mgr is None:
                        raise ValueError(f"Line manager '{ref}' was not found (use their email or {label}).")
                    data["reports_to_id"] = mgr.id

                if target is None:
                    if not can_create:
                        raise HTTPException(status_code=403, detail="You do not have permission to add employees.")
                    missing = [c.replace("_", " ") for c in ("first_name", "last_name") if not data.get(c)]
                    if missing:
                        raise ValueError(f"A new employee needs: {', '.join(missing)}.")
                    data.setdefault("username", email)
                    await records.validate_fields(db, tenant_id, data)
                    records.assert_may_grant(current_user, roles or [])
                    await records.assert_roles_exist(db, tenant_id, set(roles or []) | {"employee"})
                    user = await UserService.create_user(
                        db, tenant_id=tenant_id, data={**data, "password": password},
                        role_codes=roles or ["employee"], assigned_by=current_user.id,
                    )
                    await efs.set_values(
                        db, tenant_id=tenant_id, target=user, values=custom_values,
                        access=create_access, creating=True,
                    )
                    if not password:
                        await InviteService.issue_and_email(
                            db, user=user, created_by=current_user.id, frontend_base=frontend_base,
                            defer=emails_to_send,
                        )
                    result.update(action="create", user_id=user.id, invited=not password)
                else:
                    if not can_edit:
                        raise HTTPException(status_code=403, detail="You do not have permission to edit employees.")
                    await employee_access.assert_manages(db, current_user, [target.id])
                    if password:
                        raise ValueError("Passwords can only be set for new employees; existing employees keep theirs.")
                    changing_sign_in = {
                        k for k in ("username",) if k in data and data[k].lower() != (target.username or "").lower()
                    }
                    employee_access.assert_may_change_sign_in(current_user, target, changing_sign_in)
                    await records.validate_fields(db, tenant_id, data, target=target)
                    before = audit_service.snapshot_user(target)
                    roles_before = roles_after = sorted(target.role_codes)
                    if roles is not None:
                        roles_before, roles_after = await records.set_roles(db, current_user, target, roles)
                    cf_changes = await efs.set_values(
                        db, tenant_id=tenant_id, target=target, values=custom_values, access=edit_access,
                    )
                    await UserService.update_user(db, target, data, assigned_by=current_user.id)
                    changes = list(audit_service.diff(before, audit_service.snapshot_user(target)).keys())
                    changes += [f"custom:{k}" for k in cf_changes]
                    if roles_before != roles_after:
                        changes.append("roles")
                    result.update(
                        action="update" if changes else "unchanged",
                        user_id=target.id,
                        changes=changes,
                        name=name or audit_service.user_label(target),
                        email=target.email,
                    )
        except HTTPException as exc:
            result["errors"].append(str(exc.detail))
        except IntegrityError as exc:
            result["errors"].append(
                "Another employee already has one of these values." if "unique" in str(exc).lower()
                else "The row conflicts with an existing employee."
            )
        except ValueError as exc:
            result["errors"].append(str(exc))

    counts = {a: sum(1 for r in results if r["action"] == a) for a in ("create", "update", "unchanged", "error")}
    if dry_run:
        await outer.rollback()
    else:
        await outer.commit()
        audit_service.record(
            db, actor=current_user, action="users_import", resource_type="user", request=request,
            details={
                "filename": file.filename,
                "rows": len(results),
                "created": counts["create"],
                "updated": counts["update"],
                "unchanged": counts["unchanged"],
                "failed": counts["error"],
                "created_ids": [r["user_id"] for r in results if r["action"] == "create"],
                "updated_ids": [r["user_id"] for r in results if r["action"] == "update"],
            },
        )
        await db.commit()
        for job in emails_to_send:
            EmailService.fire_and_forget(job)

    return {
        "dry_run": dry_run,
        "total": len(results),
        "created": counts["create"],
        "updated": counts["update"],
        "unchanged": counts["unchanged"],
        "failed": counts["error"],
        "ignored_columns": ignored,
        "columns": list(builtins.keys()) + [d.key for d in custom_cols.values()],
        "rows": results,
    }

