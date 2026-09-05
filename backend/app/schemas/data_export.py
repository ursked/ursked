from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator

from app.services.export_pipeline import AGGREGATE_FUNCTIONS, FILTER_OPERATORS


# ── Data source metadata (returned by GET /sources) ──────────────

class DataSourceColumn(BaseModel):
    key: str
    label: str
    type: str  # string, number, date, time, datetime
    is_salary: bool = False


class DataSourceInfo(BaseModel):
    key: str
    label: str
    description: str
    is_salary: bool = False
    columns: List[DataSourceColumn]


# ── Custom column ────────────────────────────────────────────────

class CustomColumnSchema(BaseModel):
    name: str
    formula: str


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
    # Preview only: how many rows to return. The total is reported separately so
    # the builder can say "showing 50 of 4,216" rather than leaving the user to
    # guess how much data they just described.
    limit: Optional[int] = None


class PreviewColumn(BaseModel):
    key: str
    header: str


class PreviewResponse(BaseModel):
    columns: List[str]
    column_headers: List[PreviewColumn] = []
    rows: List[Dict[str, Any]] = []
    total: int
    returned: int = 0
    resolved_date_from: Optional[str] = None
    resolved_date_to: Optional[str] = None


# ── Scheduled export schemas ───────────────────────────────────

class ScheduledExportCreate(BaseModel):
    export_config_id: int
    schedule_type: str  # daily, weekly, monthly
    schedule_day: Optional[int] = None
    schedule_time: str  # HH:MM
    recipient_emails: List[EmailStr]
    is_active: bool = True


class ScheduledExportUpdate(BaseModel):
    export_config_id: Optional[int] = None
    schedule_type: Optional[str] = None
    schedule_day: Optional[int] = None
    schedule_time: Optional[str] = None
    recipient_emails: Optional[List[EmailStr]] = None
    is_active: Optional[bool] = None


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
    last_run_status: Optional[str] = None
    last_run_error: Optional[str] = None
    created_by: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
