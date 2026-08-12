"""Add role_permissions table for module-action RBAC.

Revision ID: 013_rbac_permissions
Revises: 012_payroll_system
Create Date: 2026-02-01
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "013_rbac_permissions"
down_revision = "012_payroll_system"
branch_labels = None
depends_on = None

# Default permission matrix: role_code -> {module: (can_view, can_create, can_edit, can_delete, extra)}
PERMISSION_MATRIX = {
    "tenant_admin": {
        "employees": (True, True, True, True, {"view_salary": True}),
        "organization": (True, True, True, True, {}),
        "schedules": (True, True, True, True, {}),
        "leave": (True, True, True, True, {}),
        "finances": (True, True, True, True, {}),
        "settings": (True, True, True, True, {}),
        "reports": (True, True, True, True, {}),
    },
    "hr": {
        "employees": (True, True, True, False, {"view_salary": True}),
        "organization": (True, True, True, False, {}),
        "schedules": (True, False, False, False, {}),
        "leave": (True, True, True, False, {}),
        "finances": (True, False, False, False, {}),
        "settings": (True, False, False, False, {}),
        "reports": (True, True, True, False, {}),
    },
    "finance": {
        "employees": (True, False, False, False, {"view_salary": True}),
        "organization": (True, False, False, False, {}),
        "schedules": (False, False, False, False, {}),
        "leave": (True, False, False, False, {}),
        "finances": (True, True, True, True, {}),
        "settings": (True, False, False, False, {}),
        "reports": (True, True, True, False, {}),
    },
    "manager": {
        "employees": (True, False, False, False, {}),
        "organization": (True, False, False, False, {}),
        "schedules": (True, False, False, False, {}),
        "leave": (True, False, False, False, {}),
        "finances": (False, False, False, False, {}),
        "settings": (False, False, False, False, {}),
        "reports": (True, False, False, False, {}),
    },
    "schedule_editor": {
        "employees": (True, False, False, False, {}),
        "organization": (False, False, False, False, {}),
        "schedules": (True, True, True, False, {}),
        "leave": (True, False, False, False, {}),
        "finances": (False, False, False, False, {}),
        "settings": (False, False, False, False, {}),
        "reports": (False, False, False, False, {}),
    },
    "leave_approver": {
        "employees": (True, False, False, False, {}),
        "organization": (False, False, False, False, {}),
        "schedules": (True, False, False, False, {}),
        "leave": (True, False, True, False, {}),
        "finances": (False, False, False, False, {}),
        "settings": (False, False, False, False, {}),
        "reports": (True, False, False, False, {}),
    },
    "employee": {
        "employees": (False, False, False, False, {}),
        "organization": (False, False, False, False, {}),
        "schedules": (False, False, False, False, {}),
        "leave": (False, False, False, False, {}),
        "finances": (False, False, False, False, {}),
        "settings": (False, False, False, False, {}),
        "reports": (False, False, False, False, {}),
    },
}


def upgrade() -> None:
    op.create_table(
        "role_permissions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("role_id", sa.Integer, sa.ForeignKey("roles.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("module", sa.String(50), nullable=False),
        sa.Column("can_view", sa.Boolean, server_default="false", nullable=False),
        sa.Column("can_create", sa.Boolean, server_default="false", nullable=False),
        sa.Column("can_edit", sa.Boolean, server_default="false", nullable=False),
        sa.Column("can_delete", sa.Boolean, server_default="false", nullable=False),
        sa.Column("extra_permissions", JSONB, nullable=True, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("role_id", "module", name="uq_role_permission_module"),
    )

    # Seed default permissions for all existing tenants
    conn = op.get_bind()

    # Get all tenant+role pairs
    rows = conn.execute(
        sa.text("SELECT t.id AS tenant_id, r.id AS role_id, r.code AS role_code FROM tenants t JOIN roles r ON r.tenant_id = t.id WHERE r.is_system = true")
    ).fetchall()

    import json

    for row in rows:
        tenant_id = row.tenant_id
        role_id = row.role_id
        role_code = row.role_code

        perms = PERMISSION_MATRIX.get(role_code, {})
        for module, (v, c, e, d, extra) in perms.items():
            extra_json = json.dumps(extra) if extra else '{}'
            conn.execute(
                sa.text(
                    "INSERT INTO role_permissions (tenant_id, role_id, module, can_view, can_create, can_edit, can_delete, extra_permissions) "
                    "VALUES (:tenant_id, :role_id, :module, :can_view, :can_create, :can_edit, :can_delete, CAST(:extra AS jsonb)) "
                    "ON CONFLICT (role_id, module) DO NOTHING"
                ),
                {
                    "tenant_id": tenant_id,
                    "role_id": role_id,
                    "module": module,
                    "can_view": v,
                    "can_create": c,
                    "can_edit": e,
                    "can_delete": d,
                    "extra": extra_json,
                },
            )


def downgrade() -> None:
    op.drop_table("role_permissions")
