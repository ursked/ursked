"""Add flexible org hierarchy: org_levels, org_nodes tables, users.org_node_id.

Revision ID: 005_flexible_org_hierarchy
Revises: 004_user_preferences
Create Date: 2026-01-31
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "005_flexible_org_hierarchy"
down_revision = "004_user_preferences"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. org_levels: defines level names per tenant (1-6 levels)
    op.create_table(
        "org_levels",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("level_number", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("tenant_id", "level_number", name="uq_tenant_level_number"),
        sa.CheckConstraint(
            "level_number >= 1 AND level_number <= 6", name="ck_level_number_range"
        ),
    )
    op.create_index("ix_org_levels_tenant_id", "org_levels", ["tenant_id"])

    # 2. org_nodes: adjacency-list hierarchy
    op.create_table(
        "org_nodes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "parent_id",
            sa.Integer(),
            sa.ForeignKey("org_nodes.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "level_id",
            sa.Integer(),
            sa.ForeignKey("org_levels.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("code", sa.String(50), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "head_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "deputy_head_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("sort_order", sa.Integer(), server_default="0"),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_org_nodes_tenant_id", "org_nodes", ["tenant_id"])
    op.create_index("ix_org_nodes_parent_id", "org_nodes", ["parent_id"])
    op.create_index("ix_org_nodes_level_id", "org_nodes", ["level_id"])
    op.create_index("ix_org_nodes_head_user_id", "org_nodes", ["head_user_id"])

    # Partial unique index on (tenant_id, code) WHERE code IS NOT NULL
    op.execute(
        "CREATE UNIQUE INDEX uq_org_nodes_tenant_code "
        "ON org_nodes (tenant_id, code) WHERE code IS NOT NULL"
    )

    # 3. Add org_node_id to users
    op.add_column(
        "users",
        sa.Column(
            "org_node_id",
            sa.Integer(),
            sa.ForeignKey("org_nodes.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_users_org_node_id", "users", ["org_node_id"])


def downgrade() -> None:
    op.drop_index("ix_users_org_node_id", table_name="users")
    op.drop_column("users", "org_node_id")
    op.execute("DROP INDEX IF EXISTS uq_org_nodes_tenant_code")
    op.drop_table("org_nodes")
    op.drop_table("org_levels")
