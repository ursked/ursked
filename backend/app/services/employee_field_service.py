"""Company-defined employee fields: definitions, validation, visibility, values.

Visibility is enforced here, on every read and write, not in the UI: a caller
never receives a value they may not see, and a field they may not edit is
refused rather than ignored. See models/employee_field.py for what each
visibility level means.

For the report builder (area R), two entry points with stable signatures:

    custom_field_columns(db, tenant_id) -> [{key, label, type, ...}]
    custom_field_values(db, tenant_id, user_ids, viewer) -> {user_id: {key: value}}
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Optional, Set

from fastapi import HTTPException
from sqlalchemy import and_, delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.employee_field import (
    FIELD_TYPES,
    VISIBILITIES,
    EmployeeFieldDefinition,
    EmployeeFieldValue,
)
from app.models.user import User
from app.services import employee_access

KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,49}$")
MAX_VALUE_LENGTH = 500
MAX_OPTIONS = 200
MAX_OPTION_LENGTH = 100
MAX_REGEX_LENGTH = 200
MAX_FIELDS_PER_TENANT = 100

# Keys that would collide with built-in employee columns in the CSV import and
# the API payload. A company cannot define a custom "email".
RESERVED_KEYS = {
    "id", "tenant_id", "first_name", "middle_name", "last_name", "name", "email",
    "username", "password", "personnel_number", "employee_number", "employee_type",
    "schedule_format", "job_title", "hiring_date", "contact_number", "org_unit",
    "org_node_id", "reports_to", "reports_to_id", "roles", "role_codes", "typecode",
    "id_number", "rank", "is_active", "status", "custom_fields",
}

VISIBILITY_LABELS = {
    "hr_only": "HR only",
    "managers": "HR and the employee's managers",
    "employee_view": "Also the employee (read-only)",
    "employee_edit": "Also the employee, who can edit it",
}


class FieldValidationError(HTTPException):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(status_code=status_code, detail=message)


# ── Who is asking ────────────────────────────────────────────────────


@dataclass
class ViewerAccess:
    user: User
    hr_level: bool
    can_view: bool
    can_edit: bool
    read_scope: Optional[Set[int]]  # None = everyone
    edit_scope: Optional[Set[int]]

    def reads(self, target_id: int) -> bool:
        return self.can_view and (self.read_scope is None or target_id in self.read_scope)

    def edits(self, target_id: int) -> bool:
        return self.can_edit and (self.edit_scope is None or target_id in self.edit_scope)


async def viewer_access(db: AsyncSession, viewer: User) -> ViewerAccess:
    from app.services import access_scope

    can_view = await employee_access.has_permission(db, viewer, "employees", "view")
    can_edit = await employee_access.has_permission(db, viewer, "employees", "edit")
    scope = await access_scope.managed_employee_ids(db, viewer, "employees")
    return ViewerAccess(
        user=viewer,
        hr_level=await employee_access.is_hr_level(db, viewer),
        can_view=can_view,
        can_edit=can_edit,
        read_scope=scope,
        edit_scope=scope,
    )


def _levels(access: ViewerAccess, target_id: int) -> Set[str]:
    if access.hr_level:
        return set(VISIBILITIES)
    levels: Set[str] = set()
    if target_id != access.user.id and access.reads(target_id):
        levels |= {"managers", "employee_view", "employee_edit"}
    if target_id == access.user.id:
        levels |= {"employee_view", "employee_edit"}
        # A manager reading their own record through the directory sees the
        # same as anyone reading it, never less.
        if access.can_view:
            levels |= {"managers"}
    return levels


def can_see(defn: EmployeeFieldDefinition, access: ViewerAccess, target_id: int, *, listing: bool = False) -> bool:
    if defn.visibility not in _levels(access, target_id):
        return False
    if listing and defn.is_sensitive and not access.hr_level:
        return False
    return True


def can_edit(defn: EmployeeFieldDefinition, access: ViewerAccess, target_id: int) -> bool:
    if defn.is_archived:
        return False
    if access.edits(target_id) and can_see(defn, access, target_id):
        return True
    return target_id == access.user.id and defn.visibility == "employee_edit"


def definition_visible_to(defn: EmployeeFieldDefinition, access: ViewerAccess) -> bool:
    """Could this viewer see this field for SOMEONE? Decides which definitions
    a form or a table header is built from."""
    if access.hr_level:
        return True
    if access.can_view and defn.visibility != "hr_only":
        return True
    return defn.visibility in ("employee_view", "employee_edit")


# ── Definitions ──────────────────────────────────────────────────────


async def list_definitions(
    db: AsyncSession, tenant_id, *, include_archived: bool = False
) -> List[EmployeeFieldDefinition]:
    stmt = select(EmployeeFieldDefinition).where(EmployeeFieldDefinition.tenant_id == tenant_id)
    if not include_archived:
        stmt = stmt.where(EmployeeFieldDefinition.is_archived == False)  # noqa: E712
    stmt = stmt.order_by(EmployeeFieldDefinition.sort_order, EmployeeFieldDefinition.id)
    return list((await db.execute(stmt)).scalars().all())


def _clean_options(options: Any) -> List[str]:
    if options is None:
        return []
    if not isinstance(options, list):
        raise FieldValidationError("Options must be a list.")
    seen, out = set(), []
    for raw in options:
        opt = str(raw).strip()
        if not opt:
            continue
        if len(opt) > MAX_OPTION_LENGTH:
            raise FieldValidationError(f"Option '{opt[:20]}…' is longer than {MAX_OPTION_LENGTH} characters.")
        if opt.lower() in seen:
            raise FieldValidationError(f"Option '{opt}' is listed twice.")
        seen.add(opt.lower())
        out.append(opt)
    if len(out) > MAX_OPTIONS:
        raise FieldValidationError(f"A list can have at most {MAX_OPTIONS} options.")
    return out


def _clean_regex(regex: Optional[str]) -> Optional[str]:
    if regex is None or not str(regex).strip():
        return None
    regex = str(regex).strip()
    if len(regex) > MAX_REGEX_LENGTH:
        raise FieldValidationError(f"The format pattern can be at most {MAX_REGEX_LENGTH} characters.")
    try:
        re.compile(regex)
    except re.error as exc:
        raise FieldValidationError(f"The format pattern is not valid: {exc}.")
    return regex


def validate_definition(data: Dict[str, Any], *, existing: Optional[EmployeeFieldDefinition] = None) -> Dict[str, Any]:
    """Check and normalise a create/update payload. Returns the cleaned dict."""
    out = dict(data)
    if existing is None:
        key = str(out.get("key") or "").strip().lower()
        if not KEY_RE.match(key):
            raise FieldValidationError(
                "The key must start with a letter and use only lowercase letters, digits and underscores (max 50)."
            )
        if key in RESERVED_KEYS:
            raise FieldValidationError(f"'{key}' is a built-in employee field; choose another key.")
        out["key"] = key
    elif "key" in out and out["key"] != existing.key:
        raise FieldValidationError("A field's key cannot be changed once created; change its label instead.")

    if "label" in out or existing is None:
        label = str(out.get("label") or "").strip()
        if not label:
            raise FieldValidationError("The field needs a label.")
        out["label"] = label[:100]

    ftype = out.get("field_type", existing.field_type if existing else "text")
    if ftype not in FIELD_TYPES:
        raise FieldValidationError(f"Field type must be one of: {', '.join(FIELD_TYPES)}.")
    out["field_type"] = ftype

    if "visibility" in out and out["visibility"] not in VISIBILITIES:
        raise FieldValidationError(f"Visibility must be one of: {', '.join(VISIBILITIES)}.")

    if "options" in out or (existing is None and ftype == "select"):
        out["options"] = _clean_options(out.get("options")) if ftype == "select" else None
    if ftype == "select":
        opts = out.get("options", existing.options if existing else None) or []
        if not opts:
            raise FieldValidationError("A list field needs at least one option.")

    if "regex" in out:
        out["regex"] = _clean_regex(out["regex"])
    if out.get("regex") and ftype != "text":
        raise FieldValidationError("A format pattern can only be set on a text field.")
    if out.get("is_unique") and ftype == "boolean":
        raise FieldValidationError("A yes/no field cannot be unique.")
    return out


async def _value_count(db: AsyncSession, field_id: int) -> int:
    return (
        await db.execute(
            select(func.count(EmployeeFieldValue.id)).where(EmployeeFieldValue.field_id == field_id)
        )
    ).scalar() or 0


async def create_definition(db: AsyncSession, tenant_id, data: Dict[str, Any], actor_id: Optional[int]) -> EmployeeFieldDefinition:
    data = validate_definition(data)
    existing = (
        await db.execute(
            select(EmployeeFieldDefinition).where(
                EmployeeFieldDefinition.tenant_id == tenant_id,
                EmployeeFieldDefinition.key == data["key"],
            )
        )
    ).scalar_one_or_none()
    if existing:
        raise FieldValidationError(
            f"A field with the key '{data['key']}' already exists"
            + (" (archived; restore it instead)." if existing.is_archived else ".")
        )
    count = (
        await db.execute(
            select(func.count(EmployeeFieldDefinition.id)).where(EmployeeFieldDefinition.tenant_id == tenant_id)
        )
    ).scalar() or 0
    if count >= MAX_FIELDS_PER_TENANT:
        raise FieldValidationError(f"A company can define at most {MAX_FIELDS_PER_TENANT} custom fields.")
    max_order = (
        await db.execute(
            select(func.max(EmployeeFieldDefinition.sort_order)).where(EmployeeFieldDefinition.tenant_id == tenant_id)
        )
    ).scalar()
    defn = EmployeeFieldDefinition(
        tenant_id=tenant_id,
        key=data["key"],
        label=data["label"],
        field_type=data["field_type"],
        options=data.get("options"),
        is_required=bool(data.get("is_required", False)),
        is_unique=bool(data.get("is_unique", False)),
        regex=data.get("regex"),
        visibility=data.get("visibility") or "hr_only",
        is_sensitive=bool(data.get("is_sensitive", False)),
        help_text=(data.get("help_text") or None),
        sort_order=(max_order + 1) if max_order is not None else 0,
        created_by=actor_id,
    )
    db.add(defn)
    await db.flush()
    return defn


DEFINITION_AUDIT_FIELDS = (
    "label", "field_type", "options", "is_required", "is_unique", "regex",
    "visibility", "is_sensitive", "help_text", "is_archived",
)


async def update_definition(db: AsyncSession, defn: EmployeeFieldDefinition, data: Dict[str, Any]) -> EmployeeFieldDefinition:
    # Serialise with value writers (see the model's comment on is_unique).
    await db.execute(
        select(EmployeeFieldDefinition.id).where(EmployeeFieldDefinition.id == defn.id).with_for_update()
    )
    data = validate_definition(data, existing=defn)
    in_use = await _value_count(db, defn.id)

    if data.get("field_type", defn.field_type) != defn.field_type and in_use:
        raise FieldValidationError(
            f"{defn.label} already has values for {in_use} employee(s), so its type cannot change. "
            "Archive it and create a new field instead."
        )

    if "options" in data and defn.field_type == "select" and data["options"] is not None:
        keep = {o.lower() for o in data["options"]}
        used = (
            await db.execute(
                select(EmployeeFieldValue.value_norm, func.count(EmployeeFieldValue.id))
                .where(EmployeeFieldValue.field_id == defn.id)
                .group_by(EmployeeFieldValue.value_norm)
            )
        ).all()
        dropped = [(v, n) for v, n in used if v and v not in keep]
        if dropped:
            v, n = dropped[0]
            raise FieldValidationError(
                f"The option '{v}' is used by {n} employee(s). Change their value before removing it."
            )

    turning_unique_on = data.get("is_unique") is True and not defn.is_unique
    if turning_unique_on:
        dupes = (
            await db.execute(
                select(EmployeeFieldValue.value_norm, func.count(EmployeeFieldValue.id))
                .where(EmployeeFieldValue.field_id == defn.id, EmployeeFieldValue.value_norm.isnot(None))
                .group_by(EmployeeFieldValue.value_norm)
                .having(func.count(EmployeeFieldValue.id) > 1)
            )
        ).all()
        if dupes:
            sample = ", ".join(f"'{v}'" for v, _ in dupes[:3])
            raise FieldValidationError(
                f"{defn.label} cannot be made unique: {len(dupes)} value(s) are shared by more than one "
                f"employee ({sample}). Fix those first."
            )

    for key in ("label", "field_type", "options", "is_required", "is_unique", "regex", "visibility", "is_sensitive", "help_text", "is_archived"):
        if key in data:
            setattr(defn, key, data[key])
    if defn.field_type != "select":
        defn.options = None

    if "is_unique" in data:
        try:
            async with db.begin_nested():
                await db.execute(
                    update(EmployeeFieldValue)
                    .where(EmployeeFieldValue.field_id == defn.id)
                    .values(is_unique=bool(defn.is_unique))
                )
        except IntegrityError:
            raise FieldValidationError(
                f"{defn.label} cannot be made unique: another change just saved a duplicate value. Try again."
            )
    await db.flush()
    return defn


async def archive_or_delete(db: AsyncSession, defn: EmployeeFieldDefinition) -> str:
    """Delete a field nobody has filled in; archive one that holds data, so no
    employee's information is lost by tidying the list."""
    if await _value_count(db, defn.id):
        defn.is_archived = True
        await db.flush()
        return "archived"
    await db.delete(defn)
    await db.flush()
    return "deleted"


