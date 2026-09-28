"""Platform: email outbox, SMTP env fingerprint, housekeeping windows

Revision ID: 065_platform_jobs_outbox_housekeeping
Revises: 064_payroll_attendance_integrity
Create Date: 2026-09-29

All additive:

1. email_outbox. Emails are now queued in the transaction of the change they
   announce and delivered by the scheduler with retries (models/email_outbox.py).
   They used to be sent from a background task before the request committed.

2. site_settings.smtp_env_fingerprint. The SMTP_* environment bootstrap used
   to overwrite SMTP settings changed in the app on every restart. It now
   records what it wrote and leaves the settings alone once they differ.
   Existing rows start with NULL, which the bootstrap treats as "configured in
   the app": an upgrade can never overwrite a working mail setup.

3. app_settings: audit_log_retention_days (730), login_history_retention_days
   (180), read_notification_retention_days (90), the windows the new daily
   housekeeping job prunes by. Server defaults fill existing rows.

4. job_runs gets an index on started_at for the Background jobs view and the
   housekeeping prune.

Downgrade drops exactly these. Queued emails still in the outbox are lost on
downgrade (the old code has nowhere to send them from).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "065_platform_jobs_outbox_housekeeping"
down_revision = "064_payroll_attendance_integrity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "email_outbox",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "tenant_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True,
        ),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("to_email", sa.String(255), nullable=False),
        sa.Column("subject", sa.String(500), nullable=False),
        sa.Column("html_body", sa.Text(), nullable=True),
        sa.Column("text_body", sa.Text(), nullable=True),
        sa.Column("log_type", sa.String(60), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_email_outbox_tenant_id", "email_outbox", ["tenant_id"])
    op.create_index("ix_email_outbox_status_next", "email_outbox", ["status", "next_attempt_at"])

    op.add_column("site_settings", sa.Column("smtp_env_fingerprint", sa.String(64), nullable=True))

    op.add_column("app_settings", sa.Column(
        "audit_log_retention_days", sa.Integer(), nullable=False, server_default="730"))
    op.add_column("app_settings", sa.Column(
        "login_history_retention_days", sa.Integer(), nullable=False, server_default="180"))
    op.add_column("app_settings", sa.Column(
        "read_notification_retention_days", sa.Integer(), nullable=False, server_default="90"))

    op.create_index("ix_job_runs_started_at", "job_runs", ["started_at"])


def downgrade() -> None:
    op.drop_index("ix_job_runs_started_at", table_name="job_runs")
    op.drop_column("app_settings", "read_notification_retention_days")
    op.drop_column("app_settings", "login_history_retention_days")
    op.drop_column("app_settings", "audit_log_retention_days")
    op.drop_column("site_settings", "smtp_env_fingerprint")
    op.drop_index("ix_email_outbox_status_next", table_name="email_outbox")
    op.drop_index("ix_email_outbox_tenant_id", table_name="email_outbox")
    op.drop_table("email_outbox")
