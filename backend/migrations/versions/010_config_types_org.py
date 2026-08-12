"""Add employee_types, schedule_formats, user_org_nodes tables.

Revision ID: 010_config_types_org
Revises: 009_leave_approval_chain
Create Date: 2026-01-31
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "010_config_types_org"
down_revision = "009_leave_approval_chain"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── employee_types ──────────────────────────────────────────────────
    op.create_table(
        "employee_types",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("is_system", sa.Boolean, server_default="false", nullable=False),
        sa.Column("is_active", sa.Boolean, server_default="true", nullable=False),
        sa.Column("sort_order", sa.Integer, server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "code", name="uq_tenant_employee_type_code"),
    )

    # ── schedule_formats ────────────────────────────────────────────────
    op.create_table(
        "schedule_formats",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("hours_per_day", sa.Float, nullable=True),
        sa.Column("hours_per_week", sa.Float, nullable=True),
        sa.Column("is_flexible", sa.Boolean, server_default="false", nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("is_system", sa.Boolean, server_default="false", nullable=False),
        sa.Column("is_active", sa.Boolean, server_default="true", nullable=False),
        sa.Column("sort_order", sa.Integer, server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "code", name="uq_tenant_schedule_format_code"),
    )

    # ── user_org_nodes (many-to-many) ───────────────────────────────────
    op.create_table(
        "user_org_nodes",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "org_node_id",
            sa.Integer,
            sa.ForeignKey("org_nodes.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("is_primary", sa.Boolean, server_default="false", nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "assigned_by",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.UniqueConstraint("user_id", "org_node_id", name="uq_user_org_node"),
    )

    # ── Seed employee_types per tenant ──────────────────────────────────
    op.execute("""
        INSERT INTO employee_types (tenant_id, code, name, is_system, is_active, sort_order, created_at, updated_at)
        SELECT t.id, et.code, et.name, et.is_sys, true, et.so, now(), now()
        FROM tenants t
        CROSS JOIN (VALUES
            ('regular',                    'Regular',                       true,  0),
            ('contractual',                'Contractual',                   true,  1),
            ('rank_and_file',              'Rank and File',                 false, 2),
            ('rank_and_file_probationary', 'Rank and File (Probationary)',  false, 3),
            ('confidential',               'Confidential',                  false, 4),
            ('confidential_probationary',  'Confidential (Probationary)',   false, 5)
        ) AS et(code, name, is_sys, so)
        ON CONFLICT DO NOTHING
    """)

    # ── Seed schedule_formats per tenant ────────────────────────────────
    op.execute("""
        INSERT INTO schedule_formats (
            tenant_id, code, name, hours_per_day, hours_per_week,
            is_flexible, is_system, is_active, sort_order, created_at, updated_at
        )
        SELECT t.id, sf.code, sf.name, sf.hpd, sf.hpw, sf.flex, true, true, sf.so, now(), now()
        FROM tenants t
        CROSS JOIN (VALUES
            ('4_hour',    '4-Hour Shift',    4.0,  20.0, false, 0),
            ('8_hour',    '8-Hour Shift',    8.0,  40.0, false, 1),
            ('9_hour',    '9-Hour Shift',    9.0,  45.0, false, 2),
            ('12_hour',   '12-Hour Shift',  12.0,  60.0, false, 3),
            ('flexible',  'Flexible Shift', NULL,  40.0, true,  4)
        ) AS sf(code, name, hpd, hpw, flex, so)
        ON CONFLICT DO NOTHING
    """)

    # ── Backfill user_org_nodes from existing user.org_node_id ──────────
    op.execute("""
        INSERT INTO user_org_nodes (user_id, org_node_id, is_primary, assigned_at)
        SELECT u.id, u.org_node_id, true, now()
        FROM users u
        WHERE u.org_node_id IS NOT NULL
        ON CONFLICT DO NOTHING
    """)


def downgrade() -> None:
    op.drop_table("user_org_nodes")
    op.drop_table("schedule_formats")
    op.drop_table("employee_types")
