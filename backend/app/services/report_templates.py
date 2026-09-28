"""Built-in reports, defined in code as ordinary report specs.

The client's "Regular Work Schedule" workbook used to exist only as a
hard-coded exporter (schedule_export_service), frozen and sharing no code with
the report builder: nobody could change it, copy it for another client, or see
how it was made. Here it is the same kind of object a user saves from the
builder, so it opens in the builder, reads as a list of steps, and can be
edited and saved under a new name.

They live in code, not as seeded rows, so a fix to the template reaches every
company on upgrade and nobody's saved copy is overwritten.
"""

from __future__ import annotations

import copy
from datetime import date
from typing import Any, Dict, Iterable, List, Optional, Set
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

_TIME = {"kind": "time", "pattern": "12h"}
_DATE = {"kind": "date", "pattern": "mdy"}

REGULAR_WORK_SCHEDULE: Dict[str, Any] = {
    "data_source": "schedules",
    "columns": [
        "employee_formal_name",
        "date",
        "date::2",
        "day_work_status",
        "start_time",
        "end_time",
        "unpaid_break_start",
        "unpaid_break_end",
        "paid_break_start",
        "paid_break_end",
        "export_remark",
    ],
    "custom_columns": [],
    "filters": [],
    "group_by": [],
    "aggregations": [],
    "column_aliases": {
        "employee_formal_name": "EMPLOYEE",
        "date": "FROM",
        "date::2": "TO",
        "day_work_status": "DWS",
        "start_time": "START",
        "end_time": "END",
        "unpaid_break_start": "START",
        "unpaid_break_end": "END",
        "paid_break_start": "START",
        "paid_break_end": "END",
        "export_remark": "REMARKS",
    },
    "column_formats": {
        "date": _DATE,
        "date::2": _DATE,
        "start_time": _TIME,
        "end_time": _TIME,
        "unpaid_break_start": _TIME,
        "unpaid_break_end": _TIME,
        "paid_break_start": _TIME,
        "paid_break_end": _TIME,
    },
    # No sort: with every day shown, the source already yields employees by
    # surname then each day in order, which is the order the form is read in.
    "sorts": [],
    "date_preset": "this_month",
    "date_from": None,
    "date_to": None,
    "output_format": "xlsx",
    "row_limit": None,
    "name_format": "first_last",
    "source_options": {"fill_calendar_days": True, "rest_day_label": "FREE"},
    "layout": {
        "heading_rows": [
            {"text": "Regular Work Schedule", "span": 10, "align": "left", "bold": True},
        ],
        "header_tiers": [[
            {"label": "WORK SCHEDULE (Dates)", "from": "date", "to": "date::2"},
            {"label": "WORK SCHEDULE\n(TIME)", "from": "start_time", "to": "end_time"},
            {"label": "1 HR UNPAID BREAK\n(9-HOUR SHIFT)", "from": "unpaid_break_start", "to": "unpaid_break_end"},
            {"label": "30 MIN PAID BREAK\n(8-HOUR SHIFT)", "from": "paid_break_start", "to": "paid_break_end"},
        ]],
        "blocks": {
            "by": "employee_formal_name",
            "blank_rows_between": 2,
            "repeat_value": "every_row",
            "sheet_per_group": False,
        },
        "sheet_name": "{date_from:%b %d} - {date_to:%d}",
        "style": "banded",
        "freeze_header": True,
    },
}

BUILTIN_REPORTS: Dict[str, Dict[str, Any]] = {
    "regular_work_schedule": {
        "name": "Regular Work Schedule",
        "description": (
            "The formal cutoff schedule: one block per employee, every day of the "
            "period with FROM and TO dates, shift times, break times and a REMARKS "
            "column with leave codes and HOL OFF. Excel dates and times throughout."
        ),
        "spec": REGULAR_WORK_SCHEDULE,
    },
}


def list_templates() -> List[Dict[str, Any]]:
    return [
        {"key": k, "name": v["name"], "description": v["description"], "spec": copy.deepcopy(v["spec"])}
        for k, v in BUILTIN_REPORTS.items()
    ]


def template_spec(key: str) -> Dict[str, Any]:
    if key not in BUILTIN_REPORTS:
        raise KeyError(key)
    return copy.deepcopy(BUILTIN_REPORTS[key]["spec"])


async def build_work_schedule_xlsx(
    db: AsyncSession,
    tenant_id: UUID,
    start_date: date,
    end_date: date,
    *,
    employee_scope: Optional[Iterable[int]] = None,
    viewer: Any = None,
    include_drafts: bool = False,
) -> bytes:
    """The Schedules page's "Export XLSX": the Regular Work Schedule template
    for one cutoff, limited to `employee_scope` (None = everyone)."""
    from app.services.data_export_service import DataExportService

    spec = template_spec("regular_work_schedule")
    spec["date_preset"] = "custom"
    spec["date_from"] = start_date.isoformat()
    spec["date_to"] = end_date.isoformat()
    if include_drafts:
        spec["source_options"]["include_drafts"] = True
    scope: Optional[Set[int]] = None if employee_scope is None else set(employee_scope)
    rows, _total, columns = await DataExportService.run_export(
        db, tenant_id, spec, viewer=viewer, employee_scope=scope
    )
    payload, _mime, _ext = DataExportService.serialise(
        rows,
        columns,
        "xlsx",
        BUILTIN_REPORTS["regular_work_schedule"]["name"],
        layout=spec["layout"],
        context={
            "report_name": BUILTIN_REPORTS["regular_work_schedule"]["name"],
            "date_from": spec["date_from"],
            "date_to": spec["date_to"],
        },
    )
    return payload
