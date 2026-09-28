import re
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.services.export_pipeline import (
    AGGREGATE_FUNCTIONS,
    FILTER_OPERATORS,
    INSTANCE_SEP,
    MAX_BLANK_ROWS,
    layout_problems,
    output_keys_for,
)


# ── Data source metadata (returned by GET /sources) ──────────────

class DataSourceColumn(BaseModel):
    key: str
    label: str
    type: str  # string, number, date, time, datetime
    is_salary: bool = False
    is_custom: bool = False


class DataSourceOption(BaseModel):
    key: str
    label: str
    type: str  # boolean, string, choice
    default: Any = None
    help: Optional[str] = None
    choices: List[Dict[str, str]] = []


class DataSourceInfo(BaseModel):
    key: str
    label: str
    description: str
    is_salary: bool = False
    columns: List[DataSourceColumn]
    options: List[DataSourceOption] = []


# ── Custom column ────────────────────────────────────────────────

class CustomColumnSchema(BaseModel):
    name: str
    formula: str

    @field_validator("name")
    @classmethod
    def no_instance_separator(cls, v: str) -> str:
        # "::" marks a repeated column ("date::2"). A calculated column called
        # "x::2" would be indistinguishable from the second copy of "x".
        if INSTANCE_SEP in v:
            raise ValueError("A calculated column's name cannot contain “::”.")
        if not v.strip():
            raise ValueError("Give the calculated column a name.")
        return v


# ── Filter condition ─────────────────────────────────────────────

class FilterCondition(BaseModel):
    column: str
    operator: str
    value: Any = None

    @field_validator("operator")
    @classmethod
    def known_operator(cls, v: str) -> str:
        # An unvalidated operator used to be accepted on save and then fall
        # through to "match everything" at export time, so a typo silently
        # removed the filter rather than reporting it.
        if v not in FILTER_OPERATORS:
            raise ValueError(
                f"Unknown filter operator '{v}'. Valid: {', '.join(sorted(FILTER_OPERATORS))}"
            )
        return v


class AggregationSpec(BaseModel):
    """One generated column, e.g. total overtime within each group."""
    column: str = ""
    func: str
    label: Optional[str] = None
    output_key: Optional[str] = None

    @field_validator("func")
    @classmethod
    def known_func(cls, v: str) -> str:
        if v not in AGGREGATE_FUNCTIONS:
            raise ValueError(
                f"Unknown aggregate '{v}'. Valid: {', '.join(sorted(AGGREGATE_FUNCTIONS))}"
            )
        return v


class SortSpec(BaseModel):
    column: str
    direction: str = "asc"

    @field_validator("direction")
    @classmethod
    def known_direction(cls, v: str) -> str:
        if v.lower() not in ("asc", "desc"):
            raise ValueError("Sort direction must be 'asc' or 'desc'")
        return v.lower()


class ColumnFormat(BaseModel):
    """How one column is rendered. `kind` picks which other fields apply."""
    kind: str  # number | date | time | text
    pattern: Optional[str] = None      # date/time
    decimals: Optional[int] = None     # number
    thousands: Optional[bool] = None   # number
    prefix: Optional[str] = None       # number
    suffix: Optional[str] = None       # number
    transform: Optional[str] = None    # text


# ── Page layout ──────────────────────────────────────────────────
# What each field means is documented once, in export_pipeline ("Layout").

class HeadingRow(BaseModel):
    text: str = Field(max_length=200)
    span: Optional[int] = Field(default=None, ge=1, le=200)
    align: Literal["left", "center", "right"] = "left"
    bold: bool = True