async def reorder(db: AsyncSession, tenant_id, ids: List[int]) -> None:
    defs = {d.id: d for d in await list_definitions(db, tenant_id, include_archived=True)}
    unknown = [i for i in ids if i not in defs]
    if unknown:
        raise FieldValidationError("The list refers to a field that does not exist.", status_code=404)
    for pos, fid in enumerate(ids):
        defs[fid].sort_order = pos
    # Anything the caller did not mention keeps its relative order, after.
    rest = [d for d in sorted(defs.values(), key=lambda d: (d.sort_order, d.id)) if d.id not in ids]
    for pos, d in enumerate(rest, start=len(ids)):
        d.sort_order = pos
    await db.flush()


def definition_dict(defn: EmployeeFieldDefinition) -> Dict[str, Any]:
    return {
        "id": defn.id,
        "key": defn.key,
        "label": defn.label,
        "field_type": defn.field_type,
        "options": defn.options or [],
        "is_required": bool(defn.is_required),
        "is_unique": bool(defn.is_unique),
        "regex": defn.regex,
        "visibility": defn.visibility,
        "is_sensitive": bool(defn.is_sensitive),
        "help_text": defn.help_text,
        "sort_order": defn.sort_order,
        "is_archived": bool(defn.is_archived),
    }


# ── Values ───────────────────────────────────────────────────────────

