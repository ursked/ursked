"""Administration is not operations: admin powers stop at running the system,
finance gets its own door, and a "Reports & data" role

Revision ID: 068_operational_portals
Revises: 067_admin_mode
Create Date: 2026-09-29

The owner's decision (2026-09-29): "Schedules are managed by managers under
their node. A manager for graphics is not an administrator of the app. The
usual functions of a non-admin account — Schedules, Leave approvals,
Attendance — should NOT be in the admin dashboard. Finance employees manage
finances on a separate dashboard too. Reports & Data ... should be available
(to those who have access) in the regular dashboard."

What this changes in the data (the rules themselves are in
app/services/permission_service.py and app/services/session_portal.py):

  * tenant_admin's role_permissions rows for schedules, finances and reports
    become all-false, and its leave row edit/delete only (= configuring leave).
    The code no longer reads tenant_admin's rows for those modules at all, and
    it bypassed them before, so these rows never decided anything: the
    Permissions screen locked the administrator row. They are rewritten so
    the screen shows what is true. Every tenant, whatever the rows held.
  * A new system role, report_viewer ("Reports & data"), for every tenant,
    with reports view/create/edit and nothing else, so a CEO or anyone who
    needs the numbers can have them without HR's or Finance's powers.
  * Role descriptions that still hold the old seed text are updated to say
    what each role now does.
  * user_sessions.portal (067, a free String(16)) gains a third value,
    'finance': a session opened at the finance sign-in page, with the same
    30-minute idle limit and 8-hour cap as an admin session, kept in the same
    admin_expires_at column (the absolute end of either privileged session).
    No schema change is needed.

Downgrade restores tenant_admin's rows to all-true and the old descriptions,
drops the report_viewer role (its assignments go with it: the older code does
not know the role) and ends every open finance session, which the older code
would otherwise read as an employee one.
"""

import sqlalchemy as sa
from alembic import op

revision = "068_operational_portals"
down_revision = "067_admin_mode"
branch_labels = None
depends_on = None

MODULES = ("employees", "organization", "schedules", "leave", "finances", "settings", "reports")

ADMIN_ROWS = {
    "schedules": (False, False, False, False),
    "leave": (False, False, True, True),
    "finances": (False, False, False, False),
    "reports": (False, False, False, False),
}

REPORT_VIEWER = {m: (False, False, False, False) for m in MODULES}
REPORT_VIEWER["reports"] = (True, True, True, False)

# code: (old seed description, new description)
DESCRIPTIONS = {
    "tenant_admin": (
        "Full tenant access, settings, and billing",
        "System administration: accounts, roles, organization, settings and policies. "
        "Not schedules, leave approvals, finances or reports",
    ),
    "hr": (
        "Payroll computations, onboarding, employee records access",
        "Employee records, schedules and leave for the whole company",
    ),
    "manager": (
        "Employee management for direct and indirect reports",
        "Schedules, leave and attendance for the teams they head",
    ),
    "finance": (
        "Payroll management, salary grades, deductions, and payroll processing",
        "Payroll, salary grades, deductions and pay rules, from the separate finance sign-in",
    ),
}


def _set_admin_rows(conn, rows) -> None:
    for module, (v, c, e, d) in rows.items():
        conn.execute(
            sa.text(
                """
                UPDATE role_permissions rp
                   SET can_view = :v, can_create = :c, can_edit = :e, can_delete = :d
                  FROM roles r
                 WHERE rp.role_id = r.id
                   AND r.code = 'tenant_admin'
                   AND rp.module = :module
                """
            ),
            {"module": module, "v": v, "c": c, "e": e, "d": d},
        )


def _set_descriptions(conn, direction: str) -> None:
    for code, (old, new) in DESCRIPTIONS.items():
        frm, to = (old, new) if direction == "up" else (new, old)
        conn.execute(
            sa.text(
                "UPDATE roles SET description = :to "
                "WHERE code = :code AND is_system = true AND description = :frm"
            ),
            {"code": code, "frm": frm, "to": to},
        )


def upgrade() -> None:
    conn = op.get_bind()

    _set_admin_rows(conn, ADMIN_ROWS)
    _set_descriptions(conn, "up")

    # One report_viewer role per tenant that lacks it, with its matrix rows.
    conn.execute(
        sa.text(
            """
            INSERT INTO roles (tenant_id, code, name, description, is_system, is_active, created_at)
            SELECT t.id, 'report_viewer', 'Reports & data',
                   'Runs and saves reports and reads the analytics', true, true, now()
              FROM tenants t
             WHERE NOT EXISTS (
                   SELECT 1 FROM roles r WHERE r.tenant_id = t.id AND r.code = 'report_viewer'
             )
            """
        )
    )
    for module, (v, c, e, d) in REPORT_VIEWER.items():
        conn.execute(
            sa.text(
                """
                INSERT INTO role_permissions
                       (tenant_id, role_id, module, can_view, can_create, can_edit, can_delete,
                        extra_permissions, created_at, updated_at)
                SELECT r.tenant_id, r.id, CAST(:module AS VARCHAR), :v, :c, :e, :d,
                       CAST('{}' AS JSONB), now(), now()
                  FROM roles r
                 WHERE r.code = 'report_viewer'
                   AND NOT EXISTS (
                       SELECT 1 FROM role_permissions rp
                        WHERE rp.role_id = r.id AND rp.module = CAST(:module AS VARCHAR)
                   )
                """
            ),
            {"module": module, "v": v, "c": c, "e": e, "d": d},
        )


def downgrade() -> None:
    conn = op.get_bind()

    _set_admin_rows(conn, {m: (True, True, True, True) for m in ADMIN_ROWS})
    _set_descriptions(conn, "down")

    # FKs from user_roles and role_permissions cascade.
    conn.execute(sa.text("DELETE FROM roles WHERE code = 'report_viewer'"))

    conn.execute(
        sa.text(
            "UPDATE user_sessions SET revoked_at = now() "
            "WHERE portal = 'finance' AND revoked_at IS NULL"
        )
    )
