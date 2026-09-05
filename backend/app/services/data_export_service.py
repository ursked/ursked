"""
Data export service: config CRUD, row loading, and orchestration of the
transformation pipeline.

Loading and joining live here; every transformation (filter, group, aggregate,
sort, rename, format, serialise) lives in `export_pipeline` so that preview,
download and the scheduler all run the identical code path.
"""

from typing import Any, Callable, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.data_export import DataExportConfig
from app.services import export_pipeline as pipeline
from app.services.data_source_registry import DATA_SOURCES, get_source, get_sources_metadata
from app.services.formula_engine import FormulaEngine, FormulaError


# Sources whose rows are keyed by a calendar date. Used both to decide the
# multi-source join key and to honour date-range filtering (undated rows in these
# sources are excluded when a filter is active).
DATE_SOURCES = {"schedules", "attendance", "overtime_logs", "tardiness_records"}


def _single_label_for(data_source: str) -> Callable[[str], str]:
    """Header text for a column of one source, e.g. "Overtime (min)"."""
    source = DATA_SOURCES.get(data_source, {})
    labels = {c["key"]: c["label"] for c in source.get("columns", [])}

    def label_for(key: str) -> str:
        return labels.get(key, key)

    return label_for


def _multi_label_for(key: str) -> str:
    """Header text for a namespaced column, e.g. "Attendance > Overtime (min)"."""
    if "." not in key:
        return key
    src_key, col_key = key.split(".", 1)
    source = DATA_SOURCES.get(src_key, {})
    col = next((c for c in source.get("columns", []) if c["key"] == col_key), None)
    return f"{source.get('label', src_key)} > {col['label'] if col else col_key}"


def _formula_scope(row: Dict[str, Any]) -> Dict[str, Any]:
    """Give a formula both `{source.column}` and bare `{column}` keys.

    The bare form is ambiguous when two sources share a column name, and the
    last one written wins — which is why the builder writes namespaced keys.
    """
    scope: Dict[str, Any] = {}
    for k, v in row.items():
        if "." in k:
            scope.setdefault(k.split(".", 1)[1], v)
        scope[k] = v
    return scope


def _as_dicts(value: Any) -> List[Dict[str, Any]]:
    """Normalise a list of pydantic models or dicts to plain dicts for JSONB."""
    out = []
    for v in value or []:
        if isinstance(v, dict):
            out.append(v)
        elif hasattr(v, "model_dump"):
            out.append(v.model_dump())
        elif hasattr(v, "dict"):
            out.append(v.dict())
    return out