_TRUE = {"true", "yes", "y", "1", "on"}
_FALSE = {"false", "no", "n", "0", "off"}
_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%Y/%m/%d")


def coerce(defn: EmployeeFieldDefinition, raw: Any) -> Optional[tuple]:
    """(value_text, value_norm) for storage, or None to clear. Raises
    FieldValidationError with a sentence naming the field."""
    label = defn.label
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    t = defn.field_type
    if t == "text":
        v = str(raw).strip()
        if len(v) > MAX_VALUE_LENGTH:
            raise FieldValidationError(f"{label} can be at most {MAX_VALUE_LENGTH} characters.")
        if defn.regex:
            try:
                ok = re.fullmatch(defn.regex, v) is not None
            except re.error:
                ok = True  # a pattern that no longer compiles never blocks data entry
            if not ok:
                raise FieldValidationError(f"{label} '{v}' is not in the required format.")
        return v, v.lower()
    if t == "number":
        if isinstance(raw, bool):
            raise FieldValidationError(f"{label} must be a number.")
        try:
            num = Decimal(str(raw).strip().replace(",", ""))
        except InvalidOperation:
            raise FieldValidationError(f"{label} must be a number.")
        if not num.is_finite():
            raise FieldValidationError(f"{label} must be a number.")
        text = str(num.quantize(Decimal(1))) if num == num.to_integral_value() else format(num.normalize(), "f")
        return text, text
    if t == "date":
        if isinstance(raw, datetime):
            d = raw.date()
        elif isinstance(raw, date):
            d = raw
        else:
            s = str(raw).strip()
            d = None
            for fmt in _DATE_FORMATS:
                try:
                    d = datetime.strptime(s, fmt).date()
                    break
                except ValueError:
                    continue
            if d is None:
                raise FieldValidationError(f"{label} must be a date (YYYY-MM-DD).")
        return d.isoformat(), d.isoformat()
    if t == "boolean":
        if isinstance(raw, bool):
            b = raw
        else:
            s = str(raw).strip().lower()
            if s in _TRUE:
                b = True
            elif s in _FALSE:
                b = False
            else:
                raise FieldValidationError(f"{label} must be yes or no.")
        text = "true" if b else "false"
        return text, text
    if t == "select":
        s = str(raw).strip()
        for opt in defn.options or []:
            if opt.lower() == s.lower():
                return opt, opt.lower()
        raise FieldValidationError(
            f"{label} must be one of: {', '.join((defn.options or [])[:10])}"
            + ("…" if len(defn.options or []) > 10 else "") + "."
        )
    raise FieldValidationError(f"{label} has an unknown type.")


