"""User sessions — persistent login records

Revision ID: 051_user_sessions
Revises: 050_invite_token_hash

Tracks active sessions so users can see where they are signed in and revoke
individual ones. Linked to the JWT's JTI for per-session revocation.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "051_user_sessions"
down_revision = "050_invite_token_hash"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_sessions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id", sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "tenant_id", UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("jti", sa.String(64), nullable=False),
        sa.Column("ip_address", sa.String(50), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("login_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"])
    op.create_index("ix_user_sessions_tenant_id", "user_sessions", ["tenant_id"])
    op.create_index("ix_user_sessions_jti", "user_sessions", ["jti"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_user_sessions_jti", table_name="user_sessions")
    op.drop_index("ix_user_sessions_tenant_id", table_name="user_sessions")
    op.drop_index("ix_user_sessions_user_id", table_name="user_sessions")
    op.drop_table("user_sessions")
