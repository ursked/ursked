"""Finance confidentiality: administrators lose the salary access setup gave them

Revision ID: 066_finance_confidentiality
Revises: 065_platform_jobs_outbox_housekeeping
Create Date: 2026-09-29

The owner's decision (2026-09): a tenant administrator sets payroll up but does
not see what anyone earns. Figures need a salary-viewer enrollment that another
person approved; an administrator can never grant it to themselves.

Until now every administrator was made a viewer AND an approver without anyone
approving it: migration 043's backfill, migration 056's CE repair and
SalaryEnrollmentService.seed_admin (first run) all insert the row with
granted_by NULL. New installs now seed approver only. This migration brings
existing installs to the same place:

  * revokes each tenant administrator's VIEWER enrollment that setup granted
    (granted_by IS NULL, and no approved viewer request of theirs on record,
    which also covers a grant whose approver's account was since deleted and
    so reads NULL through ON DELETE SET NULL). A viewer enrollment a person
    approved is left alone;
  * keeps their APPROVER enrollment, so every tenant still has someone who can
    approve requests (056's deadlock cannot come back);
  * writes an audit entry per revocation and tells each administrator in the
    app why their figures disappeared and how to ask for access.

What it revoked is recorded in finance_confidentiality_revocations so the
downgrade restores exactly those rows, and only while they are still in the
state this migration left them (revoked by nobody). The audit entries and the
notices stay on downgrade: they are history.
"""

from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "066_finance_confidentiality"
down_revision = "065_platform_jobs_outbox_housekeeping"
branch_labels = None
depends_on = None

RECORD_TABLE = "finance_confidentiality_revocations"

NOTICE_TITLE = "Salary figures now need another person's approval"
NOTICE_BODY = (
    "Being an administrator no longer shows salary figures. The salary access you "
    "were given automatically at setup has been removed; you can still set up "
    "payroll (deduction types, payout schedules, salary grade names and payroll "
    "periods) and approve other people's access. To see figures, open Finances, "
    "Salary Access and request access. Another approver must approve it: not you, "
    "and not someone you made an approver."
)

# Untyped where the value only round-trips (tenant_id comes back from the
# SELECT in whatever form the driver uses and goes straight back in).
_records = sa.table(
    RECORD_TABLE,
    sa.column("enrollment_id", sa.Integer),
    sa.column("tenant_id"),
    sa.column("user_id", sa.Integer),
    sa.column("revoked_at", sa.DateTime(timezone=True)),
)
_enrollments = sa.table(
    "salary_enrollments",
    sa.column("id", sa.Integer),
    sa.column("status", sa.String),
    sa.column("revoked_by", sa.Integer),
    sa.column("revoked_at", sa.DateTime(timezone=True)),
)
_audit = sa.table(
    "audit_logs",
    sa.column("tenant_id"),
    sa.column("user_id", sa.Integer),
    sa.column("action", sa.String),
    sa.column("resource_type", sa.String),
    sa.column("resource_id", sa.String),
    sa.column("details", postgresql.JSONB),
    sa.column("created_at", sa.DateTime(timezone=True)),
)
_notifications = sa.table(
    "notifications",
    sa.column("tenant_id"),
    sa.column("user_id", sa.Integer),
    sa.column("type", sa.String),
    sa.column("title", sa.String),
    sa.column("body", sa.Text),
    sa.column("is_read", sa.Boolean),
    sa.column("is_actioned", sa.Boolean),
    sa.column("created_at", sa.DateTime(timezone=True)),
)

# Setup-granted viewer enrollments of current tenant administrators.
_TARGETS = sa.text(
    """
    SELECT se.id, se.tenant_id, se.user_id
    FROM salary_enrollments se
    WHERE se.kind = 'viewer'
      AND se.status = 'active'
      AND se.granted_by IS NULL
      AND EXISTS (
          SELECT 1 FROM user_roles ur
          JOIN roles r ON r.id = ur.role_id
          WHERE ur.user_id = se.user_id
            AND r.code = 'tenant_admin'
            AND r.is_active = TRUE
      )
      AND NOT EXISTS (
          SELECT 1 FROM salary_enrollment_requests q
          WHERE q.tenant_id = se.tenant_id
            AND q.user_id = se.user_id
            AND q.kind = 'viewer'
            AND q.status = 'approved'
      )
    ORDER BY se.id
    """
)


def upgrade() -> None:
    op.create_table(
        RECORD_TABLE,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "enrollment_id", sa.Integer(),
            sa.ForeignKey("salary_enrollments.id", ondelete="CASCADE"),
            nullable=False, unique=True,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=False),
    )

    bind = op.get_bind()
    now = datetime.now(timezone.utc)
    for enrollment_id, tenant_id, user_id in bind.execute(_TARGETS).all():
        bind.execute(
            _enrollments.update()
            .where(_enrollments.c.id == enrollment_id)
            .values(status="revoked", revoked_by=None, revoked_at=now)
        )
        bind.execute(_records.insert().values(
            enrollment_id=enrollment_id, tenant_id=tenant_id, user_id=user_id, revoked_at=now,
        ))
        # No actor: the system did it, on the owner's decision.
        bind.execute(_audit.insert().values(
            tenant_id=tenant_id, user_id=None,
            action="salary_enrollment.bootstrap_revoked",
            resource_type="salary_enrollment", resource_id=str(enrollment_id),
            details={
                "kind": "viewer", "subject_id": user_id,
                "reason": "Administrators no longer see salary figures without "
                          "another person's approval.",
            },
            created_at=now,
        ))
        bind.execute(_notifications.insert().values(
            tenant_id=tenant_id, user_id=user_id, type="salary_enrollment_changed",
            title=NOTICE_TITLE, body=NOTICE_BODY,
            is_read=False, is_actioned=False, created_at=now,
        ))


def downgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.select(_records.c.enrollment_id, _records.c.revoked_at)).all()
    for enrollment_id, revoked_at in rows:
        # Only if still exactly as upgrade left it: a person may have granted
        # (and even revoked) it again since, and that decision stands.
        bind.execute(
            _enrollments.update()
            .where(
                _enrollments.c.id == enrollment_id,
                _enrollments.c.status == "revoked",
                _enrollments.c.revoked_by.is_(None),
                _enrollments.c.revoked_at == revoked_at,
            )
            .values(status="active", revoked_at=None)
        )
    op.drop_table(RECORD_TABLE)