def to_api(defn: EmployeeFieldDefinition, value_text: Optional[str]) -> Any:
    if value_text is None:
        return None
    if defn.field_type == "number":
        try:
            d = Decimal(value_text)
            return int(d) if d == d.to_integral_value() else float(d)
        except InvalidOperation:
            return value_text
    if defn.field_type == "boolean":
        return value_text == "true"
    return value_text


async def values_for(
    db: AsyncSession,
    tenant_id,
    user_ids: Iterable[int],
    access: Optional[ViewerAccess],
    *,
    listing: bool = False,
    definitions: Optional[List[EmployeeFieldDefinition]] = None,
) -> Dict[int, Dict[str, Any]]:
    """{user_id: {key: value}} containing only what `access` may see.

    Archived fields are omitted. With listing=True, sensitive fields are
    omitted too unless the viewer is HR-level (tables, search results, reports).
    """
    ids = [i for i in set(user_ids) if i is not None]
    out: Dict[int, Dict[str, Any]] = {i: {} for i in ids}
    if not ids or access is None:
        return out
    defs = definitions if definitions is not None else await list_definitions(db, tenant_id)
    defs_by_id = {d.id: d for d in defs if not d.is_archived}
    if not defs_by_id:
        return out
    rows = (
        await db.execute(
            select(EmployeeFieldValue.user_id, EmployeeFieldValue.field_id, EmployeeFieldValue.value_text).where(
                EmployeeFieldValue.tenant_id == tenant_id,
                EmployeeFieldValue.user_id.in_(ids),
                EmployeeFieldValue.field_id.in_(list(defs_by_id)),
            )
        )
    ).all()
    for user_id, field_id, value_text in rows:
        d = defs_by_id[field_id]
        if can_see(d, access, user_id, listing=listing):
            out[user_id][d.key] = to_api(d, value_text)
    return out


