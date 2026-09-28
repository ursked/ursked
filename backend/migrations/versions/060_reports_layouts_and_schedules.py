"""Reports: page layouts, source options, and scheduled exports on local time

Revision ID: 060_reports_layouts_and_schedules
Revises: 062_schedules_grid_holidays
Create Date: 2026-09-28

1. data_export_configs.layout (JSONB, nullable) describes the page a report is
   drawn on: headings above the table, header bands, a block per employee,
   the sheet name. NULL means the flat sheet every existing report already
   produces, so nothing changes for a report until someone gives it a layout.

2. data_export_configs.source_options (JSONB, default {}) holds switches for
   the data source, e.g. "show every day in the period". Empty for every
   existing report.

3. Scheduled exports now run at the time the person typed, in the company's
   timezone (app_settings.timezone). They used to run at that time in UTC, so
   "08:00" went out at 16:00 in Manila. Existing schedules are re-timed to
   their next local run. The old screen could also save a monthly schedule
   for "day 0" (switching from weekly kept the weekday index), which never
   matched a date; those become day 1, the value the screen showed.

4. An index for the once-a-minute "what is due?" query.

Downgrade drops the two columns and the index. It cannot tell a day-0
schedule from a genuine day-1 one afterwards, and a next run time in the
company's timezone is still a correct instant, so those stay as they are.
"""

from datetime import datetime, timedelta, timezone

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "060_reports_layouts_and_schedules"
down_revision = "062_schedules_grid_holidays"
branch_labels = None
depends_on = None


def _next_run(schedule_type, day, at, tz_name, now):
    """Same rule as scheduled_export_service.compute_next_run, frozen here so
    the migration does not change if the service does."""
    from calendar import monthrange
    from zoneinfo import ZoneInfo

    try:
        tz = ZoneInfo(tz_name or "UTC")
    except Exception:
        tz = ZoneInfo("UTC")
    local_now = now.astimezone(tz)
    today = local_now.date()

    def at_local(d):
        return datetime(d.year, d.month, d.day, at.hour, at.minute, tzinfo=tz)

    if schedule_type == "daily":
        c = at_local(today)
        if c <= local_now:
            c = at_local(today + timedelta(days=1))
        return c.astimezone(timezone.utc)
    if schedule_type == "weekly":
        ahead = ((day or 0) - today.weekday()) % 7
        c = at_local(today + timedelta(days=ahead))
        if c <= local_now:
            c = at_local(today + timedelta(days=ahead + 7))
        return c.astimezone(timezone.utc)
    if schedule_type == "monthly":
        want = min(max(day or 1, 1), 31)
        y, m = today.year, today.month
        for _ in range(3):
            d = today.replace(year=y, month=m, day=min(want, monthrange(y, m)[1]))
            c = at_local(d)
            if c > local_now:
                return c.astimezone(timezone.utc)
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return None


def upgrade() -> None:
    op.add_column(
        "data_export_configs",
        sa.Column("layout", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "data_export_configs",
        sa.Column("source_options", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    op.create_index(
        "ix_scheduled_exports_due",
        "scheduled_exports",
        ["is_active", "next_run_at"],
    )

    conn = op.get_bind()
    conn.execute(sa.text(
        "UPDATE scheduled_exports SET schedule_day = 1 "
        "WHERE schedule_type = 'monthly' AND (schedule_day IS NULL OR schedule_day < 1)"
    ))
    conn.execute(sa.text(
        "UPDATE scheduled_exports SET schedule_day = 31 "
        "WHERE schedule_type = 'monthly' AND schedule_day > 31"
    ))

    now = datetime.now(timezone.utc)
    rows = conn.execute(sa.text(
        "SELECT s.id, s.schedule_type, s.schedule_day, s.schedule_time, a.timezone "
        "FROM scheduled_exports s LEFT JOIN app_settings a ON a.tenant_id = s.tenant_id "
        "WHERE s.is_active"
    )).all()
    for sid, stype, sday, stime, tz_name in rows:
        nxt = _next_run(stype, sday, stime, tz_name, now)
        if nxt is not None:
            conn.execute(
                sa.text("UPDATE scheduled_exports SET next_run_at = :n WHERE id = :i"),
                {"n": nxt, "i": sid},
            )


def downgrade() -> None:
    op.drop_index("ix_scheduled_exports_due", table_name="scheduled_exports")
    op.drop_column("data_export_configs", "source_options")
    op.drop_column("data_export_configs", "layout")
