"""Repair tenants left with no salary approver (CE bootstrap deadlock).

Salary access is deliberately double-gated: `require_salary_access` needs an active
'viewer' enrollment and `require_salary_approver` needs an active 'approver', and
NEITHER bypasses tenant_admin. That separation of duties is intentional, but it only
works if somebody is an approver to begin with.

Two things create that first approver, and neither fires on a Community install:

  * migration 043 backfills every tenant_admin as viewer + approver — but on a fresh
    install the entrypoint runs migrations BEFORE seed_ce.py creates the tenant and
    the admin, so the backfill matches zero rows;
  * `SalaryEnrollmentService.seed_admin()` is called from app/ee/api/tenants.py on
    tenant provisioning — and CE is produced by deleting backend/app/ee/.

So `salary_enrollments` stays empty for ever. With no approver, no enrollment request
can be approved, so no viewer can be created, so the whole payroll module answers 403
to everyone including the administrator, with no route out from inside the product.

seed_ce.py now seeds the enrollment for new installs. This migration repairs the ones
already out there. It is deliberately narrow: it only touches a tenant that has NO
active approver at all, so a deployment that has appointed real approvers (and quite
reasonably removed the admin) is left exactly as it is.
"""

from alembic import op

revision = "056_ce_salary_bootstrap"
down_revision = "055_unique_short_labels"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Only for tenants with no active approver — see the module docstring. The
    # ON CONFLICT clause matches the unique (tenant_id, user_id, kind) from 043, so
    # a revoked row is left revoked rather than being silently reactivated.
    op.execute(
        """
        INSERT INTO salary_enrollments (tenant_id, user_id, kind, status, granted_by, granted_at)
        SELECT DISTINCT u.tenant_id, u.id, k.kind, 'active', NULL::integer, NOW()
        FROM users u
        JOIN user_roles ur ON ur.user_id = u.id
        JOIN roles r ON r.id = ur.role_id AND r.code = 'tenant_admin' AND r.is_active = true
        CROSS JOIN (SELECT 'viewer' AS kind UNION ALL SELECT 'approver') k
        WHERE NOT EXISTS (
            SELECT 1 FROM salary_enrollments se
            WHERE se.tenant_id = u.tenant_id
              AND se.kind = 'approver'
              AND se.status = 'active'
        )
        ON CONFLICT (tenant_id, user_id, kind) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO audit_logs (tenant_id, user_id, action, resource_type, resource_id, details, created_at)
        SELECT se.tenant_id, se.user_id, 'salary_enrollment.seeded', 'salary_enrollment',
               CAST(se.id AS VARCHAR),
               jsonb_build_object('kind', se.kind, 'bootstrap', true, 'repair', true), NOW()
        FROM salary_enrollments se
        WHERE se.granted_by IS NULL
          AND se.granted_at >= NOW() - INTERVAL '1 minute'
        """
    )


def downgrade() -> None:
    # Nothing to undo. Removing the enrollments would recreate the deadlock, and the
    # rows are indistinguishable from a legitimate 043 bootstrap.
    pass
