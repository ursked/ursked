"""attendance records, overtime logs, tardiness records, policy rules, leave credit adjustments

Revision ID: 014_attendance_policy
Revises: 013_rbac_permissions
Create Date: 2026-02-01
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "014_attendance_policy"
down_revision = "013_rbac_permissions"
branch_labels = None
depends_on = None

# Default policy rules seeded per tenant
DEFAULT_POLICY_RULES = [
    {
        "name": "Holiday Overtime",
        "description": "Overtime during holidays applies holiday OT category",
        "rule_type": "overtime",
        "priority": 5,
        "conditions": [
            {"field": "overtime_minutes", "operator": "gt", "value": 0},
            {"field": "is_holiday", "operator": "eq", "value": True},
        ],
        "actions": [{"type": "apply_ot_category", "category_code": "holiday_ot"}],
    },
    {
        "name": "Regular Overtime",
        "description": "Non-holiday overtime applies regular OT category",
        "rule_type": "overtime",
        "priority": 10,
        "conditions": [
            {"field": "overtime_minutes", "operator": "gt", "value": 0},
            {"field": "is_holiday", "operator": "eq", "value": False},
            {"field": "is_special", "operator": "eq", "value": False},
        ],
        "actions": [{"type": "apply_ot_category", "category_code": "regular_ot"}],
    },
    {
        "name": "Tardiness Over 1 Hour",
        "description": "Late by more than 60 minutes results in leave deduction",
        "rule_type": "tardiness",
        "priority": 5,
        "conditions": [
            {"field": "tardiness_minutes", "operator": "gt", "value": 60},
        ],
        "actions": [{"type": "leave_deduction", "round_to_hours": 1}],
    },
    {
        "name": "Tardiness Under 1 Hour",
        "description": "Late by up to 60 minutes triggers a warning",
        "rule_type": "tardiness",
        "priority": 10,
        "conditions": [
            {"field": "tardiness_minutes", "operator": "gt", "value": 0},
            {"field": "tardiness_minutes", "operator": "lte", "value": 60},
        ],
        "actions": [{"type": "send_warning"}],
    },
]


def upgrade() -> None:
    # ── policy_rules ───────────────────────────────────────────────
    op.create_table(
        "policy_rules",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("rule_type", sa.String(50), nullable=False),
        sa.Column("priority", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("conditions", JSONB, nullable=False, server_default="[]"),
        sa.Column("actions", JSONB, nullable=False, server_default="[]"),
        sa.Column("employment_types", JSONB, nullable=True),
        sa.Column("created_by", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "name", name="uq_tenant_policy_rule_name"),
    )

    # ── attendance_records ─────────────────────────────────────────
    op.create_table(
        "attendance_records",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("employee_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("shift_id", sa.Integer, sa.ForeignKey("shifts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("actual_start_time", sa.Time, nullable=True),
        sa.Column("actual_end_time", sa.Time, nullable=True),
        sa.Column("scheduled_start_time", sa.Time, nullable=True),
        sa.Column("scheduled_end_time", sa.Time, nullable=True),
        sa.Column("hours_worked", sa.Float, nullable=True),
        sa.Column("tardiness_minutes", sa.Integer, nullable=False, server_default="0"),
        sa.Column("overtime_minutes", sa.Integer, nullable=False, server_default="0"),
        sa.Column("undertime_minutes", sa.Integer, nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="'present'"),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("recorded_by", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("employee_id", "date", name="uq_employee_attendance_date"),
    )

    # ── overtime_logs ──────────────────────────────────────────────
    op.create_table(
        "overtime_logs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("employee_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("attendance_record_id", sa.Integer, sa.ForeignKey("attendance_records.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("overtime_minutes", sa.Integer, nullable=False),
        sa.Column("overtime_category_id", sa.Integer, sa.ForeignKey("overtime_categories.id", ondelete="SET NULL"), nullable=True),
        sa.Column("pay_multiplier", sa.Float, nullable=True),
        sa.Column("pay_amount", sa.Float, nullable=True),
        sa.Column("leave_credits_earned", sa.Float, nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="'pending'"),
        sa.Column("approved_by", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ── tardiness_records ──────────────────────────────────────────
    op.create_table(
        "tardiness_records",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("employee_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("attendance_record_id", sa.Integer, sa.ForeignKey("attendance_records.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("tardiness_minutes", sa.Integer, nullable=False),
        sa.Column("resolution_type", sa.String(30), nullable=True),
        sa.Column("deduction_amount", sa.Float, nullable=True),
        sa.Column("leave_credits_deducted", sa.Float, nullable=True),
        sa.Column("policy_rule_id", sa.Integer, sa.ForeignKey("policy_rules.id", ondelete="SET NULL"), nullable=True),
        sa.Column("recorded_by", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ── leave_credit_adjustments ───────────────────────────────────
    op.create_table(
        "leave_credit_adjustments",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("employee_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("adjustment_type", sa.String(30), nullable=False),
        sa.Column("leave_type", sa.String(50), nullable=True),
        sa.Column("credits", sa.Float, nullable=False),
        sa.Column("source_id", sa.Integer, nullable=True),
        sa.Column("source_type", sa.String(30), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_by", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ── Seed default policy rules for all existing tenants ─────────
    import json

    conn = op.get_bind()
    tenants = conn.execute(sa.text("SELECT id FROM tenants")).fetchall()

    for (tenant_id,) in tenants:
        for rule in DEFAULT_POLICY_RULES:
            conn.execute(
                sa.text(
                    "INSERT INTO policy_rules (tenant_id, name, description, rule_type, priority, conditions, actions) "
                    "VALUES (:tid, :name, :desc, :rtype, :priority, :conditions, :actions) "
                    "ON CONFLICT (tenant_id, name) DO NOTHING"
                ),
                {
                    "tid": tenant_id,
                    "name": rule["name"],
                    "desc": rule["description"],
                    "rtype": rule["rule_type"],
                    "priority": rule["priority"],
                    "conditions": json.dumps(rule["conditions"]),
                    "actions": json.dumps(rule["actions"]),
                },
            )


def downgrade() -> None:
    op.drop_table("leave_credit_adjustments")
    op.drop_table("tardiness_records")
    op.drop_table("overtime_logs")
    op.drop_table("attendance_records")
    op.drop_table("policy_rules")
