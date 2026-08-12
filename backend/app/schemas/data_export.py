from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict


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
    operator: str  # eq, neq, gt, gte, lt, lte, contains, starts_with
    value: Any


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
    date_from: Optional[str] = None
    date_to: Optional[str] = None


class PreviewResponse(BaseModel):
    columns: List[str]
    rows: List[Dict[str, Any]]
    total: int


# ── Scheduled export schemas ───────────────────────────────────

class ScheduledExportCreate(BaseModel):
    export_config_id: int
    schedule_type: str  # daily, weekly, monthly
    schedule_day: Optional[int] = None
    schedule_time: str  # HH:MM
    recipient_emails: List[str]
    is_active: bool = True


class ScheduledExportUpdate(BaseModel):
    export_config_id: Optional[int] = None
    schedule_type: Optional[str] = None
    schedule_day: Optional[int] = None
    schedule_time: Optional[str] = None
    recipient_emails: Optional[List[str]] = None
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
