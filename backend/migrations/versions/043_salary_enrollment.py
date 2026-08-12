"""Salary access enrollment + approval

Revision ID: 043_salary_enrollment
Revises: 042_policy_rule_scoping

Gates salary/compensation/payroll visibility behind a per-user enrollment that is
orthogonal to role. Being finance/hr/admin is no longer sufficient — a user must
have an active 'viewer' enrollment to see other people's salary. A 'viewer'
request must be approved by a DIFFERENT active 'approver' (separation of duties).

Tables:
- salary_enrollments: the grant (kind viewer|approver, status active|revoked).
- salary_enrollment_requests: the pending approval workflow item + email token.
- notifications: minimal in-app feed backing the approval flow.

Bootstrap: every existing tenant's tenant_admin user(s) are seeded as active
viewer + approver (granted_by NULL) so the system isn't empty and setup can
proceed. The audit trail reuses the existing audit_logs table (no new table).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "043_salary_enrollment"
down_revision = "042_policy_rule_scoping"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "salary_enrollments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("granted_by", sa.Integer(), nullable=True),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", sa.Integer(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["granted_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["revoked_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "user_id", "kind", name="uq_salary_enrollment_user_kind"),
    )
    op.create_index("ix_salary_enrollments_tenant_id", "salary_enrollments", ["tenant_id"])
    op.create_index("ix_salary_enrollments_user_id", "salary_enrollments", ["user_id"])

    op.create_table(
        "salary_enrollment_requests",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("requested_by", sa.Integer(), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by", sa.Integer(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("token", sa.String(length=255), nullable=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["decided_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token", name="uq_salary_enrollment_request_token"),
    )
    op.create_index("ix_salary_enrollment_requests_tenant_id", "salary_enrollment_requests", ["tenant_id"])
    op.create_index("ix_salary_enrollment_requests_user_id", "salary_enrollment_requests", ["user_id"])
    op.create_index("ix_salary_enrollment_requests_token", "salary_enrollment_requests", ["token"])

    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("action_type", sa.String(length=40), nullable=True),
        sa.Column("action_ref_id", sa.Integer(), nullable=True),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_actioned", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_notifications_tenant_id", "notifications", ["tenant_id"])
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])
    op.create_index("ix_notifications_created_at", "notifications", ["created_at"])

    # Bootstrap: seed each tenant's tenant_admin user(s) as active viewer + approver.
    # A user is a tenant_admin iff they have an active user_role -> role(code=tenant_admin).
    op.execute(
        """
        INSERT INTO salary_enrollments (tenant_id, user_id, kind, status, granted_by, granted_at)
        SELECT DISTINCT u.tenant_id, u.id, k.kind, 'active', NULL::integer, NOW()
        FROM users u
        JOIN user_roles ur ON ur.user_id = u.id
        JOIN roles r ON r.id = ur.role_id AND r.code = 'tenant_admin' AND r.is_active = true
        CROSS JOIN (SELECT 'viewer' AS kind UNION ALL SELECT 'approver') k
        ON CONFLICT (tenant_id, user_id, kind) DO NOTHING
        """
    )
    # Audit the seed into the existing audit_logs table.
    op.execute(
        """
        INSERT INTO audit_logs (tenant_id, user_id, action, resource_type, resource_id, details, created_at)
        SELECT se.tenant_id, se.user_id, 'salary_enrollment.seeded', 'salary_enrollment',
               CAST(se.id AS VARCHAR),
               jsonb_build_object('kind', se.kind, 'bootstrap', true), NOW()
        FROM salary_enrollments se
        WHERE se.granted_by IS NULL
        """
    )


def downgrade() -> None:
    op.drop_index("ix_notifications_created_at", table_name="notifications")
    op.drop_index("ix_notifications_user_id", table_name="notifications")
    op.drop_index("ix_notifications_tenant_id", table_name="notifications")
    op.drop_table("notifications")

    op.drop_index("ix_salary_enrollment_requests_token", table_name="salary_enrollment_requests")
    op.drop_index("ix_salary_enrollment_requests_user_id", table_name="salary_enrollment_requests")
    op.drop_index("ix_salary_enrollment_requests_tenant_id", table_name="salary_enrollment_requests")
    op.drop_table("salary_enrollment_requests")

    op.drop_index("ix_salary_enrollments_user_id", table_name="salary_enrollments")
    op.drop_index("ix_salary_enrollments_tenant_id", table_name="salary_enrollments")
    op.drop_table("salary_enrollments")
