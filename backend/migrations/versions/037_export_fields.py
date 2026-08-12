"""Add fields needed for formal schedule exports

Revision ID: 037_export_fields
Revises: 036_org_levels_unbounded

- users.middle_name: formal exports use "LASTNAME, First Middle".
- leave_types.export_code: short remark code (SL/PL/EL/AVL) shown in the
  REMARKS column of the schedule export; tenant-configurable.
"""
from alembic import op
import sqlalchemy as sa

revision = "037_export_fields"
down_revision = "036_org_levels_unbounded"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("middle_name", sa.String(length=100), nullable=True))
    op.add_column("leave_types", sa.Column("export_code", sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column("leave_types", "export_code")
    op.drop_column("users", "middle_name")
