"""Add payroll system tables: salary_grades, employee_salaries, deduction_types, payroll_periods, payroll_items.

Revision ID: 012_payroll_system
Revises: 011_schedule_break_times
Create Date: 2026-02-01
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "012_payroll_system"
down_revision = "011_schedule_break_times"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── salary_grades ─────────────────────────────────────────────
    op.create_table(
        "salary_grades",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("monthly_rate", sa.Float, nullable=False),
        sa.Column("daily_rate", sa.Float, nullable=True),
        sa.Column("hourly_rate", sa.Float, nullable=True),
        sa.Column("is_active", sa.Boolean, server_default="true", nullable=False),
        sa.Column("sort_order", sa.Integer, server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", "code", name="uq_salary_grades_tenant_code"),
    )

    # ── employee_salaries ─────────────────────────────────────────
    op.create_table(
        "employee_salaries",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("employee_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("salary_grade_id", sa.Integer, sa.ForeignKey("salary_grades.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("effective_date", sa.Date, nullable=False),
        sa.Column("monthly_rate_override", sa.Float, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.UniqueConstraint("employee_id", "effective_date", name="uq_employee_salary_date"),
    )

    # ── deduction_types ───────────────────────────────────────────
    op.create_table(
        "deduction_types",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("calculation_type", sa.String(20), nullable=False, server_default="fixed"),
        sa.Column("default_amount", sa.Float, nullable=True),
        sa.Column("default_rate", sa.Float, nullable=True),
        sa.Column("is_mandatory", sa.Boolean, server_default="false", nullable=False),
        sa.Column("is_employer_contribution", sa.Boolean, server_default="false", nullable=False),
        sa.Column("is_system", sa.Boolean, server_default="false", nullable=False),
        sa.Column("is_active", sa.Boolean, server_default="true", nullable=False),
        sa.Column("sort_order", sa.Integer, server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", "code", name="uq_deduction_types_tenant_code"),
    )

    # ── payroll_periods ───────────────────────────────────────────
    op.create_table(
        "payroll_periods",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("period_type", sa.String(20), nullable=False, server_default="monthly"),
        sa.Column("start_date", sa.Date, nullable=False),
        sa.Column("end_date", sa.Date, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("computed_by", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finalized_by", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", "start_date", "end_date", name="uq_payroll_period_range"),
    )

    # ── payroll_items ─────────────────────────────────────────────
    op.create_table(
        "payroll_items",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("payroll_period_id", sa.Integer, sa.ForeignKey("payroll_periods.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("employee_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("salary_grade_id", sa.Integer, sa.ForeignKey("salary_grades.id", ondelete="SET NULL"), nullable=True),
        sa.Column("base_pay", sa.Float, nullable=False, server_default="0"),
        sa.Column("overtime_pay", sa.Float, nullable=False, server_default="0"),
        sa.Column("gross_pay", sa.Float, nullable=False, server_default="0"),
        sa.Column("total_deductions", sa.Float, nullable=False, server_default="0"),
        sa.Column("total_contributions", sa.Float, nullable=False, server_default="0"),
        sa.Column("net_pay", sa.Float, nullable=False, server_default="0"),
        sa.Column("breakdown", JSONB, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.UniqueConstraint("payroll_period_id", "employee_id", name="uq_payroll_item_period_emp"),
    )

    # ── Seed finance role for all existing tenants ────────────────
    op.execute("""
        INSERT INTO roles (tenant_id, code, name, description, is_system, is_active)
        SELECT t.id, 'finance', 'Finance', 'Payroll management, salary grades, deductions, and payroll processing', true, true
        FROM tenants t
        WHERE NOT EXISTS (
            SELECT 1 FROM roles r WHERE r.tenant_id = t.id AND r.code = 'finance'
        )
    """)

    # ── Seed default deduction types for all existing tenants ─────
    op.execute("""
        INSERT INTO deduction_types (tenant_id, code, name, description, calculation_type, default_amount, default_rate, is_mandatory, is_employer_contribution, is_system, sort_order)
        SELECT t.id, 'sss', 'SSS', 'Social Security System contribution', 'fixed', 1125, NULL, true, false, true, 1
        FROM tenants t
        WHERE NOT EXISTS (
            SELECT 1 FROM deduction_types d WHERE d.tenant_id = t.id AND d.code = 'sss'
        )
    """)
    op.execute("""
        INSERT INTO deduction_types (tenant_id, code, name, description, calculation_type, default_amount, default_rate, is_mandatory, is_employer_contribution, is_system, sort_order)
        SELECT t.id, 'sss_employer', 'SSS (Employer Share)', 'Social Security System employer contribution', 'fixed', 1375, NULL, true, true, true, 2
        FROM tenants t
        WHERE NOT EXISTS (
            SELECT 1 FROM deduction_types d WHERE d.tenant_id = t.id AND d.code = 'sss_employer'
        )
    """)
    op.execute("""
        INSERT INTO deduction_types (tenant_id, code, name, description, calculation_type, default_amount, default_rate, is_mandatory, is_employer_contribution, is_system, sort_order)
        SELECT t.id, 'philhealth', 'PhilHealth', 'Philippine Health Insurance Corporation contribution', 'percentage', NULL, 0.025, true, false, true, 3
        FROM tenants t
        WHERE NOT EXISTS (
            SELECT 1 FROM deduction_types d WHERE d.tenant_id = t.id AND d.code = 'philhealth'
        )
    """)
    op.execute("""
        INSERT INTO deduction_types (tenant_id, code, name, description, calculation_type, default_amount, default_rate, is_mandatory, is_employer_contribution, is_system, sort_order)
        SELECT t.id, 'philhealth_employer', 'PhilHealth (Employer Share)', 'PhilHealth employer contribution', 'percentage', NULL, 0.025, true, true, true, 4
        FROM tenants t
        WHERE NOT EXISTS (
            SELECT 1 FROM deduction_types d WHERE d.tenant_id = t.id AND d.code = 'philhealth_employer'
        )
    """)
    op.execute("""
        INSERT INTO deduction_types (tenant_id, code, name, description, calculation_type, default_amount, default_rate, is_mandatory, is_employer_contribution, is_system, sort_order)
        SELECT t.id, 'pagibig', 'Pag-IBIG', 'Home Development Mutual Fund contribution', 'fixed', 100, NULL, true, false, true, 5
        FROM tenants t
        WHERE NOT EXISTS (
            SELECT 1 FROM deduction_types d WHERE d.tenant_id = t.id AND d.code = 'pagibig'
        )
    """)
    op.execute("""
        INSERT INTO deduction_types (tenant_id, code, name, description, calculation_type, default_amount, default_rate, is_mandatory, is_employer_contribution, is_system, sort_order)
        SELECT t.id, 'pagibig_employer', 'Pag-IBIG (Employer Share)', 'Pag-IBIG employer contribution', 'fixed', 100, NULL, true, true, true, 6
        FROM tenants t
        WHERE NOT EXISTS (
            SELECT 1 FROM deduction_types d WHERE d.tenant_id = t.id AND d.code = 'pagibig_employer'
        )
    """)
    op.execute("""
        INSERT INTO deduction_types (tenant_id, code, name, description, calculation_type, default_amount, default_rate, is_mandatory, is_employer_contribution, is_system, sort_order)
        SELECT t.id, 'wtax', 'Withholding Tax', 'Withholding tax on compensation', 'fixed', 0, NULL, true, false, true, 7
        FROM tenants t
        WHERE NOT EXISTS (
            SELECT 1 FROM deduction_types d WHERE d.tenant_id = t.id AND d.code = 'wtax'
        )
    """)


def downgrade() -> None:
    op.drop_table("payroll_items")
    op.drop_table("payroll_periods")
    op.drop_table("employee_salaries")
    op.drop_table("salary_grades")
    op.drop_table("deduction_types")
    # Finance role and deduction seed data are left in place on downgrade
