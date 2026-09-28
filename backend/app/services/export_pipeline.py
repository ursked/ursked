"""
Transformation pipeline for custom data exports.

Before this module the exporter could do `SELECT cols FROM one_source WHERE ...
ORDER BY one_col` and nothing else: no grouping, no aggregates, no column
renaming, no value formatting, no relative date windows. Those are the whole
difference between "a column picker" and "something you would otherwise open
Excel or write SQL for", so they live here rather than being scattered through
the service.

The stages run in a FIXED order, and the order is the contract the UI explains
to the user in plain English:

    1. load        rows come out of the data source
    2. date window absolute dates, or a relative preset resolved against today
    3. filter      row conditions, ANDed
    4. calculate   formula columns (so you can group or filter-after on them)
    5. group       group-by + aggregates, which REPLACES the row shape
    6. sort        one or more keys
    7. limit       top N
    8. project     choose, order and rename the output columns (raw values)
    9. render      lay the rows out on a page: display formatting for preview
                   and CSV, typed cells and number formats for Excel, and the
                   optional layout (headings, header bands, blocks, tabs)

Aggregation deliberately sits after the formula stage: "total overtime per
department" is only expressible if a computed department column already exists.
Sorting sits after aggregation so you can sort by a total. Rendering never adds,
removes or reorders a data row: grouping changes the rows, the layout changes
the page, which is why the two can be combined.

Values stay RAW until stage 9. They used to be stringified in stage 8, so a
start time reached the workbook as the text '14:00' (or '2:00 PM') and nobody
could sort or subtract it. Now preview and CSV format at the edge, and the
workbook gets a real date/time/number with a matching Excel number format.

Column identity
---------------
A report can show the same field more than once (the work schedule shows the
shift date as both FROM and TO), so an output column is an INSTANCE of a field:

    instance_id := field_key | field_key "::" integer >= 2

The first instance's id is the field key itself, so every config saved before
instances existed is already valid. What keys off what:

    instance id   columns, column_aliases, column_formats,
                  layout.header_tiers[].from/to, layout.blocks.by
    field key     filters, sorts, group_by, aggregations, formulas

Anything that reads a row applies `field_of()` first, because rows are keyed by
field, never by instance.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any, Callable, Dict, Iterable, List, NamedTuple, Optional, Tuple

from app.utils.timeutil import utcnow

# ── Date windows ─────────────────────────────────────────────────────
#
# A saved report that says "last 30 days" has to mean last 30 days *when it
# runs*, not when it was saved. Absolute dates cannot express that, which is why
# every scheduled export currently emails the entire history every time: there
# was nowhere to put a window at all.

DATE_PRESETS = (
    "today",
    "yesterday",
    "last_7_days",
    "last_30_days",
    "last_90_days",
    "this_week",
    "last_week",
    "this_month",
    "last_month",
    "this_quarter",
    "this_year",
    "year_to_date",
    "custom",
)


def resolve_date_window(
    preset: Optional[str],
    date_from: Optional[str],
    date_to: Optional[str],
    today: Optional[date] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """Turn a preset (or explicit dates) into a concrete ISO from/to pair."""
    if not preset or preset == "custom":
        return date_from, date_to

    # Callers pass the company's day; the fallback is UTC, never the container clock.
    d = today or utcnow().date()
    iso = lambda x: x.isoformat()  # noqa: E731

    if preset == "today":
        return iso(d), iso(d)
    if preset == "yesterday":
        y = d - timedelta(days=1)
        return iso(y), iso(y)
    if preset == "last_7_days":
        return iso(d - timedelta(days=6)), iso(d)
    if preset == "last_30_days":
        return iso(d - timedelta(days=29)), iso(d)
    if preset == "last_90_days":
        return iso(d - timedelta(days=89)), iso(d)
    if preset == "this_week":
        start = d - timedelta(days=d.weekday())
        return iso(start), iso(start + timedelta(days=6))
    if preset == "last_week":
        start = d - timedelta(days=d.weekday() + 7)
        return iso(start), iso(start + timedelta(days=6))
    if preset == "this_month":
        start = d.replace(day=1)
        return iso(start), iso(_end_of_month(start))
    if preset == "last_month":
        first_this = d.replace(day=1)
        end_prev = first_this - timedelta(days=1)
        return iso(end_prev.replace(day=1)), iso(end_prev)
    if preset == "this_quarter":
        q_start_month = 3 * ((d.month - 1) // 3) + 1
        start = d.replace(month=q_start_month, day=1)
        end_month = q_start_month + 2
        return iso(start), iso(_end_of_month(d.replace(month=end_month, day=1)))
    if preset == "this_year":
        return iso(d.replace(month=1, day=1)), iso(d.replace(month=12, day=31))
    if preset == "year_to_date":
        return iso(d.replace(month=1, day=1)), iso(d)

    # Unknown preset: fall back to whatever explicit dates were given rather
    # than silently exporting everything.
    return date_from, date_to


def _end_of_month(d: date) -> date:
    if d.month == 12:
        return d.replace(day=31)
    return d.replace(month=d.month + 1, day=1) - timedelta(days=1)


# ── Column identity ──────────────────────────────────────────────────

INSTANCE_SEP = "::"


def field_of(instance_id: str) -> str:
    """The field an output column shows: 'date::2' -> 'date', 'date' -> 'date'.

    Splits only on the LAST '::' and only when the right side is an integer of
    at least 2, so a field whose own name happens to contain '::' is left alone.
    """
    if not isinstance(instance_id, str) or INSTANCE_SEP not in instance_id:
        return instance_id
    base, _sep, tail = instance_id.rpartition(INSTANCE_SEP)
    if base and tail.isdigit() and int(tail) >= 2:
        return base
    return instance_id


def new_instance_id(field_key: str, existing: Iterable[str]) -> str:
    """The next unused instance id for `field_key`: 'date' -> 'date::2'."""
    taken = set(existing)
    base = field_of(field_key)
    if base not in taken:
        return base
    n = 2
    while f"{base}{INSTANCE_SEP}{n}" in taken:
        n += 1
    return f"{base}{INSTANCE_SEP}{n}"


# ── Filters ──────────────────────────────────────────────────────────

FILTER_OPERATORS = {
    "eq": "is",
    "neq": "is not",
    "contains": "contains",
    "not_contains": "does not contain",
    "starts_with": "starts with",
    "ends_with": "ends with",
    "gt": "is greater than",
    "gte": "is greater than or equal to",
    "lt": "is less than",
    "lte": "is less than or equal to",
    "between": "is between",
    "in": "is any of",
    "not_in": "is none of",
    "is_empty": "is empty",
    "is_not_empty": "is not empty",
}

# Operators that carry no value, so the UI hides the value box entirely.
NO_VALUE_OPERATORS = {"is_empty", "is_not_empty"}


def _as_number(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def match_filter(cell: Any, operator: str, value: Any) -> bool:
    """Evaluate one condition against one cell.

    An UNKNOWN operator raises rather than returning True. The previous
    behaviour fell through to `return True`, so a typo'd operator matched every
    row and the export silently ignored the filter.
    """
    cv = "" if cell is None else str(cell)
    cv_l = cv.lower()

    if operator == "is_empty":
        return cv.strip() == ""
    if operator == "is_not_empty":
        return cv.strip() != ""

    if operator == "in" or operator == "not_in":
        wanted = value if isinstance(value, list) else [
            v.strip() for v in str(value).split(",") if v.strip()
        ]
        hit = cv_l in {str(w).lower() for w in wanted}
        return hit if operator == "in" else not hit

    if operator == "between":
        lo_raw, hi_raw = (value + [None, None])[:2] if isinstance(value, list) else (None, None)
        lo_n, hi_n, cv_n = _as_number(lo_raw), _as_number(hi_raw), _as_number(cell)
        if lo_n is not None and hi_n is not None and cv_n is not None:
            return lo_n <= cv_n <= hi_n
        # Dates and anything else compare lexically, which is correct for ISO.
        lo_s = "" if lo_raw is None else str(lo_raw)
        hi_s = "" if hi_raw is None else str(hi_raw)
        return (not lo_s or cv >= lo_s) and (not hi_s or cv <= hi_s)

    fv = "" if value is None else str(value)
    fv_l = fv.lower()

    if operator == "eq":
        return cv_l == fv_l
    if operator == "neq":
        return cv_l != fv_l
    if operator == "contains":
        return fv_l in cv_l
    if operator == "not_contains":
        return fv_l not in cv_l
    if operator == "starts_with":
        return cv_l.startswith(fv_l)
    if operator == "ends_with":
        return cv_l.endswith(fv_l)

    if operator in ("gt", "gte", "lt", "lte"):
        cv_n, fv_n = _as_number(cell), _as_number(value)
        if cv_n is None or fv_n is None:
            # Dates arrive as ISO strings, which order correctly as text.
            if operator == "gt":
                return cv > fv
            if operator == "gte":
                return cv >= fv
            if operator == "lt":
                return cv < fv
            return cv <= fv
        if operator == "gt":
            return cv_n > fv_n
        if operator == "gte":
            return cv_n >= fv_n
        if operator == "lt":
            return cv_n < fv_n
        return cv_n <= fv_n

    raise ValueError(f"Unknown filter operator: {operator}")


def apply_filters(
    rows: List[Dict[str, Any]], filters: Optional[List[Dict[str, Any]]]
) -> List[Dict[str, Any]]:
    if not filters:
        return rows
    out = rows
    for f in filters:
        col = field_of(f.get("column", ""))
        op = f.get("operator", "eq")
        val = f.get("value")
        out = [r for r in out if match_filter(r.get(col, ""), op, val)]
    return out


# ── Aggregation ──────────────────────────────────────────────────────

AGGREGATE_FUNCTIONS = {
    "sum": "Total",
    "avg": "Average",
    "min": "Lowest",
    "max": "Highest",
    "count": "Count",
    "count_distinct": "Distinct count",
    "first": "First",
}


def aggregate_label(func: str, column_label: str) -> str:
    """Human label for a generated column, e.g. "Total Overtime (min)"."""
    if func == "count":
        return "Number of rows"
    return f"{AGGREGATE_FUNCTIONS.get(func, func.title())} {column_label}"


def aggregate_output_key(agg: Dict[str, Any]) -> str:
    return agg.get("output_key") or agg.get("label") or agg.get("column")


def apply_grouping(
    rows: List[Dict[str, Any]],
    group_by: List[str],
    aggregations: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Collapse rows to one per distinct combination of the group-by columns.

    Grouping REPLACES the row shape: the result has exactly the group-by columns
    plus one column per aggregate, keyed by each aggregate's output name. Any
    other selected column is dropped, because there is no defensible value to
    show for it once fifty rows have become one.
    """
    if not group_by:
        return rows

    group_by = [field_of(g) for g in group_by]
    buckets: Dict[Tuple, List[Dict[str, Any]]] = {}
    order: List[Tuple] = []
    for r in rows:
        key = tuple(str(r.get(g, "")) for g in group_by)
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(r)

    out: List[Dict[str, Any]] = []
    for key in order:
        members = buckets[key]
        row: Dict[str, Any] = {g: key[i] for i, g in enumerate(group_by)}
        for agg in aggregations or []:
            row[aggregate_output_key(agg)] = _compute_aggregate(members, agg)
        out.append(row)
    return out


