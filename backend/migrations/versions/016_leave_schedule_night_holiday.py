"""leave schedule overlay, night differential, holiday shift

Revision ID: 016_leave_schedule_night_holiday
Revises: 015_data_export
Create Date: 2026-02-01
"""

from alembic import op
import sqlalchemy as sa

revision = "016_leave_schedule_night_holiday"
down_revision = "015_data_export"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add columns to shifts for leave overlay (preserve original schedule)
    op.add_column("shifts", sa.Column("original_status", sa.String(50), nullable=True))
    op.add_column("shifts", sa.Column("original_start_time", sa.Time(), nullable=True))
    op.add_column("shifts", sa.Column("original_end_time", sa.Time(), nullable=True))
    op.add_column(
        "shifts",
        sa.Column(
            "leave_application_id",
            sa.Integer(),
            sa.ForeignKey("leave_applications.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    # Add log_type to overtime_logs for night diff / holiday shift records
    op.add_column(
        "overtime_logs",
        sa.Column("log_type", sa.String(30), nullable=False, server_default="overtime"),
    )


def downgrade() -> None:
    op.drop_column("overtime_logs", "log_type")
    op.drop_column("shifts", "leave_application_id")
    op.drop_column("shifts", "original_end_time")
    op.drop_column("shifts", "original_start_time")
    op.drop_column("shifts", "original_status")
