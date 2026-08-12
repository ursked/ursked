"""Add paid_break_minutes and unpaid_break_minutes to schedule_formats.

Revision ID: 011_schedule_break_times
Revises: 010_config_types_org
Create Date: 2026-02-01
"""
from alembic import op
import sqlalchemy as sa

revision = "011_schedule_break_times"
down_revision = "010_config_types_org"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "schedule_formats",
        sa.Column("paid_break_minutes", sa.Integer, server_default="0", nullable=False),
    )
    op.add_column(
        "schedule_formats",
        sa.Column("unpaid_break_minutes", sa.Integer, server_default="0", nullable=False),
    )

    # Set sensible defaults for existing seeded formats
    op.execute("""
        UPDATE schedule_formats SET paid_break_minutes = 15, unpaid_break_minutes = 60
        WHERE code = '8_hour'
    """)
    op.execute("""
        UPDATE schedule_formats SET paid_break_minutes = 15, unpaid_break_minutes = 60
        WHERE code = '9_hour'
    """)
    op.execute("""
        UPDATE schedule_formats SET paid_break_minutes = 30, unpaid_break_minutes = 60
        WHERE code = '12_hour'
    """)
    op.execute("""
        UPDATE schedule_formats SET paid_break_minutes = 15, unpaid_break_minutes = 0
        WHERE code = '4_hour'
    """)


def downgrade() -> None:
    op.drop_column("schedule_formats", "unpaid_break_minutes")
    op.drop_column("schedule_formats", "paid_break_minutes")