def _as_dict_map(value: Any) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for k, v in (value or {}).items():
        if isinstance(v, dict):
            out[k] = v
        elif hasattr(v, "model_dump"):
            out[k] = v.model_dump()
        elif hasattr(v, "dict"):
            out[k] = v.dict()
    return out


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
            # name_format was accepted by the schema and had a column and a
            # migration, but was never assigned here — so a report saved with a
            # name format silently lost it until someone edited and re-saved.
            name_format=data.get("name_format"),
            group_by=data.get("group_by") or [],
            aggregations=_as_dicts(data.get("aggregations")),
            column_aliases=data.get("column_aliases") or {},
            column_formats=_as_dict_map(data.get("column_formats")),
            sorts=_as_dicts(data.get("sorts")),
            date_preset=data.get("date_preset"),
            date_from=data.get("date_from"),
            date_to=data.get("date_to"),
            output_format=(data.get("output_format") or "csv"),
            row_limit=data.get("row_limit"),
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

        # JSONB columns must hold plain dicts, not pydantic models.
        for key in ("aggregations", "sorts"):
            if key in data and data[key] is not None:
                data[key] = _as_dicts(data[key])
        if "column_formats" in data and data["column_formats"] is not None:
            data["column_formats"] = _as_dict_map(data["column_formats"])

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

    # ── Export orchestration ─────────────────────────────────────

    @staticmethod
    async def run_export(
        db: AsyncSession,
        tenant_id: UUID,
        spec: Dict[str, Any],
        *,
        limit: Optional[int] = None,
    ) -> Tuple[List[Dict[str, Any]], int, List[Tuple[str, str]]]:
        """Load, transform and shape one export.

        Returns (rows, total_before_limit, output_columns) where output_columns
        is an ordered list of (field_key, header). One entry point for preview,
        download and the scheduler, so the three cannot drift apart — which is
        exactly how scheduled exports ended up unable to run a multi-source
        config at all while the download path could.

        Stage order is documented in `export_pipeline` and is restated to the
        user in the builder, so do not reorder it casually.
        """
        data_source = spec.get("data_source") or ""
        columns: List[str] = list(spec.get("columns") or [])
        custom_columns = list(spec.get("custom_columns") or [])
        group_by = [g for g in (spec.get("group_by") or []) if g]
        aggregations = list(spec.get("aggregations") or [])

        # A relative window re-resolves on every run; absolute dates pass through.
        date_from, date_to = pipeline.resolve_date_window(
            spec.get("date_preset"), spec.get("date_from"), spec.get("date_to")
        )

        # 1. Load
        if data_source == "multi":
            rows = await DataExportService._load_multi_rows(
                db, tenant_id, columns,
                name_format=spec.get("name_format"),
                date_from=date_from, date_to=date_to,
            )
            label_for = _multi_label_for
            valid_columns = list(columns)
        else:
            source = get_source(data_source)
            if not source:
                raise ValueError(f"Unknown data source: {data_source}")
            query_kwargs = {}
            if spec.get("name_format"):
                query_kwargs["name_format"] = spec["name_format"]
            rows = await source["query"](db, tenant_id, **query_kwargs)
            if date_from or date_to:
                rows = _apply_date_range(
                    rows, date_from, date_to, is_date_source=data_source in DATE_SOURCES
                )
            source_col_keys = {c["key"] for c in source["columns"]}
            valid_columns = [c for c in columns if c in source_col_keys]
            label_for = _single_label_for(data_source)

        # 2. Calculate BEFORE filtering and grouping, so a computed column can be
        #    filtered on and grouped by. Formulas see the whole source row, not
        #    just the selected columns.
        if custom_columns:
            for row in rows:
                scope = _formula_scope(row) if data_source == "multi" else row
                for cc in custom_columns:
                    try:
                        row[cc["name"]] = FormulaEngine.evaluate(cc["formula"], scope)
                    except FormulaError:
                        row[cc["name"]] = "#ERROR"

        # 3. Filter
        rows = pipeline.apply_filters(rows, spec.get("filters"))

        # 4. Group — replaces the row shape when active
        if group_by:
            rows = pipeline.apply_grouping(rows, group_by, aggregations)

        # 5. Sort. `sorts` is the multi-key form; fall back to the legacy
        #    sort_by/sort_direction pair so configs saved before 058 still work.
        sorts = list(spec.get("sorts") or [])
        if not sorts and spec.get("sort_by"):
            sorts = [{"column": spec["sort_by"], "direction": spec.get("sort_direction") or "asc"}]
        rows = pipeline.apply_sort(rows, sorts)

        total = len(rows)

        # 6. Limit
        effective_limit = limit if limit is not None else spec.get("row_limit")
        if effective_limit and effective_limit > 0:
            rows = rows[:effective_limit]

        # 7. Project, rename, format
        output_columns = pipeline.build_output_columns(
            columns=valid_columns,
            custom_columns=custom_columns,
            group_by=group_by,
            aggregations=aggregations,
            label_for=label_for,
            aliases=spec.get("column_aliases"),
        )
        shaped = pipeline.project_rows(rows, output_columns, spec.get("column_formats"))
        return shaped, total, output_columns

    @staticmethod
    def serialise(
        rows: List[Dict[str, Any]],
        output_columns: List[Tuple[str, str]],
        output_format: str = "csv",
        sheet_name: str = "Export",
    ) -> Tuple[bytes, str, str]:
        """Return (payload, media_type, file_extension)."""
        if (output_format or "csv").lower() == "xlsx":
            return (
                pipeline.generate_xlsx(rows, output_columns, sheet_name),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "xlsx",
            )
        return pipeline.generate_csv(rows, output_columns).encode("utf-8"), "text/csv", "csv"

    # ── Row loading ──────────────────────────────────────────────

    @staticmethod
    async def _load_multi_rows(
        db: AsyncSession,
        tenant_id: UUID,
        namespaced_columns: List[str],
        name_format: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Query and merge several sources, joined on employee id (+ date).

        Returns raw merged rows keyed `source.column`. Filtering, grouping,
        sorting, limiting and projection all happen afterwards in the pipeline,
        which is what makes multi-source behave identically to single-source —
        previously filters ran BEFORE projection for one source and AFTER for
        several, so the same filter worked in one mode and not the other.
        """
        # Parse namespaced columns -> {source_key: [col_key, ...]}
        source_cols: Dict[str, List[str]] = {}
        for nc in namespaced_columns:
            if '.' not in nc:
                continue
            src_key, col_key = nc.split('.', 1)
            source_cols.setdefault(src_key, []).append(col_key)

        if not source_cols:
            return []

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
            return []

        source_keys = list(source_rows.keys())

        # Only one source actually contributes columns: namespace and return.
        if len(source_keys) == 1:
            src = source_keys[0]
            cols = source_cols[src]
            return [
                {f"{src}.{c}": r.get(c, "") for c in cols}
                for r in source_rows[src]
            ]

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

        return merged


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
