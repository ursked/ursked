"""Add employee separation fields and data retention settings

Revision ID: 028_employee_separation
Revises: 027_export_name_format
"""
from alembic import op
import sqlalchemy as sa

revision = "028_employee_separation"
down_revision = "027_export_name_format"


def upgrade():
    # User separation fields
    op.add_column("users", sa.Column("separation_type", sa.String(20), nullable=True))
    op.add_column("users", sa.Column("separation_date", sa.Date(), nullable=True))
    op.add_column("users", sa.Column("separation_reason", sa.Text(), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "separated_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    # App settings for data retention
    op.add_column("app_settings", sa.Column("data_retention_days", sa.Integer(), nullable=True))
    op.add_column(
        "app_settings",
        sa.Column("analytics_exclusion_days", sa.Integer(), nullable=True, server_default="0"),
    )


def downgrade():
    op.drop_column("app_settings", "analytics_exclusion_days")
    op.drop_column("app_settings", "data_retention_days")
    op.drop_column("users", "separated_by")
    op.drop_column("users", "separation_reason")
    op.drop_column("users", "separation_date")
    op.drop_column("users", "separation_type")
