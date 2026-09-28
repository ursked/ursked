"""Payroll and attendance: paid overtime, locked periods, attendance automation

Revision ID: 064_payroll_attendance_integrity
Revises: 060_reports_layouts_and_schedules
Create Date: 2026-09-28

All additive:

1. overtime_logs.payroll_period_id and paid_at. Finalizing a payroll run now
   records which overtime it paid, so re-deriving attendance later can never
   delete and re-create (as pending) overtime that has already been paid.
   Existing finalized runs are back-filled: every approved log dated inside a
   finalized period, for an employee that period paid, is linked to it.

2. overtime_logs: the unique key moves from attendance_record_id alone to
   (attendance_record_id, log_type). The policy engine applies an overtime
   rule and a night-differential rule to the same day (they fill different
   effect slots), and the second insert failed, turning the punch or edit that
   triggered it into a 500.

3. attendance_records gains is_rest_day_work, auto_marked, status_override
   and excused_by_leave_id; time_punches gains auto_closed. See the model
   comments for why each exists.

4. app_settings gains the auto clock-out and auto-absent settings.

Downgrade removes what this revision added. The old single-column overtime
key is only restored when no attendance record has two overtime logs; if one
does, the composite key is kept rather than deleting pay records.
"""

from alembic import op
import sqlalchemy as sa

revision = "064_payroll_attendance_integrity"
down_revision = "060_reports_layouts_and_schedules"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("overtime_logs", sa.Column("payroll_period_id", sa.Integer(), nullable=True))
    op.add_column("overtime_logs", sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        "fk_overtime_logs_payroll_period_id", "overtime_logs", "payroll_periods",
        ["payroll_period_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index("ix_overtime_logs_payroll_period_id", "overtime_logs", ["payroll_period_id"])

    op.execute("ALTER TABLE overtime_logs DROP CONSTRAINT IF EXISTS overtime_logs_attendance_record_id_key")
    op.create_unique_constraint(
        "uq_overtime_log_record_type", "overtime_logs", ["attendance_record_id", "log_type"]
    )
    op.create_index("ix_overtime_logs_attendance_record_id", "overtime_logs", ["attendance_record_id"])

    op.add_column("attendance_records", sa.Column("is_rest_day_work", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("attendance_records", sa.Column("auto_marked", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("attendance_records", sa.Column("status_override", sa.String(20), nullable=True))
    op.add_column("attendance_records", sa.Column("excused_by_leave_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_attendance_records_excused_by_leave_id", "attendance_records", "leave_applications",
        ["excused_by_leave_id"], ["id"], ondelete="SET NULL",
    )

    op.add_column("time_punches", sa.Column("auto_closed", sa.Boolean(), nullable=False, server_default="false"))

    op.add_column("app_settings", sa.Column("auto_clockout_after_hours", sa.Float(), nullable=False, server_default="4"))
    op.add_column("app_settings", sa.Column("auto_clockout_unscheduled_hours", sa.Float(), nullable=False, server_default="16"))
    op.add_column("app_settings", sa.Column("auto_mark_absent", sa.Boolean(), nullable=False, server_default="true"))
    op.add_column("app_settings", sa.Column("auto_absent_after_minutes", sa.Integer(), nullable=False, server_default="120"))

    # Overtime already paid by a finalized run: record it, so it is locked.
    op.execute(
        """
        UPDATE overtime_logs o
           SET payroll_period_id = p.id,
               paid_at = COALESCE(p.finalized_at, now())
          FROM payroll_periods p, payroll_items i
         WHERE p.status = 'finalized'
           AND i.payroll_period_id = p.id
           AND i.employee_id = o.employee_id
           AND o.tenant_id = p.tenant_id
           AND o.status = 'approved'
           AND o.date BETWEEN p.start_date AND p.end_date
           AND o.payroll_period_id IS NULL
        """
    )


def downgrade() -> None:
    op.drop_column("app_settings", "auto_absent_after_minutes")
    op.drop_column("app_settings", "auto_mark_absent")
    op.drop_column("app_settings", "auto_clockout_unscheduled_hours")
    op.drop_column("app_settings", "auto_clockout_after_hours")

    op.drop_column("time_punches", "auto_closed")

    op.drop_constraint("fk_attendance_records_excused_by_leave_id", "attendance_records", type_="foreignkey")
    op.drop_column("attendance_records", "excused_by_leave_id")
    op.drop_column("attendance_records", "status_override")
    op.drop_column("attendance_records", "auto_marked")
    op.drop_column("attendance_records", "is_rest_day_work")

    op.drop_index("ix_overtime_logs_attendance_record_id", table_name="overtime_logs")
    # Put the old key back only if it holds; never delete a pay record to make
    # it fit.
    op.execute(
        """
        DO $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM overtime_logs
             GROUP BY attendance_record_id HAVING count(*) > 1
          ) THEN
            ALTER TABLE overtime_logs DROP CONSTRAINT uq_overtime_log_record_type;
            ALTER TABLE overtime_logs
              ADD CONSTRAINT overtime_logs_attendance_record_id_key UNIQUE (attendance_record_id);
          END IF;
        END $$;
        """
    )

    op.drop_index("ix_overtime_logs_payroll_period_id", table_name="overtime_logs")
    op.drop_constraint("fk_overtime_logs_payroll_period_id", "overtime_logs", type_="foreignkey")
    op.drop_column("overtime_logs", "paid_at")
    op.drop_column("overtime_logs", "payroll_period_id")
