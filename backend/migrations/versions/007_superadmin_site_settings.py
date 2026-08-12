"""Add superadmin flag, site_settings table, and audit_logs table.

Revision ID: 007_superadmin_site_settings
Revises: 006_expand_org_levels_to_9
Create Date: 2026-01-31
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "007_superadmin_site_settings"
down_revision = "006_expand_org_levels_to_9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add is_superadmin to users
    op.add_column("users", sa.Column("is_superadmin", sa.Boolean(), nullable=False, server_default="false"))

    # Create site_settings table (singleton — one row)
    op.create_table(
        "site_settings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        # General
        sa.Column("site_name", sa.String(200), nullable=False, server_default="SchedulePro"),
        sa.Column("site_description", sa.Text(), nullable=True),
        sa.Column("site_timezone", sa.String(100), nullable=False, server_default="UTC"),
        sa.Column("primary_domain", sa.String(255), nullable=True),
        sa.Column("base_url", sa.String(255), nullable=True),
        sa.Column("allowed_domains", sa.Text(), nullable=True),
        sa.Column("support_email", sa.String(255), nullable=True),
        sa.Column("registration_enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("maintenance_mode", sa.Boolean(), nullable=False, server_default="false"),
        # SMTP
        sa.Column("smtp_active", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("smtp_host", sa.String(255), nullable=True),
        sa.Column("smtp_port", sa.Integer(), nullable=False, server_default="587"),
        sa.Column("smtp_use_ssl", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("smtp_use_tls", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("smtp_username", sa.String(255), nullable=True),
        sa.Column("smtp_password", sa.String(255), nullable=True),
        sa.Column("smtp_from_email", sa.String(255), nullable=True),
        sa.Column("smtp_from_name", sa.String(200), nullable=True),
        sa.Column("smtp_admin_notification_email", sa.String(255), nullable=True),
        # Database backup
        sa.Column("db_backup_enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("db_backup_frequency", sa.String(50), nullable=False, server_default="daily"),
        sa.Column("db_backup_time", sa.String(10), nullable=False, server_default="02:00"),
        sa.Column("db_backup_retention_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("db_backup_path", sa.String(500), nullable=True),
        # Application backup
        sa.Column("app_backup_enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("app_backup_frequency", sa.String(50), nullable=False, server_default="weekly"),
        sa.Column("app_backup_retention_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("app_backup_path", sa.String(500), nullable=True),
        # Notifications
        sa.Column("notify_on_backup_failure", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("notification_email", sa.String(255), nullable=True),
        # Timestamps
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Create audit_logs table
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("user_email", sa.String(255), nullable=True),
        sa.Column("action", sa.String(100), nullable=False, index=True),
        sa.Column("resource_type", sa.String(100), nullable=True),
        sa.Column("resource_id", sa.String(100), nullable=True),
        sa.Column("details", JSONB, nullable=True),
        sa.Column("ip_address", sa.String(50), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), index=True),
    )


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("site_settings")
    op.drop_column("users", "is_superadmin")
