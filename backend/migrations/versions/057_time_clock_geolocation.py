"""Time clock: punch events, work sites, and per-arrangement geofence rules.

Employees clock in and out; each punch records the server instant and, where the
browser allows it, the device's coordinates.

Punches are stored as EVENTS rather than as in_/out_ columns on
`attendance_records`, which stays a derived daily summary recomputed after every
punch. Three properties of the real data force this:

* A day can hold more than one in/out pair. Split shifts — a morning worked from
  home, an afternoon on site — exist in the roster, and they are exactly the days
  where the location expectation changes mid-day. One pair of columns cannot
  represent that.
* `attendance_records` is keyed to a single `date` with `Time` columns. It cannot
  express "06:05, the following calendar day, belongs to yesterday", which is the
  ordinary case for a 22:00-06:00 shift.
* A denied location, its later recapture, and an admin correction must all remain
  visible. Columns on a summary row get overwritten.

Keeping punches separate also means `uq_employee_attendance_date` is untouched, so
`overtime_logs.attendance_record_id` and `tardiness_records.attendance_record_id`
(both unique), the uselist=False relationships, analytics and the export registry
all keep working unchanged.

Geofencing is driven by `shifts.work_arrangement`, which is an unvalidated
String(50) and always has been. Rather than retrofit an enum onto live rows that
payroll depends on, `work_arrangement_rules` maps a normalised code to an
expectation and anything unrecognised falls back to `any_location` — a typo must
never become a false "outside the geofence" on someone's timesheet.

Revision ID: 057_time_clock_geolocation
Revises: 056_ce_salary_bootstrap
"""
import sqlalchemy as sa
from alembic import op

revision = "057_time_clock_geolocation"
down_revision = "056_ce_salary_bootstrap"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "work_sites",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("radius_m", sa.Integer(), nullable=False, server_default="200"),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("org_node_id", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["org_node_id"], ["org_nodes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_tenant_work_site_name"),
    )
    op.create_index("ix_work_sites_tenant_id", "work_sites", ["tenant_id"])

    op.create_table(
        "work_arrangement_rules",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("label", sa.String(length=100), nullable=False),
        sa.Column("geofence_mode", sa.String(length=20), nullable=False, server_default="any_location"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "code", name="uq_tenant_arrangement_code"),
    )
    op.create_index("ix_work_arrangement_rules_tenant_id", "work_arrangement_rules", ["tenant_id"])

    op.create_table(
        "time_punches",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("employee_id", sa.Integer(), nullable=False),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("punch_type", sa.String(length=10), nullable=False),
        sa.Column("shift_id", sa.Integer(), nullable=True),
        sa.Column("sequence_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("work_arrangement", sa.String(length=50), nullable=True),
        sa.Column("attendance_record_id", sa.Integer(), nullable=True),
        sa.Column("paired_punch_id", sa.Integer(), nullable=True),
        sa.Column("punched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("local_time", sa.Time(), nullable=False),
        sa.Column("client_reported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("clock_skew_seconds", sa.Integer(), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("accuracy_m", sa.Float(), nullable=True),
        sa.Column("location_status", sa.String(length=20), nullable=False, server_default="not_required"),
        sa.Column("location_captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recapture_deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("geofence_status", sa.String(length=20), nullable=False, server_default="not_applicable"),
        sa.Column("work_site_id", sa.Integer(), nullable=True),
        sa.Column("distance_m", sa.Float(), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=False, server_default="web"),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.String(length=255), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("recorded_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["employee_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["shift_id"], ["shifts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["attendance_record_id"], ["attendance_records.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["paired_punch_id"], ["time_punches.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["work_site_id"], ["work_sites.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["recorded_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_time_punches_tenant_id", "time_punches", ["tenant_id"])
    op.create_index("ix_time_punches_employee_id", "time_punches", ["employee_id"])
    op.create_index("ix_time_punches_attendance_record_id", "time_punches", ["attendance_record_id"])
    op.create_index("ix_time_punches_emp_date", "time_punches", ["tenant_id", "employee_id", "business_date"])

    # At most one OPEN clock-in per employee. Enforced here rather than on the
    # model: the test harness builds DDL from Base.metadata on SQLite, where a
    # model-level partial index compiles to a FULL unique index and would forbid
    # an employee ever having two clock-ins. The service also checks, so this is
    # the race-proofing rather than the only guard.
    op.execute(
        """
        CREATE UNIQUE INDEX uq_one_open_punch_per_employee
        ON time_punches (employee_id)
        WHERE punch_type = 'in' AND paired_punch_id IS NULL
        """
    )

    # Where an on-site employee is expected to be. Per-shift, so the two halves of
    # a split shift can point at different places.
    op.add_column("shifts", sa.Column("work_site_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_shifts_work_site_id", "shifts", "work_sites",
        ["work_site_id"], ["id"], ondelete="SET NULL",
    )

    op.add_column("app_settings", sa.Column(
        "timeclock_enabled", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("app_settings", sa.Column(
        "timeclock_require_location", sa.Boolean(), nullable=False, server_default="true"))
    op.add_column("app_settings", sa.Column(
        "timeclock_location_grace_minutes", sa.Integer(), nullable=False, server_default="60"))
    op.add_column("app_settings", sa.Column(
        "timeclock_default_radius_m", sa.Integer(), nullable=False, server_default="200"))


def downgrade() -> None:
    op.drop_column("app_settings", "timeclock_default_radius_m")
    op.drop_column("app_settings", "timeclock_location_grace_minutes")
    op.drop_column("app_settings", "timeclock_require_location")
    op.drop_column("app_settings", "timeclock_enabled")

    op.drop_constraint("fk_shifts_work_site_id", "shifts", type_="foreignkey")
    op.drop_column("shifts", "work_site_id")

    op.execute("DROP INDEX IF EXISTS uq_one_open_punch_per_employee")
    op.drop_index("ix_time_punches_emp_date", table_name="time_punches")
    op.drop_index("ix_time_punches_attendance_record_id", table_name="time_punches")
    op.drop_index("ix_time_punches_employee_id", table_name="time_punches")
    op.drop_index("ix_time_punches_tenant_id", table_name="time_punches")
    op.drop_table("time_punches")

    op.drop_index("ix_work_arrangement_rules_tenant_id", table_name="work_arrangement_rules")
    op.drop_table("work_arrangement_rules")

    op.drop_index("ix_work_sites_tenant_id", table_name="work_sites")
    op.drop_table("work_sites")
