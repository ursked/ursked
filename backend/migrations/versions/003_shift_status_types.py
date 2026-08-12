"""Add shift_status_types table for tenant-configurable shift statuses.

Revision ID: 003_shift_status_types
Revises: 002_multi_role_permissions
Create Date: 2026-01-30
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '003_shift_status_types'
down_revision = '002_multi_role_permissions'
branch_labels = None
depends_on = None

# Default system status types seeded for every tenant
SYSTEM_DEFAULTS = [
    {
        "code": "scheduled",
        "label": "Scheduled",
        "short_label": "Sched",
        "color": "#7c3aed",
        "bg_class": "bg-purple-100 text-purple-800",
        "category": "work",
        "is_system": True,
        "sort_order": 0,
    },
    {
        "code": "rest_day",
        "label": "Rest Day",
        "short_label": "Rest",
        "color": "#6b7280",
        "bg_class": "bg-gray-100 text-gray-600",
        "category": "rest",
        "is_system": True,
        "sort_order": 1,
    },
]


def upgrade() -> None:
    # Create the shift_status_types table
    op.create_table(
        'shift_status_types',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('code', sa.String(50), nullable=False),
        sa.Column('label', sa.String(100), nullable=False),
        sa.Column('short_label', sa.String(10), nullable=False),
        sa.Column('color', sa.String(20), nullable=False),
        sa.Column('bg_class', sa.String(100), nullable=False),
        sa.Column('category', sa.String(20), nullable=False, server_default='leave'),
        sa.Column('is_system', sa.Boolean(), server_default='false'),
        sa.Column('is_active', sa.Boolean(), server_default='true'),
        sa.Column('sort_order', sa.Integer(), server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.UniqueConstraint('tenant_id', 'code', name='uq_tenant_status_code'),
    )

    # Seed default status types for all existing tenants
    conn = op.get_bind()
    tenants = conn.execute(sa.text("SELECT id FROM tenants")).fetchall()

    if tenants:
        for tenant in tenants:
            tenant_id = tenant[0]
            for d in SYSTEM_DEFAULTS:
                conn.execute(
                    sa.text("""
                        INSERT INTO shift_status_types
                            (tenant_id, code, label, short_label, color, bg_class, category, is_system, is_active, sort_order)
                        VALUES
                            (:tenant_id, :code, :label, :short_label, :color, :bg_class, :category, :is_system, true, :sort_order)
                    """),
                    {
                        "tenant_id": str(tenant_id),
                        "code": d["code"],
                        "label": d["label"],
                        "short_label": d["short_label"],
                        "color": d["color"],
                        "bg_class": d["bg_class"],
                        "category": d["category"],
                        "is_system": d["is_system"],
                        "sort_order": d["sort_order"],
                    },
                )


def downgrade() -> None:
    op.drop_table('shift_status_types')
