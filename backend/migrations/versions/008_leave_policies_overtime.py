"""Add leave types, leave policies, policy entitlements, and overtime categories.

Revision ID: 008_leave_policies_overtime
Revises: 007_superadmin_site_settings
Create Date: 2026-01-31
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON, UUID

revision = "008_leave_policies_overtime"
down_revision = "007_superadmin_site_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── leave_types ──────────────────────────────────────────────────
    op.create_table(
        "leave_types",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "code", name="uq_tenant_leave_type_code"),
    )

    # ── leave_policies ───────────────────────────────────────────────
    op.create_table(
        "leave_policies",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("accrual_method", sa.String(20), nullable=False, server_default="annual"),
        sa.Column("pool_type", sa.String(20), nullable=False, server_default="per_type"),
        sa.Column("employment_types", JSON(), nullable=False, server_default="[]"),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("shared_annual_credits", sa.Float(), nullable=True),
        sa.Column("shared_carry_over_enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("shared_max_carry_over_days", sa.Float(), nullable=False, server_default="0"),
        sa.Column("shared_carry_over_expiry_months", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("shared_cash_convertible", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("shared_cash_conversion_rate", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_tenant_leave_policy_name"),
    )

    # ── leave_policy_entitlements ────────────────────────────────────
    op.create_table(
        "leave_policy_entitlements",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("policy_id", sa.Integer(), sa.ForeignKey("leave_policies.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("leave_type_id", sa.Integer(), sa.ForeignKey("leave_types.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("annual_credits", sa.Float(), nullable=False, server_default="0"),
        sa.Column("carry_over_enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("max_carry_over_days", sa.Float(), nullable=False, server_default="0"),
        sa.Column("carry_over_expiry_months", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cash_convertible", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("cash_conversion_rate", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("requires_documentation", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("min_notice_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("policy_id", "leave_type_id", name="uq_policy_leave_type"),
    )

    # ── overtime_categories ──────────────────────────────────────────
    op.create_table(
        "overtime_categories",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("multiplier_rate", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("compensation_type", sa.String(20), nullable=False, server_default="paid"),
        sa.Column("leave_credit_rate", sa.Float(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "code", name="uq_tenant_overtime_category_code"),
    )

    # ── Seed default leave types for all existing tenants ────────────
    op.execute(sa.text("""
        INSERT INTO leave_types (tenant_id, code, name, is_system, is_active, sort_order, created_at, updated_at)
        SELECT t.id, lt.code, lt.name, true, true, lt.sort_order, now(), now()
        FROM tenants t
        CROSS JOIN (VALUES
            ('annual_vacation',   'Annual Vacation',   0),
            ('sick_leave',        'Sick Leave',        1),
            ('personal_leave',    'Personal Leave',    2),
            ('emergency_leave',   'Emergency Leave',   3),
            ('bereavement_leave', 'Bereavement Leave', 4),
            ('paternity_leave',   'Paternity Leave',   5),
            ('maternity_leave',   'Maternity Leave',   6),
            ('other',             'Other',             7)
        ) AS lt(code, name, sort_order)
    """))

    # ── Seed default "Standard" policy for all existing tenants ──────
    op.execute(sa.text("""
        INSERT INTO leave_policies (
            tenant_id, name, description, accrual_method, pool_type,
            employment_types, is_default, is_active, created_at, updated_at
        )
        SELECT
            t.id,
            'Standard',
            'Default leave policy for all employees',
            'annual',
            'per_type',
            '["rank_and_file","rank_and_file_probationary","confidential","confidential_probationary","contractual"]'::json,
            true,
            true,
            now(),
            now()
        FROM tenants t
    """))

    # ── Seed entitlements (15 credits per type) for each default policy
    op.execute(sa.text("""
        INSERT INTO leave_policy_entitlements (
            policy_id, leave_type_id, annual_credits,
            carry_over_enabled, max_carry_over_days, carry_over_expiry_months,
            cash_convertible, cash_conversion_rate,
            requires_documentation, min_notice_days,
            created_at, updated_at
        )
        SELECT
            lp.id,
            lt.id,
            15,
            false, 0, 0,
            false, 1.0,
            CASE WHEN lt.code = 'sick_leave' THEN true ELSE false END,
            0,
            now(),
            now()
        FROM leave_policies lp
        JOIN leave_types lt ON lt.tenant_id = lp.tenant_id
        WHERE lp.name = 'Standard'
    """))


def downgrade() -> None:
    op.drop_table("overtime_categories")
    op.drop_table("leave_policy_entitlements")
    op.drop_table("leave_policies")
    op.drop_table("leave_types")