class HeaderBand(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    label: str = Field(max_length=120)
    from_: str = Field(alias="from")
    to: str

    @field_validator("label")
    @classmethod
    def has_label(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("A heading over columns needs some text.")
        return v


class BlockSpec(BaseModel):
    by: str
    blank_rows_between: int = Field(default=1, ge=0, le=MAX_BLANK_ROWS)
    repeat_value: Literal["every_row", "first_row"] = "every_row"
    sheet_per_group: bool = False


class LayoutSpec(BaseModel):
    heading_rows: List[HeadingRow] = Field(default_factory=list, max_length=5)
    header_tiers: List[List[HeaderBand]] = Field(default_factory=list, max_length=3)
    blocks: Optional[BlockSpec] = None
    sheet_name: Optional[str] = Field(default=None, max_length=100)
    # Deliberately two values: this is a layout engine, not a spreadsheet editor.
    style: Literal["plain", "banded"] = "plain"
    freeze_header: bool = True


_SOURCE_OPTIONS_LIMIT = 20


def _check_layout(values: Any) -> Any:
    """Fail loudly at save, never silently at render: a band naming a column
    the report does not have, running backwards, or overlapping another."""
    layout = getattr(values, "layout", None)
    if layout is None:
        return values
    spec = {
        "columns": getattr(values, "columns", None) or [],
        "custom_columns": getattr(values, "custom_columns", None) or [],
        "group_by": getattr(values, "group_by", None) or [],
        "aggregations": [a.model_dump() for a in (getattr(values, "aggregations", None) or [])],
    }
    problem = layout_problems(layout, output_keys_for(spec), getattr(values, "column_aliases", None) or {})
    if problem:
        raise ValueError(problem)
    return values


def _check_options(v: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if v is not None and len(v) > _SOURCE_OPTIONS_LIMIT:
        raise ValueError("Too many data options.")
    return v


# ── Config CRUD schemas ─────────────────────────────────────────

class DataExportConfigCreate(BaseModel):
    name: str
    description: Optional[str] = None
    data_source: str
    columns: List[str]
    custom_columns: List[CustomColumnSchema] = []
    filters: Optional[List[FilterCondition]] = None
    sort_by: Optional[str] = None
    sort_direction: Optional[str] = None
    name_format: Optional[str] = None
    group_by: List[str] = []
    aggregations: List[AggregationSpec] = []
    column_aliases: Dict[str, str] = {}
    column_formats: Dict[str, ColumnFormat] = {}
    sorts: List[SortSpec] = []
    date_preset: Optional[str] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    output_format: str = "csv"
    row_limit: Optional[int] = None
    layout: Optional[LayoutSpec] = None
    source_options: Dict[str, Any] = {}

    @field_validator("source_options")
    @classmethod
    def few_options(cls, v):
        return _check_options(v)

    @model_validator(mode="after")
    def layout_fits_columns(self):
        return _check_layout(self)


class DataExportConfigUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    data_source: Optional[str] = None
    columns: Optional[List[str]] = None
    custom_columns: Optional[List[CustomColumnSchema]] = None
    filters: Optional[List[FilterCondition]] = None
    sort_by: Optional[str] = None
    sort_direction: Optional[str] = None
    name_format: Optional[str] = None
    group_by: Optional[List[str]] = None
    aggregations: Optional[List[AggregationSpec]] = None
    column_aliases: Optional[Dict[str, str]] = None
    column_formats: Optional[Dict[str, ColumnFormat]] = None
    sorts: Optional[List[SortSpec]] = None
    date_preset: Optional[str] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    output_format: Optional[str] = None
    row_limit: Optional[int] = None
    # Explicit null clears the layout; leaving it out keeps it. The merged
    # result is checked in the service, since this is only part of the report.
    layout: Optional[LayoutSpec] = None
    source_options: Optional[Dict[str, Any]] = None

    @field_validator("source_options")
    @classmethod
    def few_options(cls, v):
        return _check_options(v)


class DataExportConfigResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: str
    name: str
    description: Optional[str] = None
    data_source: str
    columns: List[str]
    custom_columns: List[Dict[str, str]] = []
    filters: Optional[List[Dict[str, Any]]] = None
    sort_by: Optional[str] = None
    sort_direction: Optional[str] = None
    name_format: Optional[str] = None
    group_by: List[str] = []
    aggregations: List[Dict[str, Any]] = []
    column_aliases: Dict[str, str] = {}
    column_formats: Dict[str, Dict[str, Any]] = {}
    sorts: List[Dict[str, Any]] = []
    date_preset: Optional[str] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    output_format: str = "csv"
    row_limit: Optional[int] = None
    layout: Optional[Dict[str, Any]] = None
    source_options: Dict[str, Any] = {}
    created_by: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ── Preview / Export request ─────────────────────────────────────

class DataExportRequest(BaseModel):
    data_source: str
    columns: List[str]
    custom_columns: List[CustomColumnSchema] = []
    filters: Optional[List[FilterCondition]] = None
    sort_by: Optional[str] = None
    sort_direction: Optional[str] = None
    name_format: Optional[str] = None
    group_by: List[str] = []
    aggregations: List[AggregationSpec] = []
    column_aliases: Dict[str, str] = {}
    column_formats: Dict[str, ColumnFormat] = {}
    sorts: List[SortSpec] = []
    date_preset: Optional[str] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    output_format: str = "csv"
    row_limit: Optional[int] = None
    layout: Optional[LayoutSpec] = None
    source_options: Dict[str, Any] = {}
    # Fills the {report_name} token and names the downloaded file.
    report_name: Optional[str] = Field(default=None, max_length=200)
    # Preview only: how many rows to return. The total is reported separately so
    # the builder can say "showing 50 of 4,216" rather than leaving the user to
    # guess how much data they just described.
    limit: Optional[int] = None

    @field_validator("source_options")
    @classmethod
    def few_options(cls, v):
        return _check_options(v)

    @model_validator(mode="after")
    def layout_fits_columns(self):
        return _check_layout(self)


class PreviewColumn(BaseModel):
    key: str
    header: str
    type: Optional[str] = None


class PreviewResponse(BaseModel):
    columns: List[str]
    column_headers: List[PreviewColumn] = []
    rows: List[Dict[str, Any]] = []
    total: int
    returned: int = 0
    resolved_date_from: Optional[str] = None
    resolved_date_to: Optional[str] = None
    # The layout's headings with {tokens} filled in, and the worksheet names
    # the download will have, so the preview shows the page, not just the data.
    headings: List[str] = []
    sheet_names: List[str] = []


class ReportTemplate(BaseModel):
    key: str
    name: str
    description: str
    spec: Dict[str, Any]


# ── Scheduled export schemas ───────────────────────────────────

_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)(:[0-5]\d)?$")


def _valid_schedule(schedule_type: Optional[str], day: Optional[int]) -> Optional[str]:
    if schedule_type is None:
        return None
    if schedule_type not in ("daily", "weekly", "monthly"):
        return "How often must be every day, every week or every month."
    if schedule_type == "weekly" and day is not None and not 0 <= day <= 6:
        return "Pick a day of the week."
    if schedule_type == "monthly" and day is not None and not 1 <= day <= 31:
        return "The day of the month must be between 1 and 31."
    return None


class ScheduledExportCreate(BaseModel):
    export_config_id: int
    schedule_type: str  # daily, weekly, monthly
    # Weekly: 0 = Monday .. 6 = Sunday. Monthly: 1..31; in a shorter month the
    # report goes out on its last day.
    schedule_day: Optional[int] = None
    schedule_time: str  # HH:MM, in the company's timezone
    recipient_emails: List[EmailStr] = Field(min_length=1, max_length=50)
    is_active: bool = True

    @field_validator("schedule_time")
    @classmethod
    def valid_time(cls, v: str) -> str:
        if not _TIME_RE.match(v or ""):
            raise ValueError("Enter a time like 08:00.")
        return v

    @model_validator(mode="after")
    def valid_day(self):
        problem = _valid_schedule(self.schedule_type, self.schedule_day)
        if problem:
            raise ValueError(problem)
        return self


class ScheduledExportUpdate(BaseModel):
    export_config_id: Optional[int] = None
    schedule_type: Optional[str] = None
    schedule_day: Optional[int] = None
    schedule_time: Optional[str] = None
    recipient_emails: Optional[List[EmailStr]] = Field(default=None, max_length=50)
    is_active: Optional[bool] = None

    @field_validator("schedule_time")
    @classmethod
    def valid_time(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not _TIME_RE.match(v):
            raise ValueError("Enter a time like 08:00.")
        return v

    @field_validator("recipient_emails")
    @classmethod
    def someone(cls, v):
        if v is not None and len(v) == 0:
            raise ValueError("Add at least one email address.")
        return v

    @model_validator(mode="after")
    def valid_day(self):
        problem = _valid_schedule(self.schedule_type, self.schedule_day)
        if problem:
            raise ValueError(problem)
        return self


class ScheduledExportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: str
    export_config_id: int
    export_config_name: str
    schedule_type: str
    schedule_day: Optional[int] = None
    schedule_time: str
    recipient_emails: List[str]
    is_active: bool
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None
    # The next run in the company's own time, e.g. "Mon 29 Sep 2026, 08:00",
    # and the timezone it is in, so nobody has to convert from UTC.
    next_run_local: Optional[str] = None
    timezone: Optional[str] = None
    last_run_status: Optional[str] = None
    last_run_error: Optional[str] = None
    created_by: Optional[int] = None
    owner_name: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ScheduledExportRun(BaseModel):
    id: int
    status: str
    error: Optional[str] = None
    ran_at: Optional[str] = None
    rows: Optional[int] = None
    delivered: Optional[int] = None
    recipients: Optional[int] = None
