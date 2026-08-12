"""add leave_credit_type_id to overtime_categories

Revision ID: 024_overtime_leave_credit_type
Revises: 023_approver_role
Create Date: 2026-02-03
"""

from alembic import op
import sqlalchemy as sa

revision = "024_overtime_leave_credit_type"
down_revision = "023_approver_role"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "overtime_categories",
        sa.Column(
            "leave_credit_type_id",
            sa.Integer(),
            sa.ForeignKey("leave_types.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("overtime_categories", "leave_credit_type_id")
