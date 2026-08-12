"""
Data export service: config CRUD, data querying, formula evaluation, CSV generation.
"""

import csv
import io
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.data_export import DataExportConfig
from app.services.data_source_registry import DATA_SOURCES, get_source, get_sources_metadata
from app.services.formula_engine import FormulaEngine, FormulaError


# Sources whose rows are keyed by a calendar date. Used both to decide the
# multi-source join key and to honour date-range filtering (undated rows in these
# sources are excluded when a filter is active).
DATE_SOURCES = {"schedules", "attendance", "overtime_logs", "tardiness_records"}

# Characters that make spreadsheet apps (Excel, Sheets, LibreOffice) treat a
# cell as a formula. Employee-entered free text (names, notes, reasons) flows
# into exports, so a value like "=cmd|'…'" would execute on open. We neutralise
# by prefixing a single quote, which spreadsheets strip on display.
_CSV_FORMULA_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")


def _csv_safe(value: Any) -> str:
    """Render a cell value as CSV text, neutralising spreadsheet formula injection."""
    if value is None:
        return ""
    s = value if isinstance(value, str) else str(value)
    if s and s[0] in _CSV_FORMULA_TRIGGERS:
        return "'" + s
    return s


class DataExportService:

    # ── Config CRUD ──────────────────────────────────────────────

    @staticmethod
    async def list_configs(
        db: AsyncSession, tenant_id: UUID
    ) -> List[DataExportConfig]:
        stmt = (
            select(DataExportConfig)
            .where(DataExportConfig.tenant_id == tenant_id)
            .order_by(DataExportConfig.name)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_config(
        db: AsyncSession, tenant_id: UUID, config_id: int
    ) -> Optional[DataExportConfig]:
        stmt = select(DataExportConfig).where(
            DataExportConfig.tenant_id == tenant_id,
            DataExportConfig.id == config_id,
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def create_config(
        db: AsyncSession,
        tenant_id: UUID,
        data: Dict[str, Any],
        created_by: int,
    ) -> DataExportConfig:
        if data["data_source"] != "multi":
            source = get_source(data["data_source"])
            if not source:
                raise ValueError(f"Unknown data source: {data['data_source']}")

        # Validate custom column formulas
        for cc in data.get("custom_columns", []):
            err = FormulaEngine.validate(cc["formula"])
            if err:
                raise ValueError(f"Invalid formula in column '{cc['name']}': {err}")

        config = DataExportConfig(
            tenant_id=tenant_id,
            name=data["name"],
            description=data.get("description"),
            data_source=data["data_source"],
            columns=data["columns"],
            custom_columns=[{"name": c["name"], "formula": c["formula"]} for c in data.get("custom_columns", [])],
            filters=[f if isinstance(f, dict) else f.dict() for f in (data.get("filters") or [])],
            sort_by=data.get("sort_by"),
            sort_direction=data.get("sort_direction"),
            created_by=created_by,
        )
        db.add(config)
        return config

    @staticmethod
    async def update_config(
        db: AsyncSession,
        tenant_id: UUID,
        config_id: int,
        data: Dict[str, Any],
    ) -> Optional[DataExportConfig]:
        config = await DataExportService.get_config(db, tenant_id, config_id)
        if not config:
            return None

        if "data_source" in data and data["data_source"] != "multi":
            source = get_source(data["data_source"])
            if not source:
                raise ValueError(f"Unknown data source: {data['data_source']}")

        if "custom_columns" in data and data["custom_columns"] is not None:
            for cc in data["custom_columns"]:
                formula = cc["formula"] if isinstance(cc, dict) else cc.formula
                name = cc["name"] if isinstance(cc, dict) else cc.name
                err = FormulaEngine.validate(formula)
                if err:
                    raise ValueError(f"Invalid formula in column '{name}': {err}")
            data["custom_columns"] = [
                {"name": c["name"] if isinstance(c, dict) else c.name, "formula": c["formula"] if isinstance(c, dict) else c.formula}
                for c in data["custom_columns"]
            ]

        if "filters" in data and data["filters"] is not None:
            data["filters"] = [
                f if isinstance(f, dict) else f.dict()
                for f in data["filters"]
            ]

        for key, value in data.items():
            if hasattr(config, key):
                setattr(config, key, value)

        return config

    @staticmethod
    async def delete_config(
        db: AsyncSession, tenant_id: UUID, config_id: int
    ) -> bool:
        config = await DataExportService.get_config(db, tenant_id, config_id)
        if not config:
            return False
        await db.delete(config)
        return True

    # ── Data query + export ──────────────────────────────────────

    @staticmethod
    async def query_data(
        db: AsyncSession,
        tenant_id: UUID,
        data_source: str,
        columns: List[str],
        custom_columns: Optional[List[Dict[str, str]]] = None,
        filters: Optional[List[Dict[str, Any]]] = None,
        sort_by: Optional[str] = None,
        sort_direction: Optional[str] = None,
        limit: Optional[int] = None,
        name_format: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Query data from a source and apply column selection, formulas, filters."""
        source = get_source(data_source)
        if not source:
            raise ValueError(f"Unknown data source: {data_source}")

        # Get all rows from source
        query_kwargs = {}
        if name_format:
            query_kwargs["name_format"] = name_format
        all_rows = await source["query"](db, tenant_id, **query_kwargs)

        # Apply date range filter
        if date_from or date_to:
            all_rows = _apply_date_range(
                all_rows, date_from, date_to, is_date_source=data_source in DATE_SOURCES
            )

        # Apply filters
        if filters:
            all_rows = _apply_filters(all_rows, filters)

        # Apply sort
        if sort_by:
            reverse = (sort_direction or "asc").lower() == "desc"
            all_rows.sort(key=lambda r: _sort_key(r.get(sort_by, "")), reverse=reverse)

        total = len(all_rows)

        # Apply limit
        if limit and limit > 0:
            all_rows = all_rows[:limit]

        # Project columns + compute custom columns
        source_col_keys = {c["key"] for c in source["columns"]}
        valid_columns = [c for c in columns if c in source_col_keys]

        result_rows = []
        for row in all_rows:
            projected = {}
            for col in valid_columns:
                projected[col] = row.get(col, "")

            # Evaluate custom columns
            if custom_columns:
                for cc in custom_columns:
                    try:
                        projected[cc["name"]] = FormulaEngine.evaluate(cc["formula"], row)
                    except FormulaError:
                        projected[cc["name"]] = "#ERROR"

            result_rows.append(projected)

        return result_rows, total

    # ── Multi-source query + export ─────────────────────────────

    @staticmethod
    async def query_multi_source_data(
        db: AsyncSession,
        tenant_id: UUID,
        namespaced_columns: List[str],
        custom_columns: Optional[List[Dict[str, str]]] = None,
        filters: Optional[List[Dict[str, Any]]] = None,
        sort_by: Optional[str] = None,
        sort_direction: Optional[str] = None,
        limit: Optional[int] = None,
        name_format: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Query and merge data from multiple sources, joined on employee_id."""
        # Parse namespaced columns -> {source_key: [col_key, ...]}
        source_cols: Dict[str, List[str]] = {}
        for nc in namespaced_columns:
            if '.' not in nc:
                continue
            src_key, col_key = nc.split('.', 1)
            source_cols.setdefault(src_key, []).append(col_key)

        if not source_cols:
            return [], 0

        # Query each needed source
        query_kwargs = {}
        if name_format:
            query_kwargs["name_format"] = name_format
        source_rows: Dict[str, List[Dict[str, Any]]] = {}
        for src_key in source_cols:
            source = get_source(src_key)
            if not source:
                continue
            rows = await source["query"](db, tenant_id, **query_kwargs)
            # Apply date range filter per source
            if date_from or date_to:
                rows = _apply_date_range(
                    rows, date_from, date_to, is_date_source=src_key in DATE_SOURCES
                )
            source_rows[src_key] = rows

        if not source_rows:
            return [], 0

        source_keys = list(source_rows.keys())

        # Single source fast path
        if len(source_keys) == 1:
            src = source_keys[0]
            cols = source_cols[src]
            projected = []
            for r in source_rows[src]:
                row = {f"{src}.{c}": r.get(c, "") for c in cols}
                projected.append(row)
            if filters:
                projected = _apply_filters(projected, filters)
            if sort_by:
                reverse = (sort_direction or "asc").lower() == "desc"
                projected.sort(key=lambda r: _sort_key(r.get(sort_by, "")), reverse=reverse)
            total = len(projected)
            if limit and limit > 0:
                projected = projected[:limit]
            if custom_columns:
                for row in projected:
                    flat = {}
                    for k, v in row.items():
                        if '.' in k:
                            flat[k.split('.', 1)[1]] = v
                        flat[k] = v
                    for cc in custom_columns:
                        try:
                            row[cc["name"]] = FormulaEngine.evaluate(cc["formula"], flat)
                        except FormulaError:
                            row[cc["name"]] = "#ERROR"
            return projected, total

        # Multi-source merge
        EMPLOYEE_SOURCES = {
            "employees", "schedules", "attendance", "leave_applications",
            "overtime_logs", "tardiness_records", "payroll_items",
            "leave_credit_adjustments",
        }

        # Pick primary source: prefer detail (date-based) sources, then largest
        detail = [s for s in source_keys if s in DATE_SOURCES]
        if detail:
            primary = max(detail, key=lambda s: len(source_rows[s]))
        elif "employees" in source_keys:
            primary = "employees"
        else:
            primary = max(source_keys, key=lambda s: len(source_rows[s]))

        secondary_keys = [s for s in source_keys if s != primary]

        # Build lookup indices for secondary sources. Each key maps to a LIST of
        # matching rows (not just the first) so multiple same-day records — e.g.
        # two overtime logs on one date — are not silently dropped.
        sec_index: Dict[str, Dict[str, Any]] = {}
        for sec in secondary_keys:
            idx: Dict[Any, List[Dict[str, Any]]] = {}
            primary_has_date = primary in DATE_SOURCES
            sec_has_date = sec in DATE_SOURCES
            use_date = primary_has_date and sec_has_date

            for row in source_rows[sec]:
                eid = row.get("employee_id")
                if eid is None:
                    continue
                key = (eid, row.get("date", "")) if use_date else eid
                idx.setdefault(key, []).append(row)
            sec_index[sec] = {"data": idx, "use_date": use_date}

        def _secondary_matches(sec: str, eid: Any, pdate: str) -> List[Dict[str, Any]]:
            si = sec_index[sec]
            key = (eid, pdate) if si["use_date"] else eid
            return si["data"].get(key, [])

        # Build merged rows. To keep row counts correct without a combinatorial
        # blow-up across several secondaries, we fan out on AT MOST ONE secondary
        # (the first that has multiple matches for a given primary row); the rest
        # contribute their first match. This preserves the common "one primary +
        # one detail source" case (the real duplicate-drop bug) while staying
        # bounded when many sources are combined.
        merged: List[Dict[str, Any]] = []
        for prow in source_rows[primary]:
            base: Dict[str, Any] = {}
            for c in source_cols.get(primary, []):
                base[f"{primary}.{c}"] = prow.get(c, "")

            eid = prow.get("employee_id")
            pdate = prow.get("date", "")

            # Decide which (if any) secondary to fan out on.
            fanout_sec: Optional[str] = None
            for sec in secondary_keys:
                if len(_secondary_matches(sec, eid, pdate)) > 1:
                    fanout_sec = sec
                    break

            fan_rows = _secondary_matches(fanout_sec, eid, pdate) if fanout_sec else [None]
            if not fan_rows:
                fan_rows = [None]

            for fan_row in fan_rows:
                mrow = dict(base)
                for sec in secondary_keys:
                    if sec == fanout_sec and fan_row is not None:
                        srow = fan_row
                    else:
                        matches = _secondary_matches(sec, eid, pdate)
                        srow = matches[0] if matches else {}
                    for c in source_cols.get(sec, []):
                        mrow[f"{sec}.{c}"] = srow.get(c, "")
                merged.append(mrow)

        # Apply filters
        if filters:
            merged = _apply_filters(merged, filters)

        # Sort
        if sort_by:
            reverse = (sort_direction or "asc").lower() == "desc"
            merged.sort(key=lambda r: _sort_key(r.get(sort_by, "")), reverse=reverse)

        total = len(merged)
        if limit and limit > 0:
            merged = merged[:limit]

        # Custom columns (provide both namespaced and flat keys for formulas)
        if custom_columns:
            for row in merged:
                flat: Dict[str, Any] = {}
                for k, v in row.items():
                    if '.' in k:
                        flat[k.split('.', 1)[1]] = v
                    flat[k] = v
                for cc in custom_columns:
                    try:
                        row[cc["name"]] = FormulaEngine.evaluate(cc["formula"], flat)
                    except FormulaError:
                        row[cc["name"]] = "#ERROR"

        return merged, total

    @staticmethod
    def generate_multi_csv(
        rows: List[Dict[str, Any]],
        namespaced_columns: List[str],
        custom_columns: Optional[List[Dict[str, str]]] = None,
        currency_code: Optional[str] = None,
    ) -> str:
        """Generate CSV from multi-source merged data with readable headers.

        Monetary column headers are suffixed with the tenant currency code
        (e.g. "Payroll > Net Pay (PHP)") so raw numeric amounts remain numeric
        while the denomination stays explicit."""
        from app.services.data_source_registry import column_is_monetary

        output = io.StringIO()

        headers = []
        for nc in namespaced_columns:
            if '.' in nc:
                src_key, col_key = nc.split('.', 1)
                source = DATA_SOURCES.get(src_key, {})
                src_label = source.get("label", src_key)
                col_def = next(
                    (c for c in source.get("columns", []) if c["key"] == col_key),
                    None,
                )
                col_label = col_def["label"] if col_def else col_key
                header = f"{src_label} > {col_label}"
                if currency_code and column_is_monetary(src_key, col_key):
                    header = f"{header} ({currency_code})"
                headers.append(header)
            else:
                headers.append(nc)
        if custom_columns:
            for cc in custom_columns:
                headers.append(cc["name"])

        field_keys = list(namespaced_columns)
        if custom_columns:
            field_keys.extend(cc["name"] for cc in custom_columns)

        writer = csv.writer(output)
        writer.writerow(headers)
        for row in rows:
            writer.writerow([_csv_safe(row.get(k, "")) for k in field_keys])

        return output.getvalue()

    @staticmethod
    def generate_csv(
        rows: List[Dict[str, Any]],
        columns: List[str],
        custom_columns: Optional[List[Dict[str, str]]] = None,
        source_columns: Optional[List[Dict[str, str]]] = None,
        data_source: Optional[str] = None,
        currency_code: Optional[str] = None,
    ) -> str:
        """Generate CSV string from query results.

        Monetary column headers are suffixed with the tenant currency code
        (e.g. "Net Pay (PHP)") when data_source + currency_code are supplied."""
        from app.services.data_source_registry import column_is_monetary

        output = io.StringIO()

        # Build header labels
        col_label_map = {}
        if source_columns:
            for sc in source_columns:
                col_label_map[sc["key"]] = sc["label"]

        headers = []
        for col in columns:
            label = col_label_map.get(col, col)
            if currency_code and data_source and column_is_monetary(data_source, col):
                label = f"{label} ({currency_code})"
            headers.append(label)
        if custom_columns:
            for cc in custom_columns:
                headers.append(cc["name"])

        # Build field keys in order
        field_keys = list(columns)
        if custom_columns:
            field_keys.extend(cc["name"] for cc in custom_columns)

        writer = csv.writer(output)
        writer.writerow(headers)

        for row in rows:
            writer.writerow([_csv_safe(row.get(k, "")) for k in field_keys])

        return output.getvalue()


def _apply_date_range(
    rows: List[Dict[str, Any]],
    date_from: Optional[str],
    date_to: Optional[str],
    is_date_source: bool = False,
) -> List[Dict[str, Any]]:
    """Filter rows by date range. Looks for 'date', 'start_date', or namespaced date keys.

    `is_date_source` controls what happens to a row with no usable date value:
    - For a genuinely date-less source (employees, salary grades) it is kept, so a
      date filter set alongside other sources doesn't wipe reference data.
    - For a date-based source (schedules, attendance, overtime, tardiness) a row
      with a missing/blank date is EXCLUDED when a filter is active — otherwise the
      filter would silently leak out-of-range or undated records the user believes
      they scoped out.
    """
    if not date_from and not date_to:
        return rows

    def get_date_value(row: Dict[str, Any]) -> Optional[str]:
        # Check common date field names (direct and namespaced)
        for key in ("date", "start_date"):
            if key in row and row[key]:
                return str(row[key])
        # Check namespaced date keys like "schedules.date"
        for key, val in row.items():
            if key.endswith(".date") or key.endswith(".start_date"):
                if val:
                    return str(val)
        return None

    result = []
    for row in rows:
        dv = get_date_value(row)
        if dv is None:
            # Keep undated rows only for date-less sources; drop them for
            # date-based sources so the filter is honoured.
            if not is_date_source:
                result.append(row)
            continue
        if date_from and dv < date_from:
            continue
        if date_to and dv > date_to:
            continue
        result.append(row)
    return result


def _apply_filters(rows: List[Dict[str, Any]], filters: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Apply filter conditions to rows."""
    result = rows
    for f in filters:
        col = f.get("column", "")
        op = f.get("operator", "eq")
        val = f.get("value", "")
        result = [r for r in result if _match_filter(r.get(col, ""), op, val)]
    return result


def _match_filter(cell_value: Any, operator: str, filter_value: Any) -> bool:
    """Check if a cell value matches a filter condition."""
    cv_str = str(cell_value).lower() if cell_value is not None else ""
    fv_str = str(filter_value).lower() if filter_value is not None else ""

    if operator == "eq":
        return cv_str == fv_str
    if operator == "neq":
        return cv_str != fv_str
    if operator == "contains":
        return fv_str in cv_str
    if operator == "starts_with":
        return cv_str.startswith(fv_str)

    # Numeric comparisons
    try:
        cv_num = float(cell_value) if cell_value else 0
        fv_num = float(filter_value) if filter_value else 0
    except (TypeError, ValueError):
        return False

    if operator == "gt":
        return cv_num > fv_num
    if operator == "gte":
        return cv_num >= fv_num
    if operator == "lt":
        return cv_num < fv_num
    if operator == "lte":
        return cv_num <= fv_num

    return True


def _sort_key(value: Any):
    """Generate a sort key that works for mixed types."""
    if value is None or value == "":
        return (1, "")
    try:
        return (0, float(value))
    except (TypeError, ValueError):
        return (0, str(value).lower())
