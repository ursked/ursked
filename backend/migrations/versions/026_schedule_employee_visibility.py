"""Add schedule_employee_visibility to app_settings

Revision ID: 026_schedule_employee_visibility
Revises: 025_schedule_snapshots
"""
from alembic import op
import sqlalchemy as sa

revision = "026_schedule_employee_visibility"
down_revision = "025_schedule_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column(
            "schedule_employee_visibility",
            sa.String(30),
            nullable=False,
            server_default="own_node",
        ),
    )


def downgrade() -> None:
    op.drop_column("app_settings", "schedule_employee_visibility")