def _compute_aggregate(members: List[Dict[str, Any]], agg: Dict[str, Any]) -> Any:
    func = agg.get("func", "sum")
    col = field_of(agg.get("column", ""))

    if func == "count":
        return len(members)

    values = [m.get(col) for m in members]

    if func == "count_distinct":
        return len({str(v) for v in values if v not in (None, "")})
    if func == "first":
        for v in values:
            if v not in (None, ""):
                return v
        return ""

    numbers = [n for n in (_as_number(v) for v in values) if n is not None]
    if not numbers:
        # min/max still make sense on text (earliest date, first name).
        if func in ("min", "max"):
            texts = sorted(str(v) for v in values if v not in (None, ""))
            if not texts:
                return ""
            return texts[0] if func == "min" else texts[-1]
        return 0

    if func == "sum":
        total = sum(numbers)
    elif func == "avg":
        total = sum(numbers) / len(numbers)
    elif func == "min":
        total = min(numbers)
    elif func == "max":
        total = max(numbers)
    else:
        return ""

    # Keep integers looking like integers: a count of shifts should read 12, not
    # 12.0, in a spreadsheet cell people will eyeball.
    rounded = round(total, 4)
    return int(rounded) if float(rounded).is_integer() else rounded


# ── Sorting ──────────────────────────────────────────────────────────


