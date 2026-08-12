"""Add break offset hours to schedule_formats

Revision ID: 029_schedule_break_offset
Revises: 028_employee_separation
"""

from alembic import op
import sqlalchemy as sa

revision = "029_schedule_break_offset"
down_revision = "028_employee_separation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "schedule_formats",
        sa.Column("paid_break_after_hours", sa.Float(), nullable=False, server_default="4.0"),
    )
    op.add_column(
        "schedule_formats",
        sa.Column("unpaid_break_after_hours", sa.Float(), nullable=False, server_default="4.0"),
    )

    # Set sensible defaults for common formats
    op.execute("""
        UPDATE schedule_formats SET
            paid_break_after_hours = CASE code
                WHEN '4_hour' THEN 2.0
                WHEN 'flexible' THEN 0
                ELSE 4.0
            END,
            unpaid_break_after_hours = CASE code
                WHEN '4_hour' THEN 0
                WHEN '12_hour' THEN 6.0
                WHEN 'flexible' THEN 0
                ELSE 4.0
            END
    """)


def downgrade() -> None:
    op.drop_column("schedule_formats", "unpaid_break_after_hours")
    op.drop_column("schedule_formats", "paid_break_after_hours")
