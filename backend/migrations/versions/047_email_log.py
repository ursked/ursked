"""Email delivery log

Revision ID: 047_email_log
Revises: 046_rebrand_site_name_ursked

One row per email send attempt (pending -> sent|failed) so operators can answer
"did that email go out?". No body column by design (bodies carry tokens).
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "047_email_log"
down_revision = "046_rebrand_site_name_ursked"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "email_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("type", sa.String(length=60), nullable=False),
        sa.Column("to_email", sa.String(length=255), nullable=False),
        sa.Column("subject", sa.String(length=500), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_email_logs_tenant_id", "email_logs", ["tenant_id"])
    op.create_index("ix_email_logs_type", "email_logs", ["type"])
    op.create_index("ix_email_logs_to_email", "email_logs", ["to_email"])
    op.create_index("ix_email_logs_status", "email_logs", ["status"])
    op.create_index("ix_email_logs_created_at", "email_logs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_email_logs_created_at", table_name="email_logs")
    op.drop_index("ix_email_logs_status", table_name="email_logs")
    op.drop_index("ix_email_logs_to_email", table_name="email_logs")
    op.drop_index("ix_email_logs_type", table_name="email_logs")
    op.drop_index("ix_email_logs_tenant_id", table_name="email_logs")
    op.drop_table("email_logs")