async def set_values(
    db: AsyncSession,
    *,
    tenant_id,
    target: User,
    values: Dict[str, Any],
    access: ViewerAccess,
    creating: bool = False,
) -> Dict[str, Dict[str, Any]]:
    """Validate and write `values` ({key: value}; null clears) for `target`.

    All-or-nothing: every problem is reported in one readable message and
    nothing is written unless everything is valid. Returns the audit diff
    ({key: {"from", "to"}}, sensitive values masked).
    """
    values = values or {}
    defs = {d.key: d for d in await list_definitions(db, tenant_id, include_archived=True)}
    errors: List[str] = []
    forbidden: List[str] = []
    planned: Dict[int, Optional[tuple]] = {}

    for key, raw in values.items():
        d = defs.get(key)
        if d is None or (d.is_archived and raw is not None):
            errors.append(f"There is no custom field called '{key}'.")
            continue
        if d.is_archived:
            continue
        if not can_edit(d, access, target.id):
            forbidden.append(d.label)
            continue
        try:
            coerced = coerce(d, raw)
        except FieldValidationError as exc:
            errors.append(exc.detail)
            continue
        if coerced is None and d.is_required:
            errors.append(f"{d.label} is required.")
            continue
        planned[d.id] = coerced

    if creating:
        for d in defs.values():
            if d.is_required and not d.is_archived and d.key not in values and can_edit(d, access, target.id):
                errors.append(f"{d.label} is required.")

    if forbidden:
        raise FieldValidationError(f"You cannot change: {', '.join(forbidden)}.", status_code=403)
    if errors:
        raise FieldValidationError(" ".join(errors))
    if not planned:
        return {}

    by_id = {d.id: d for d in defs.values()}
    # FOR SHARE on the definitions: a concurrent "make unique" waits for us or
    # we wait for it, so the is_unique copy below is never stale.
    await db.execute(
        select(EmployeeFieldDefinition.id)
        .where(EmployeeFieldDefinition.id.in_(list(planned)))
        .with_for_update(read=True)
    )

    existing = {
        v.field_id: v
        for v in (
            await db.execute(
                select(EmployeeFieldValue).where(
                    EmployeeFieldValue.user_id == target.id,
                    EmployeeFieldValue.field_id.in_(list(planned)),
                )
            )
        ).scalars().all()
    }

    # Friendly pre-check; the unique index is what actually guarantees it.
    for fid, coerced in planned.items():
        d = by_id[fid]
        if coerced is None or not d.is_unique:
            continue
        clash = (
            await db.execute(
                select(EmployeeFieldValue.user_id).where(
                    EmployeeFieldValue.field_id == fid,
                    EmployeeFieldValue.value_norm == coerced[1],
                    EmployeeFieldValue.user_id != target.id,
                ).limit(1)
            )
        ).scalar()
        if clash is not None:
            errors.append(f"{d.label} '{coerced[0]}' is already used by another employee.")
    if errors:
        raise FieldValidationError(" ".join(errors))

    changes: Dict[str, Dict[str, Any]] = {}
    try:
        async with db.begin_nested():
            for fid, coerced in planned.items():
                d = by_id[fid]
                row = existing.get(fid)
                old = to_api(d, row.value_text) if row else None
                if coerced is None:
                    if row is not None:
                        await db.delete(row)
                else:
                    if row is None:
                        row = EmployeeFieldValue(tenant_id=tenant_id, field_id=fid, user_id=target.id)
                        db.add(row)
                    row.value_text, row.value_norm = coerced
                    row.is_unique = bool(d.is_unique)
                    row.updated_by = access.user.id
                new = to_api(d, coerced[0]) if coerced else None
                if old != new:
                    changes[d.key] = (
                        {"from": "(hidden)", "to": "(hidden)"} if d.is_sensitive else {"from": old, "to": new}
                    )
            await db.flush()
    except IntegrityError:
        raise FieldValidationError("One of the values is already used by another employee (it must be unique).")
    return changes


