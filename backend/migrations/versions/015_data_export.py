"""data export configurations

Revision ID: 015_data_export
Revises: 014_attendance_policy
Create Date: 2026-02-01
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "015_data_export"
down_revision = "014_attendance_policy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "data_export_configs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("data_source", sa.String(50), nullable=False),
        sa.Column("columns", JSONB, nullable=False),
        sa.Column("custom_columns", JSONB, nullable=False, server_default="[]"),
        sa.Column("filters", JSONB, nullable=True),
        sa.Column("sort_by", sa.String(100), nullable=True),
        sa.Column("sort_direction", sa.String(4), nullable=True),
        sa.Column(
            "created_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.UniqueConstraint("tenant_id", "name", name="uq_export_config_tenant_name"),
    )


def downgrade() -> None:
    op.drop_table("data_export_configs")
