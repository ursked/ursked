"""Session revocation column, hot-path composite indexes, 2FA backup code reset

Revision ID: 030_session_revocation_and_indexes
Revises: 029_schedule_break_offset
"""

from alembic import op
import sqlalchemy as sa

revision = "030_session_revocation_and_indexes"
down_revision = "029_schedule_break_offset"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Global session revocation ---------------------------------------
    # Any token issued before this instant is rejected. Lives on the row (not
    # in Redis) so revocation survives a cache outage.
    op.add_column(
        "users",
        sa.Column("tokens_valid_from", sa.DateTime(timezone=True), nullable=True),
    )

    # Existing tokens were minted before token-type enforcement and before
    # `iat` was included in the payload, so they must not remain valid.
    op.execute("UPDATE users SET tokens_valid_from = NOW()")

    # --- 2FA backup codes -------------------------------------------------
    # Codes are now stored as SHA-256 digests. Previously-stored plaintext
    # codes cannot be migrated (and should not be kept), so they are cleared;
    # affected users must re-run 2FA setup to obtain a fresh set.
    op.execute(
        "UPDATE user_two_factor SET backup_codes = NULL WHERE backup_codes IS NOT NULL"
    )

    # --- Hot-path composite indexes --------------------------------------
    op.create_index(
        "ix_attendance_records_tenant_date",
        "attendance_records",
        ["tenant_id", "date"],
    )
    op.create_index(
        "ix_schedule_change_requests_tenant_status",
        "schedule_change_requests",
        ["tenant_id", "status"],
    )
    op.create_index(
        "ix_leave_approver_assignments_tenant_approver",
        "leave_approver_assignments",
        ["tenant_id", "approver_id"],
    )
    op.create_index(
        "ix_shifts_tenant_date",
        "shifts",
        ["tenant_id", "date"],
    )
    op.create_index(
        "ix_leave_applications_tenant_status",
        "leave_applications",
        ["tenant_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_leave_applications_tenant_status", table_name="leave_applications")
    op.drop_index("ix_shifts_tenant_date", table_name="shifts")
    op.drop_index(
        "ix_leave_approver_assignments_tenant_approver",
        table_name="leave_approver_assignments",
    )
    op.drop_index(
        "ix_schedule_change_requests_tenant_status",
        table_name="schedule_change_requests",
    )
    op.drop_index("ix_attendance_records_tenant_date", table_name="attendance_records")
    op.drop_column("users", "tokens_valid_from")