def _sort_key(value: Any):
    if value is None or value == "":
        return (1, 0.0, "")
    n = _as_number(value)
    if n is not None:
        return (0, n, "")
    return (0, 0.0, str(value).lower())


def apply_sort(rows: List[Dict[str, Any]], sorts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Sort by one or more keys.

    Applied last-key-first because Python's sort is stable, which is what makes
    "by department, then by name within it" come out right.
    """
    if not sorts:
        return rows
    out = list(rows)
    for s in reversed(sorts):
        col = field_of(s.get("column") or "")
        if not col:
            continue
        desc = str(s.get("direction", "asc")).lower() == "desc"
        out.sort(key=lambda r: _sort_key(r.get(col, "")), reverse=desc)
    return out


# ── Value formatting ─────────────────────────────────────────────────

DATE_PATTERNS = {
    "iso": "%Y-%m-%d",
    "dmy": "%d/%m/%Y",
    "mdy": "%m/%d/%Y",
    "long": "%d %B %Y",
    "month_year": "%B %Y",
    "day_month": "%d %b",
    "weekday": "%a %d %b",
}

TIME_PATTERNS = {"24h": "%H:%M", "12h": "%I:%M %p"}

# The same choices, as Excel number formats, so a recipient sees in the cell
# exactly what the preview showed while the value underneath stays a real date.
EXCEL_DATE_FORMATS = {
    "iso": "yyyy-mm-dd",
    "dmy": "dd/mm/yyyy",
    "mdy": "mm/dd/yyyy",
    "long": "dd mmmm yyyy",
    "month_year": "mmmm yyyy",
    "day_month": "dd mmm",
    "weekday": "ddd dd mmm",
}
EXCEL_TIME_FORMATS = {"24h": "hh:mm", "12h": "h:mm AM/PM"}
EXCEL_DATETIME_FORMAT = "yyyy-mm-dd hh:mm"


def format_value(value: Any, spec: Optional[Dict[str, Any]]) -> Any:
    """Apply a display format. Unparseable values are returned untouched.

    Deliberately forgiving: a formatting choice must never turn a cell into an
    error. If a date will not parse, the original string is better than "#ERROR".
    """
    if not spec or value in (None, ""):
        return value

    kind = spec.get("kind")

    if kind == "number":
        n = _as_number(value)
        if n is None:
            return value
        decimals = int(spec.get("decimals", 0) or 0)
        s = f"{n:,.{decimals}f}" if spec.get("thousands") else f"{n:.{decimals}f}"
        prefix = spec.get("prefix") or ""
        suffix = spec.get("suffix") or ""
        return f"{prefix}{s}{suffix}"

    if kind == "date":
        fmt = DATE_PATTERNS.get(spec.get("pattern", "iso"))
        if not fmt:
            return value
        parsed = _parse_date(value)
        return parsed.strftime(fmt) if parsed else value

    if kind == "time":
        fmt = TIME_PATTERNS.get(spec.get("pattern", "24h"))
        if not fmt:
            return value
        parsed = _parse_time(value)
        return parsed.strftime(fmt).lstrip("0") if parsed and spec.get("pattern") == "12h" else (
            parsed.strftime(fmt) if parsed else value
        )

    if kind == "text":
        t = spec.get("transform")
        s = str(value)
        if t == "upper":
            return s.upper()
        if t == "lower":
            return s.lower()
        if t == "title":
            return s.title()
        return s

    return value


def _parse_date(value: Any) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s[: len(fmt) + 2] if "T" in fmt or " " in fmt else s, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s).date()
    except ValueError:
        return None


def _parse_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    s = str(value).strip()
    try:
        # Excel has no time zones; the wall-clock value as stored is what the
        # CSV and the preview show, so that is what the cell holds.
        return datetime.fromisoformat(s).replace(tzinfo=None)
    except ValueError:
        return None


def _parse_time(value: Any) -> Optional[datetime]:
    if isinstance(value, time):
        return datetime(1900, 1, 1, value.hour, value.minute, value.second)
    s = str(value).strip()
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


# ── Output shaping ───────────────────────────────────────────────────


class OutputColumn(NamedTuple):
    """One column of the output, in order.

    `key` is the instance id (see "Column identity"), `type` the source column
    type (string, number, date, time, datetime; None when unknown, e.g. a
    calculated column) and `format` the user's display format, if any. It is a
    tuple so code that only wants (key, header) can still unpack the first two.
    """

    key: str
    header: str
    type: Optional[str] = None
    format: Optional[Dict[str, Any]] = None


def output_keys_for(spec: Dict[str, Any]) -> List[str]:
    """The instance ids a spec will output, in order, without running it.

    Used to validate a layout at save time against the columns it names.
    """
    group_by = [g for g in (spec.get("group_by") or []) if g]
    if group_by:
        keys = list(group_by)
        for agg in spec.get("aggregations") or []:
            a = agg if isinstance(agg, dict) else agg.model_dump()
            keys.append(aggregate_output_key(a))
        return keys
    keys = list(spec.get("columns") or [])
    for cc in spec.get("custom_columns") or []:
        keys.append(cc["name"] if isinstance(cc, dict) else cc.name)
    return keys


def build_output_columns(
    *,
    columns: List[str],
    custom_columns: Optional[List[Dict[str, str]]],
    group_by: Optional[List[str]],
    aggregations: Optional[List[Dict[str, Any]]],
    label_for: Callable[[str], str],
    aliases: Optional[Dict[str, str]] = None,
    type_for: Optional[Callable[[str], Optional[str]]] = None,
    formats: Optional[Dict[str, Dict[str, Any]]] = None,
) -> List[OutputColumn]:
    """Return the ordered output columns.

    When grouping is on, the selected columns are irrelevant — the shape is
    group-by keys plus aggregates — so the caller does not have to keep the two
    in sync and the UI can say so plainly.
    """
    aliases = aliases or {}
    formats = formats or {}
    type_for = type_for or (lambda _k: None)
    out: List[OutputColumn] = []

    def col(key: str, header: str, typ: Optional[str]) -> OutputColumn:
        return OutputColumn(key, header, typ, formats.get(key) or None)

    if group_by:
        for g in group_by:
            out.append(col(g, aliases.get(g) or label_for(field_of(g)), type_for(field_of(g))))
        for agg in aggregations or []:
            key = aggregate_output_key(agg)
            func = agg.get("func", "sum")
            header = aliases.get(key) or agg.get("label") or aggregate_label(
                func, label_for(field_of(agg.get("column", "")))
            )
            typ = type_for(field_of(agg.get("column", ""))) if func in ("min", "max", "first") else "number"
            out.append(col(key, header, typ))
        return out

    for c in columns:
        out.append(col(c, aliases.get(c) or label_for(field_of(c)), type_for(field_of(c))))
    for cc in custom_columns or []:
        name = cc["name"]
        out.append(col(name, aliases.get(name) or name, None))
    return out


def project_rows(
    rows: List[Dict[str, Any]],
    output_columns: List[Tuple],
    formats: Optional[Dict[str, Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Reduce each row to the output columns, keyed by instance id. RAW values.

    `formats` is accepted for callers written before the raw/display split and
    applied if given; the pipeline itself passes none and formats at the edge.
    """
    out = []
    for r in rows:
        row = {}
        for c in output_columns:
            key = c[0]
            v = r.get(key, r.get(field_of(key), ""))
            row[key] = format_value(v, formats.get(key)) if formats else v
        out.append(row)
    return out


def format_rows(
    rows: List[Dict[str, Any]], output_columns: List[Tuple]
) -> List[Dict[str, Any]]:
    """Display values for the preview and CSV: each column's format applied."""
    fmts = {c[0]: (c[3] if len(c) > 3 else None) for c in output_columns}
    out = []
    for r in rows:
        out.append({k: format_value(r.get(k, ""), f) for k, f in fmts.items()})
    return out


# ── Excel typing ─────────────────────────────────────────────────────


def excel_number_format(col_type: Optional[str], fmt: Optional[Dict[str, Any]]) -> Optional[str]:
    """The Excel number format matching what the preview shows for a column."""
    fmt = fmt or {}
    kind = fmt.get("kind")
    if kind == "date" or (col_type == "date" and kind in (None, "")):
        return EXCEL_DATE_FORMATS.get(fmt.get("pattern") or "iso", EXCEL_DATE_FORMATS["iso"])
    if col_type == "datetime" and kind in (None, ""):
        return EXCEL_DATETIME_FORMAT
    if kind == "time" or (col_type == "time" and kind in (None, "")):
        return EXCEL_TIME_FORMATS.get(fmt.get("pattern") or "24h", EXCEL_TIME_FORMATS["24h"])
    if kind == "number":
        decimals = max(0, min(int(fmt.get("decimals") or 0), 10))
        body = "#,##0" if fmt.get("thousands") else "0"
        if decimals:
            body += "." + "0" * decimals

        def lit(s: Any) -> str:
            s = str(s or "").replace('"', "")
            return f'"{s}"' if s else ""

        return f"{lit(fmt.get('prefix'))}{body}{lit(fmt.get('suffix'))}"
    return None


def _number(value: Any) -> Optional[Any]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    s = str(value)
    if not _looks_numeric(s):
        return None
    n = _as_number(s.replace(",", ""))
    if n is None:
        return None
    return int(n) if float(n).is_integer() and "." not in s else n


def typed_cell(
    value: Any, col_type: Optional[str], fmt: Optional[Dict[str, Any]] = None
) -> Tuple[Any, Optional[str]]:
    """(cell value, Excel number format) for one raw value.

    The declared column type decides, not the look of the value: a Personnel #
    of "00123" is text and keeps its zeros, a start time is a time. Untyped
    columns (calculated ones) keep the old behaviour of recognising numbers and
    ISO dates, so their cells do not change. A value that will not parse as its
    type is written as its display text rather than as an error.
    """
    if value is None or value == "":
        return None, None
    fmt = fmt or None
    kind = (fmt or {}).get("kind")

    if kind == "text":
        return str(format_value(value, fmt)), None

    if kind == "date" or col_type == "date":
        d = _parse_date(value)
        if d is not None:
            return d, excel_number_format("date", fmt)
    elif col_type == "datetime":
        dt = _parse_datetime(value)
        if dt is not None:
            return dt, excel_number_format("datetime", fmt)
    elif kind == "time" or col_type == "time":
        t = _parse_time(value)
        if t is not None:
            return t.time(), excel_number_format("time", fmt)
    elif kind == "number" or col_type == "number":
        n = _number(value)
        if n is not None:
            return n, excel_number_format("number", fmt)
    elif col_type is None:
        if isinstance(value, bool):
            return value, None
        n = _number(value)
        if n is not None:
            return n, None
        s = str(value)
        if len(s) >= 8 and s[:4].isdigit():
            d = _parse_date(s)
            if d is not None:
                return d, EXCEL_DATE_FORMATS["iso"]
        return s, None
    else:
        return str(value), None

    # Did not parse as its type: show what the preview shows.
    return str(format_value(value, fmt)), None


# ── Layout ───────────────────────────────────────────────────────────
#
# A layout describes the page, never the data. It is optional: a report
# without one is the flat sheet it always was. The object is:
#
#   heading_rows  [{text, span, align, bold}]  lines above the table; `span`
#                 is how many columns the line is merged across (all if unset)
#   header_tiers  [[{label, from, to}]]  rows of header bands above the column
#                 headings; a band groups the columns from..to (instance ids)
#   blocks        {by, blank_rows_between, repeat_value, sheet_per_group}
#                 start a new block whenever the `by` column changes value
#   sheet_name    worksheet name, tokens allowed
#   style         "plain" (the builder's look) or "banded" (grey headings and
#                 a border round every cell, like a printed form)
#   freeze_header keep the headings on screen while scrolling
#
# A column not covered by a band in some tier has its heading merged
# VERTICALLY up through that tier. That is derived, never specified, and is
# what produces A2:A3 / D2:D3 / K2:K3 in the client's work schedule.
#
# Headings and sheet names may use {report_name}, {date_from}, {date_to} and
# {group}; dates also take a strftime pattern, e.g. {date_from:%b %d}. Tokens
# resolve from a fixed dict, never eval, and an unknown token stays as typed:
# a formatting choice must never turn into an error.

LAYOUT_STYLES = ("plain", "banded")
REPEAT_VALUES = ("every_row", "first_row")
MAX_SHEETS = 500
MAX_BLANK_ROWS = 10

_TOKEN_RE = re.compile(r"\{(report_name|date_from|date_to|group)(?::([^{}]*))?\}")


def resolve_tokens(text: Optional[str], context: Optional[Dict[str, Any]]) -> str:
    if not text:
        return ""
    ctx = context or {}

    def sub(m: "re.Match[str]") -> str:
        name, pattern = m.group(1), m.group(2)
        v = ctx.get(name)
        if v in (None, ""):
            return ""
        if pattern and name in ("date_from", "date_to"):
            d = _parse_date(v)
            if d is None:
                return str(v)
            try:
                return d.strftime(pattern)
            except (ValueError, TypeError):
                return m.group(0)
        return str(v)

    return _TOKEN_RE.sub(sub, text)


def _layout_dict(layout: Any) -> Optional[Dict[str, Any]]:
    if layout is None:
        return None
    if hasattr(layout, "model_dump"):
        return layout.model_dump(by_alias=True)
    return layout


def layout_problems(layout: Any, output_keys: List[str], labels: Optional[Dict[str, str]] = None) -> Optional[str]:
    """A plain-English reason the layout cannot be drawn, or None.

    Checked when a report is saved or run, so a band that names a removed column
    fails loudly at save time rather than silently vanishing from the file.
    """
    layout = _layout_dict(layout)
    if not layout:
        return None
    labels = labels or {}
    pos = {k: i for i, k in enumerate(output_keys)}

    def name(k: str) -> str:
        return labels.get(k) or k

    for t, tier in enumerate(layout.get("header_tiers") or []):
        spans = []
        for band in tier or []:
            label = (band.get("label") or "").strip() or "(untitled)"
            a, b = band.get("from"), band.get("to")
            if a not in pos or b not in pos:
                missing = a if a not in pos else b
                return (
                    f"The heading “{label}” groups {name(missing)}, which is not a "
                    "column of this report. Add the column back or change the heading."
                )
            if pos[a] > pos[b]:
                return f"The heading “{label}” starts after it ends. Pick its first column, then its last."
            for other_label, lo, hi in spans:
                if pos[a] <= hi and lo <= pos[b]:
                    return (
                        f"The headings “{other_label}” and “{label}” cover the same "
                        "columns. Headings on the same row cannot overlap."
                    )
            spans.append((label, pos[a], pos[b]))
    blocks = layout.get("blocks")
    if blocks:
        by = blocks.get("by")
        if by not in pos:
            return (
                f"Blocks are started by {name(by)}, which is not a column of this report. "
                "Add the column back or choose another one."
            )
    return None


@dataclass
class SheetCell:
    row: int
    col: int
    value: Any
    number_format: Optional[str] = None
    role: str = "body"  # heading | band | header | body
    bold: bool = False
    align: Optional[str] = None


@dataclass
class SheetSpec:
    """One worksheet, fully decided, with no openpyxl in sight.

    The Excel and CSV writers both draw from this, which is how the CSV can be
    a faithful flattening of the workbook instead of a separate guess.
    """

    title: str
    ncols: int
    cells: List[SheetCell] = field(default_factory=list)
    merges: List[Tuple[int, int, int, int]] = field(default_factory=list)
    freeze: Optional[str] = None
    widths: Dict[int, float] = field(default_factory=dict)
    heights: Dict[int, float] = field(default_factory=dict)
    style: str = "flat"  # flat | plain | banded
    # For the CSV: ("heading", [text]) | ("header", [labels]) | ("body", [texts]) | ("blank", [])
    lines: List[Tuple[str, List[str]]] = field(default_factory=list)


_SHEET_BAD = set('[]:*?/\\')


def safe_sheet_title(name: str, taken: Optional[set] = None, fallback: str = "Export") -> str:
    """Excel's rules: at most 31 characters, none of []:*?/\\, not blank, no
    leading or trailing apostrophe, unique in the workbook (case-insensitive)."""
    s = "".join(c for c in (name or "") if c not in _SHEET_BAD).replace("\n", " ").strip().strip("'").strip()
    s = s[:31].strip() or fallback
    if taken is None:
        return s
    lower = {t.lower() for t in taken}
    if s.lower() not in lower:
        return s
    n = 2
    while True:
        suffix = f" ({n})"
        cand = s[: 31 - len(suffix)].rstrip() + suffix
        if cand.lower() not in lower:
            return cand
        n += 1


def _display_text(value: Any) -> str:
    return "" if value is None else str(value)


def _flat_widths(output_columns: List[OutputColumn], display_rows: List[Dict[str, Any]]) -> Dict[int, float]:
    widths: Dict[int, float] = {}
    for ci, c in enumerate(output_columns, start=1):
        widest = max((len(line) for line in str(c.header).split("\n")), default=0)
        for r in display_rows[:200]:
            widest = max(widest, len(str(r.get(c.key, ""))))
        widths[ci] = min(max(widest + 2, 10), 45)
    return widths


def build_sheet_plan(
    rows: List[Dict[str, Any]],
    output_columns: List[Tuple],
    layout: Any = None,
    context: Optional[Dict[str, Any]] = None,
    *,
    sheet_name: str = "Export",
) -> List[SheetSpec]:
    """Decide every cell of the workbook for `rows` (raw, projected).

    Pure: no openpyxl, no database. Returns one SheetSpec per worksheet (more
    than one only with blocks.sheet_per_group). Never adds, drops or reorders a
    data row; blocks only insert blank rows between runs of the same value.
    """
    cols = [OutputColumn(*c) if not isinstance(c, OutputColumn) else c for c in output_columns]
    display = format_rows(rows, cols)
    layout = _layout_dict(layout)
    ctx = dict(context or {})

    if not layout:
        return [_flat_plan(rows, display, cols, sheet_name)]

    blocks = layout.get("blocks") or None
    by = blocks.get("by") if blocks else None

    if blocks and blocks.get("sheet_per_group") and by:
        groups: Dict[str, List[int]] = {}
        for i, r in enumerate(rows):
            groups.setdefault(_display_text(r.get(by)), []).append(i)
        if len(groups) > MAX_SHEETS:
            raise ValueError(
                f"This would make {len(groups):,} tabs, one per value of the block column. "
                f"A workbook this size is not usable; the limit is {MAX_SHEETS}. "
                "Filter the report down, or turn off “one tab per block”."
            )
        taken: set = set()
        plans = []
        for gval, idxs in groups.items():
            gctx = dict(ctx, group=gval)
            title_src = layout.get("sheet_name") or "{group}"
            title = safe_sheet_title(resolve_tokens(title_src, gctx), taken, fallback="Blank")
            taken.add(title)
            plans.append(
                _layout_plan([rows[i] for i in idxs], [display[i] for i in idxs], cols, layout, gctx, title)
            )
        if not plans:
            plans.append(_layout_plan([], [], cols, layout, ctx, safe_sheet_title(
                resolve_tokens(layout.get("sheet_name"), ctx) or sheet_name)))
        return plans

    title = safe_sheet_title(resolve_tokens(layout.get("sheet_name"), ctx) or sheet_name)
    return [_layout_plan(rows, display, cols, layout, ctx, title)]


def _body_cells(
    plan: SheetSpec, r_index: int, raw: Dict[str, Any], disp: Dict[str, Any], cols: List[OutputColumn],
    blank_keys: Iterable[str] = (),
) -> None:
    blank = set(blank_keys)
    texts = []
    for ci, c in enumerate(cols, start=1):
        if c.key in blank:
            texts.append("")
            continue
        v, nf = typed_cell(raw.get(c.key), c.type, c.format)
        plan.cells.append(SheetCell(r_index, ci, v, nf, "body"))
        texts.append(_display_text(disp.get(c.key, "")))
    plan.lines.append(("body", texts))


def _flat_plan(rows, display, cols: List[OutputColumn], sheet_name: str) -> SheetSpec:
    """Exactly the sheet the builder has always produced: one header row,
    frozen, auto-sized columns."""
    plan = SheetSpec(title=safe_sheet_title(sheet_name), ncols=len(cols), style="flat")
    for ci, c in enumerate(cols, start=1):
        plan.cells.append(SheetCell(1, ci, c.header, None, "header"))
    plan.lines.append(("header", [c.header for c in cols]))
    for ri, (raw, disp) in enumerate(zip(rows, display), start=2):
        _body_cells(plan, ri, raw, disp, cols)
    plan.freeze = "A2"
    plan.widths = _flat_widths(cols, display)
    return plan


def _layout_plan(rows, display, cols: List[OutputColumn], layout: Dict[str, Any], ctx, title: str) -> SheetSpec:
    ncols = len(cols)
    style = layout.get("style") if layout.get("style") in LAYOUT_STYLES else "plain"
    plan = SheetSpec(title=title, ncols=ncols, style=style)
    pos = {c.key: i + 1 for i, c in enumerate(cols)}
    r = 1

    # Headings.
    for h in layout.get("heading_rows") or []:
        text = resolve_tokens(h.get("text"), ctx)
        span = h.get("span") or ncols
        span = max(1, min(int(span), max(ncols, 1)))
        plan.cells.append(SheetCell(r, 1, text or None, None, "heading",
                                    bold=bool(h.get("bold", True)), align=h.get("align") or "left"))
        if span > 1:
            plan.merges.append((r, 1, r, span))
        plan.lines.append(("heading", [text]))
        r += 1

    # Header bands, then the leaf headings.
    tiers = layout.get("header_tiers") or []
    first_header_row = r
    leaf_row = r + len(tiers)
    deepest: Dict[int, int] = {}
    band_of: Dict[int, List[str]] = {}
    for t, tier in enumerate(tiers):
        row = first_header_row + t
        for band in tier or []:
            a, b = pos.get(band.get("from")), pos.get(band.get("to"))
            if a is None or b is None or a > b:
                continue  # validated at save; never draw a broken band
            label = band.get("label") or ""
            plan.cells.append(SheetCell(row, a, label, None, "band"))
            if b > a:
                plan.merges.append((row, a, row, b))
            if "\n" in label:
                plan.heights[row] = max(plan.heights.get(row, 0), 14.0 * (label.count("\n") + 1))
            for ci in range(a, b + 1):
                deepest[ci] = t
                band_of.setdefault(ci, []).append(label.replace("\n", " ").strip())
    for ci, c in enumerate(cols, start=1):
        top = first_header_row + deepest.get(ci, -1) + 1
        plan.cells.append(SheetCell(top, ci, c.header, None, "header"))
        if top < leaf_row:
            plan.merges.append((top, ci, leaf_row, ci))
    # CSV has one header line, so a band is folded into each column name.
    plan.lines.append((
        "header",
        [" — ".join(band_of.get(ci, []) + [c.header.replace("\n", " ")]) for ci, c in enumerate(cols, start=1)],
    ))

    # Body, in blocks.
    body_first = leaf_row + 1
    r = body_first
    blocks = layout.get("blocks") or None
    by = blocks.get("by") if blocks else None
    gap = max(0, min(int((blocks or {}).get("blank_rows_between") or 0), MAX_BLANK_ROWS)) if by else 0
    first_only = bool(blocks and blocks.get("repeat_value") == "first_row")
    prev: Optional[str] = None
    for i, (raw, disp) in enumerate(zip(rows, display)):
        key = _display_text(raw.get(by)) if by else None
        new_block = bool(by) and (i == 0 or key != prev)
        if new_block and i > 0:
            for _ in range(gap):
                plan.lines.append(("blank", []))
                r += 1
        blank = [by] if (by and first_only and not new_block) else []
        _body_cells(plan, r, raw, disp, cols, blank)
        prev = key
        r += 1

    if layout.get("freeze_header", True):
        plan.freeze = f"A{body_first}"
    plan.widths = _flat_widths(cols, display)
    return plan


# ── Serialisation ────────────────────────────────────────────────────

# Characters that make a spreadsheet treat a cell as a formula. Employee-entered
# free text flows into exports, so "=cmd|'...'" would execute on open.
_FORMULA_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(value: Any) -> str:
    if value is None:
        return ""
    s = value if isinstance(value, str) else str(value)
    if s and s[0] in _FORMULA_TRIGGERS:
        return "'" + s
    return s


def generate_csv(
    rows: List[Dict[str, Any]],
    output_columns: List[Tuple],
    layout: Any = None,
    context: Optional[Dict[str, Any]] = None,
) -> str:
    """CSV from the same sheet plan as the workbook.

    A flat report is exactly what it always was. With a layout, the headings
    become lines of their own, header bands are folded into the column names
    ("WORK SCHEDULE (Dates) — FROM") and blocks keep their blank lines. Tabs
    cannot exist in a CSV, so one-tab-per-block puts every tab in the one file,
    each after a blank line; the builder says so before you download.
    """
    import csv as _csv

    buf = io.StringIO()
    writer = _csv.writer(buf)
    plans = build_sheet_plan(rows, output_columns, layout, context)
    for i, plan in enumerate(plans):
        if i > 0:
            writer.writerow([])
        for kind, cells in plan.lines:
            if kind == "blank":
                writer.writerow([])
            elif kind == "body":
                writer.writerow([csv_safe(c) for c in cells])
            else:
                writer.writerow([csv_safe(c) for c in cells])
    return buf.getvalue()


def generate_xlsx(
    rows: List[Dict[str, Any]],
    output_columns: List[Tuple],
    sheet_name: str = "Export",
    layout: Any = None,
    context: Optional[Dict[str, Any]] = None,
) -> bytes:
    """Write a real workbook: typed cells, a frozen header, sized columns.

    Numbers are written as numbers, dates as dates and times as times, each
    with the number format that matches the preview, so the recipient can sort,
    sum and pivot without re-typing the sheet — which is the main reason people
    ask for Excel instead of CSV in the first place.
    """
    from openpyxl import Workbook

    plans = build_sheet_plan(rows, output_columns, layout, context, sheet_name=sheet_name)
    wb = Workbook()
    for i, plan in enumerate(plans):
        ws = wb.active if i == 0 else wb.create_sheet()
        ws.title = plan.title
        _write_sheet(ws, plan)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _write_sheet(ws, plan: SheetSpec) -> None:
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    purple_font = Font(bold=True, color="FFFFFF")
    purple_fill = PatternFill("solid", fgColor="7C3AED")
    thin = Side(style="thin", color="BFBFBF")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    grey_fill = PatternFill("solid", fgColor="D9D9D9")
    banded = plan.style == "banded"

    for c in plan.cells:
        cell = ws.cell(row=c.row, column=c.col)
        cell.value = c.value
        if isinstance(c.value, str):
            # openpyxl reads a string starting with "=" as a formula. Cell text
            # comes from employee data, so it must always stay text.
            cell.data_type = "s"
        if c.number_format:
            cell.number_format = c.number_format
        if c.role in ("header", "band"):
            if banded:
                cell.font = Font(bold=True, size=9)
                cell.fill = grey_fill
                cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            else:
                cell.font = purple_font
                cell.fill = purple_fill
                cell.alignment = Alignment(
                    horizontal="center" if plan.style != "flat" else None,
                    vertical="center", wrap_text=True,
                )
        elif c.role == "heading":
            cell.font = Font(bold=c.bold, size=12)
            cell.alignment = Alignment(horizontal=c.align or "left", vertical="center")
        elif banded:
            cell.font = Font(size=9)
            cell.alignment = Alignment(horizontal="left" if c.col == 1 else "center", vertical="center")

    if banded:
        header_rows = {c.row for c in plan.cells if c.role in ("header", "band")}
        body_rows = {c.row for c in plan.cells if c.role == "body"}
        for row in header_rows:
            for col in range(1, plan.ncols + 1):
                cell = ws.cell(row=row, column=col)
                cell.border = border
                cell.fill = grey_fill
        for row in body_rows:
            for col in range(1, plan.ncols + 1):
                ws.cell(row=row, column=col).border = border

    for r1, c1, r2, c2 in plan.merges:
        ws.merge_cells(start_row=r1, start_column=c1, end_row=r2, end_column=c2)
    if plan.freeze:
        ws.freeze_panes = plan.freeze
    for ci, w in plan.widths.items():
        ws.column_dimensions[get_column_letter(ci)].width = w
    for row, h in plan.heights.items():
        ws.row_dimensions[row].height = h


def _looks_numeric(s: str) -> bool:
    t = s.strip().replace(",", "")
    if not t or t in ("-", "+", "."):
        return False
    if t[0] in "+-":
        t = t[1:]
    return t.replace(".", "", 1).isdigit()
