"""Make the permission matrix defaults match what each role can actually do

Revision ID: 059_permission_defaults
Revises: 058_export_transformations
Create Date: 2026-09-28

The Permissions screen was only enforced on attendance, policy rules, work
sites and data export; every other endpoint used a hard-coded role list. So the
seeded matrix could say "managers: schedules view only" while managers created,
moved and deleted shifts every day, and unticking a box changed nothing.

The matrix is now enforced everywhere. For that to change nothing on the day it
ships, the stored defaults must first describe today's behaviour. This moves
only rows that still hold the OLD seed value: a box an admin deliberately
changed is left exactly as they set it.
"""

from alembic import op
import sqlalchemy as sa

revision = "059_permission_defaults"
down_revision = "058_export_transformations"
branch_labels = None
depends_on = None

# (role_code, module): (old (view, create, edit, delete), new (...))
CHANGES = {
    ("hr", "schedules"): ((True, False, False, False), (True, True, True, True)),
    ("hr", "leave"): ((True, True, True, False), (True, True, True, True)),
    ("manager", "schedules"): ((True, False, False, False), (True, True, True, True)),
    ("schedule_editor", "schedules"): ((True, True, True, False), (True, True, True, True)),
    # Approving is governed by the approver chain now, not by leave:edit, so a
    # plain leave approver no longer needs config rights to do their job.
    ("leave_approver", "leave"): ((True, False, True, False), (True, False, False, False)),
    # Analytics were never open to leave approvers; the old seed said they were.
    ("leave_approver", "reports"): ((True, False, False, False), (False, False, False, False)),
}

_UPDATE = sa.text(
    """
    UPDATE role_permissions rp
       SET can_view = :nv, can_create = :nc, can_edit = :ne, can_delete = :nd
      FROM roles r
     WHERE rp.role_id = r.id
       AND r.is_system = true
       AND r.code = :code
       AND rp.module = :module
       AND rp.can_view = :ov AND rp.can_create = :oc
       AND rp.can_edit = :oe AND rp.can_delete = :od
    """
)


def _apply(direction: str) -> None:
    conn = op.get_bind()
    for (code, module), (old, new) in CHANGES.items():
        frm, to = (old, new) if direction == "up" else (new, old)
        conn.execute(
            _UPDATE,
            {
                "code": code,
                "module": module,
                "ov": frm[0], "oc": frm[1], "oe": frm[2], "od": frm[3],
                "nv": to[0], "nc": to[1], "ne": to[2], "nd": to[3],
            },
        )


def upgrade() -> None:
    _apply("up")


def downgrade() -> None:
    _apply("down")
