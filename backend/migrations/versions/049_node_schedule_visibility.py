"""Per-node schedule visibility: explicit grants + per-node override

Revision ID: 049_node_schedule_visibility
Revises: 048_password_reset_tokens

Two related pieces:
  * node_schedule_visibility: explicit grants letting a user view a specific org
    node's schedule (and, by default, its subtree) beyond the built-in admin /
    node-head / tenant-setting scoping.
  * org_nodes.schedule_visibility: a per-node override of the tenant-wide
    visibility mode (NULL = inherit from ancestors / tenant default).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "049_node_schedule_visibility"
down_revision = "048_password_reset_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "org_nodes",
        sa.Column("schedule_visibility", sa.String(length=20), nullable=True),
    )
    op.create_table(
        "node_schedule_visibility",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "org_node_id",
            sa.Integer(),
            sa.ForeignKey("org_nodes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "include_descendants",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.UniqueConstraint("user_id", "org_node_id", name="uq_node_schedule_visibility"),
    )
    op.create_index(
        "ix_node_schedule_visibility_tenant_id", "node_schedule_visibility", ["tenant_id"]
    )
    op.create_index(
        "ix_node_schedule_visibility_user_id", "node_schedule_visibility", ["user_id"]
    )
    op.create_index(
        "ix_node_schedule_visibility_org_node_id", "node_schedule_visibility", ["org_node_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_node_schedule_visibility_org_node_id", table_name="node_schedule_visibility")
    op.drop_index("ix_node_schedule_visibility_user_id", table_name="node_schedule_visibility")
    op.drop_index("ix_node_schedule_visibility_tenant_id", table_name="node_schedule_visibility")
    op.drop_table("node_schedule_visibility")
    op.drop_column("org_nodes", "schedule_visibility")
