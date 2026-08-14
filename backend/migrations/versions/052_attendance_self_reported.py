"""Add self_reported flag to attendance records

Revision ID: 052_attendance_self_reported
Revises: 051_user_sessions

Marks whether an attendance entry was submitted by the employee themselves
(POST /attendance/my) vs recorded by an admin/manager. Lets admins filter
self-reported entries for review before payroll.
"""
from alembic import op
import sqlalchemy as sa

revision = "052_attendance_self_reported"
down_revision = "051_user_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "attendance_records",
        sa.Column("self_reported", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("attendance_records", "self_reported")