# ── Directory search and filters ─────────────────────────────────────


async def searchable_field_ids(db: AsyncSession, tenant_id, access: ViewerAccess) -> List[int]:
    """Unique, non-sensitive fields the viewer may see: the ones the directory
    search box also matches (an employee code is how people look someone up)."""
    return [
        d.id
        for d in await list_definitions(db, tenant_id)
        if d.is_unique and not d.is_sensitive and definition_visible_to(d, access)
        and (access.hr_level or d.visibility != "hr_only")
    ]


async def filter_clauses(db: AsyncSession, tenant_id, access: ViewerAccess, filters: Dict[str, str]):
    """SQL conditions on User.id for `?cf_<key>=value` filters. Only select and
    unique fields may be filtered, and only ones the viewer may see, so a
    filter can never be used to discover a hidden value."""
    if not filters:
        return []
    defs = {d.key: d for d in await list_definitions(db, tenant_id)}
    clauses = []
    for key, raw in filters.items():
        d = defs.get(key)
        if d is None or not definition_visible_to(d, access) or (d.visibility == "hr_only" and not access.hr_level):
            raise FieldValidationError(f"You cannot filter on '{key}'.")
        if d.is_sensitive and not access.hr_level:
            raise FieldValidationError(f"You cannot filter on {d.label}.")
        if d.field_type != "select" and not d.is_unique:
            raise FieldValidationError(f"{d.label} is not a filterable field.")
        norm = str(raw).strip().lower()
        clauses.append(
            User.id.in_(
                select(EmployeeFieldValue.user_id).where(
                    and_(EmployeeFieldValue.field_id == d.id, EmployeeFieldValue.value_norm == norm)
                )
            )
        )
    return clauses


def search_clause(field_ids: List[int], like: str):
    return User.id.in_(
        select(EmployeeFieldValue.user_id).where(
            EmployeeFieldValue.field_id.in_(field_ids),
            EmployeeFieldValue.value_norm.like(like),
        )
    )


async def delete_values_for_user(db: AsyncSession, user_id: int) -> None:
    await db.execute(delete(EmployeeFieldValue).where(EmployeeFieldValue.user_id == user_id))


# ── Report builder hook (area R) ─────────────────────────────────────


async def custom_field_columns(db: AsyncSession, tenant_id) -> List[Dict[str, Any]]:
    """Active custom fields as report columns: [{key, label, type, options,
    visibility, is_sensitive}], in the company's display order. Values must be
    fetched with custom_field_values, which applies visibility per viewer."""
    return [
        {
            "key": d.key,
            "label": d.label,
            "type": d.field_type,
            "options": d.options or [],
            "visibility": d.visibility,
            "is_sensitive": bool(d.is_sensitive),
        }
        for d in await list_definitions(db, tenant_id)
    ]


async def custom_field_values(
    db: AsyncSession, tenant_id, user_ids: Iterable[int], viewer: Optional[User]
) -> Dict[int, Dict[str, Any]]:
    """{user_id: {key: value}} for the report builder, honouring visibility for
    `viewer` exactly as the employee directory does (sensitive fields only for
    HR-level viewers). viewer=None returns empty dicts: a report with no known
    audience gets no custom data rather than all of it."""
    ids = list(user_ids)
    if viewer is None:
        return {i: {} for i in ids}
    access = await viewer_access(db, viewer)
    return await values_for(db, tenant_id, ids, access, listing=True)
