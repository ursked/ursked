"""schedule change requests and approval steps

Revision ID: 022_schedule_change_requests
Revises: 021_approver_nullable
Create Date: 2026-02-02
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "022_schedule_change_requests"
down_revision = "021_approver_nullable"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "schedule_change_requests",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("request_type", sa.String(20), nullable=False),
        sa.Column("requester_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("target_employee_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("original_start_time", sa.Time(), nullable=True),
        sa.Column("original_end_time", sa.Time(), nullable=True),
        sa.Column("original_status", sa.String(50), nullable=True),
        sa.Column("target_original_start_time", sa.Time(), nullable=True),
        sa.Column("target_original_end_time", sa.Time(), nullable=True),
        sa.Column("target_original_status", sa.String(50), nullable=True),
        sa.Column("requested_start_time", sa.Time(), nullable=True),
        sa.Column("requested_end_time", sa.Time(), nullable=True),
        sa.Column("requested_status", sa.String(50), nullable=True),
        sa.Column("requested_work_arrangement", sa.String(50), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("reviewed_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewer_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "schedule_change_approval_steps",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("request_id", sa.Integer(), sa.ForeignKey("schedule_change_requests.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("approver_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("step_order", sa.Integer(), nullable=False),
        sa.Column("step_type", sa.String(30), nullable=False, server_default="manager_approval"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("schedule_change_approval_steps")
    op.drop_table("schedule_change_requests")
