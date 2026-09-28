"""Leave: ordered approver chains, an approval ledger, day breakdowns, work week

Revision ID: 063_leave_approvals_engine
Revises: 061_employees_custom_fields
Create Date: 2026-09-28

Four gaps from the 2026-09-28 audit need somewhere to live:

* An approver rule could hold exactly one approver. A two-level chain meant two
  rules at the same priority that happened to match together, so a rule's
  priority decided both WHICH rule applied and HOW LONG the chain was, and
  editing one rule silently changed another's chain. `leave_approver_rule_steps`
  gives each rule its own ordered list. Every existing rule gets one step copied
  from its own approver, so today's chains resolve exactly as before; the
  assignment's own approver columns are kept (and kept in sync with step 1) so a
  downgrade loses nothing.

* Overrides, reassignments, self-approvals, reminders, escalations and expiry
  had no record. `leave_approval_events` is shown on the request and doubles as
  the once-a-day reminder ledger (unique on step, action, day).

* Leave was counted Monday to Friday regardless of the roster or holidays, and a
  request spanning New Year consumed nothing. `leave_applications.day_breakdown`
  stores the per-day count so balances can split by year; `half_day` records
  AM/PM half days. Existing rows keep NULL and are read the old way.

* `app_settings.work_week_days` is the fallback for days with nothing on the
  roster; the two reminder settings drive the daily approval reminder job.

`leave_approver_assignments.deactivated_reason` says why the system switched a
rule off (its unit was deleted, its approver left) instead of deleting it.

Everything is additive. Downgrade drops only what this revision created.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "063_leave_approvals_engine"
down_revision = "061_employees_custom_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("leave_applications", sa.Column("half_day", sa.String(length=2), nullable=True))
    op.add_column("leave_applications", sa.Column("day_breakdown", sa.JSON(), nullable=True))

    op.add_column(
        "leave_approver_assignments",
        sa.Column("deactivated_reason", sa.Text(), nullable=True),
    )

    op.create_table(
        "leave_approver_rule_steps",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("assignment_id", sa.Integer(), nullable=False),
        sa.Column("step_order", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("approver_id", sa.Integer(), nullable=True),
        sa.Column("approver_role", sa.String(length=30), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["assignment_id"], ["leave_approver_assignments.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["approver_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_leave_approver_rule_steps_assignment_id",
        "leave_approver_rule_steps",
        ["assignment_id"],
    )
    # One step per existing rule, copied from the rule itself. step_order keeps
    # the rule's own value: the resolver merges legacy rules that share a scope
    # and priority by (rule step_order, step step_order), which reproduces the
    # chain those rules produced before this revision.
    op.execute(
        """
        INSERT INTO leave_approver_rule_steps (assignment_id, step_order, approver_id, approver_role, created_at)
        SELECT id, COALESCE(step_order, 1), approver_id, approver_role, NOW()
        FROM leave_approver_assignments
        WHERE COALESCE(exclude, false) = false
          AND (approver_id IS NOT NULL OR approver_role IS NOT NULL)
        """
    )

    op.create_table(
        "leave_approval_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("leave_application_id", sa.Integer(), nullable=False),
        sa.Column("step_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=30), nullable=False),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("from_approver_id", sa.Integer(), nullable=True),
        sa.Column("to_approver_id", sa.Integer(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("on_date", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["leave_application_id"], ["leave_applications.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["step_id"], ["leave_approval_steps.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["from_approver_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["to_approver_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_leave_approval_events_tenant_id", "leave_approval_events", ["tenant_id"])
    op.create_index(
        "ix_leave_approval_events_leave_application_id",
        "leave_approval_events",
        ["leave_application_id"],
    )
    op.create_index(
        "ix_leave_approval_events_once",
        "leave_approval_events",
        ["step_id", "action", "on_date"],
        unique=True,
    )

    # Steps left "pending" on requests that were cancelled or rejected at an
    # earlier step inflated every approver's "Pending my review" count. They
    # will never be decided: mark them skipped, as the code now does itself.
    op.execute(
        """
        UPDATE leave_approval_steps SET status = 'skipped'
        WHERE status = 'pending'
          AND leave_application_id IN (
              SELECT id FROM leave_applications WHERE status IN ('cancelled', 'rejected')
          )
        """
    )

    op.add_column(
        "app_settings",
        sa.Column(
            "work_week_days",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[0, 1, 2, 3, 4]'::jsonb"),
        ),
    )
    op.add_column(
        "app_settings",
        sa.Column("leave_reminder_after_days", sa.Integer(), nullable=False, server_default="2"),
    )
    op.add_column(
        "app_settings",
        sa.Column("leave_escalate_after_days", sa.Integer(), nullable=False, server_default="5"),
    )


def downgrade() -> None:
    op.drop_column("app_settings", "leave_escalate_after_days")
    op.drop_column("app_settings", "leave_reminder_after_days")
    op.drop_column("app_settings", "work_week_days")

    op.drop_index("ix_leave_approval_events_once", table_name="leave_approval_events")
    op.drop_index("ix_leave_approval_events_leave_application_id", table_name="leave_approval_events")
    op.drop_index("ix_leave_approval_events_tenant_id", table_name="leave_approval_events")
    op.drop_table("leave_approval_events")

    # Rules with more than one step cannot be represented once the steps table
    # is gone. Keep their first step on the rule itself, which is what an older
    # build reads, rather than leave a multi-step rule with no approver at all.
    op.execute(
        """
        UPDATE leave_approver_assignments a
        SET approver_id = s.approver_id, approver_role = s.approver_role
        FROM (
            SELECT DISTINCT ON (assignment_id) assignment_id, approver_id, approver_role
            FROM leave_approver_rule_steps
            ORDER BY assignment_id, step_order, id
        ) s
        WHERE s.assignment_id = a.id
        """
    )
    op.drop_index(
        "ix_leave_approver_rule_steps_assignment_id", table_name="leave_approver_rule_steps"
    )
    op.drop_table("leave_approver_rule_steps")

    op.drop_column("leave_approver_assignments", "deactivated_reason")

    # Older builds know no "skipped" step; they read it as not-yet-decided.
    op.execute("UPDATE leave_approval_steps SET status = 'pending' WHERE status = 'skipped'")
    # Nor an "expired" request: it was pending when it expired.
    op.execute("UPDATE leave_applications SET status = 'pending' WHERE status = 'expired'")

    op.drop_column("leave_applications", "day_breakdown")
    op.drop_column("leave_applications", "half_day")
