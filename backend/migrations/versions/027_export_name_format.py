"""Add name_format to data_export_configs

Revision ID: 027_export_name_format
Revises: 026_schedule_employee_visibility
"""
from alembic import op
import sqlalchemy as sa

revision = "027_export_name_format"
down_revision = "026_schedule_employee_visibility"


def upgrade():
    op.add_column(
        "data_export_configs",
        sa.Column("name_format", sa.String(50), nullable=True),
    )


def downgrade():
    op.drop_column("data_export_configs", "name_format")
