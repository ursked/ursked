"""Multi-role permissions and reporting hierarchy

Revision ID: 002_multi_role_permissions
Revises: 001_create_saas_schema
Create Date: 2026-01-29 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '002_multi_role_permissions'
down_revision: Union[str, None] = '001_create_saas_schema'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---- Phase 1: Create new tables and add new columns ----

    # Roles table
    op.create_table(
        'roles',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('code', sa.String(50), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_system', sa.Boolean(), server_default='true'),
        sa.Column('is_active', sa.Boolean(), server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.UniqueConstraint('tenant_id', 'code', name='uq_tenant_role_code'),
    )
    op.create_index('ix_roles_tenant_id', 'roles', ['tenant_id'])

    # User roles junction table
    op.create_table(
        'user_roles',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('role_id', sa.Integer(), sa.ForeignKey('roles.id', ondelete='CASCADE'), nullable=False),
        sa.Column('title', sa.String(100), nullable=True),
        sa.Column('assigned_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('assigned_by', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.UniqueConstraint('user_id', 'role_id', name='uq_user_role'),
    )
    op.create_index('ix_user_roles_user_id', 'user_roles', ['user_id'])
    op.create_index('ix_user_roles_role_id', 'user_roles', ['role_id'])

    # Leave approval steps table
    op.create_table(
        'leave_approval_steps',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('leave_application_id', sa.Integer(), sa.ForeignKey('leave_applications.id', ondelete='CASCADE'), nullable=False),
        sa.Column('approver_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('step_order', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )
    op.create_index('ix_leave_approval_steps_leave_id', 'leave_approval_steps', ['leave_application_id'])

    # Add reports_to_id to users
    op.add_column('users', sa.Column('reports_to_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True))
    op.create_index('ix_users_reports_to_id', 'users', ['reports_to_id'])

    # Add company detail columns to tenants
    op.add_column('tenants', sa.Column('industry', sa.String(100), nullable=True))
    op.add_column('tenants', sa.Column('company_size', sa.String(50), nullable=True))
    op.add_column('tenants', sa.Column('country', sa.String(100), nullable=True))
    op.add_column('tenants', sa.Column('timezone', sa.String(100), nullable=True))

    # ---- Phase 2: Migrate existing data ----

    conn = op.get_bind()

    # Seed system roles for every existing tenant
    tenants = conn.execute(sa.text("SELECT id FROM tenants")).fetchall()
    system_roles = [
        ("employee", "Employee", "Base role assigned to every user"),
        ("tenant_admin", "Tenant Administrator", "Full tenant access, settings, and billing"),
        ("hr", "HR", "Payroll computations, onboarding, employee records access"),
        ("manager", "Manager", "Employee management for direct and indirect reports"),
        ("leave_approver", "Leave Approver", "Can approve leave applications for reports in their chain"),
        ("schedule_editor", "Schedule Editor", "Can create and edit schedules"),
    ]
    for (tenant_id,) in tenants:
        for code, name, desc in system_roles:
            conn.execute(sa.text(
                "INSERT INTO roles (tenant_id, code, name, description, is_system) "
                "VALUES (:tid, :code, :name, :desc, true)"
            ), {"tid": tenant_id, "code": code, "name": name, "desc": desc})

    # Migrate user roles from old role column to user_roles junction table
    users = conn.execute(sa.text(
        "SELECT id, tenant_id, role, is_section_approver, is_unit_approver, "
        "is_department_approver, is_division_approver FROM users"
    )).fetchall()

    for user_id, tenant_id, old_role, is_sec, is_unit, is_dept, is_div in users:
        # Everyone gets employee role
        conn.execute(sa.text(
            "INSERT INTO user_roles (user_id, role_id) "
            "SELECT :uid, r.id FROM roles r WHERE r.tenant_id = :tid AND r.code = 'employee'"
        ), {"uid": user_id, "tid": tenant_id})

        # Map old role values to new role codes
        if old_role in ("administrator", "super_admin"):
            conn.execute(sa.text(
                "INSERT INTO user_roles (user_id, role_id) "
                "SELECT :uid, r.id FROM roles r WHERE r.tenant_id = :tid AND r.code = 'tenant_admin'"
            ), {"uid": user_id, "tid": tenant_id})
        elif old_role == "manager":
            conn.execute(sa.text(
                "INSERT INTO user_roles (user_id, role_id) "
                "SELECT :uid, r.id FROM roles r WHERE r.tenant_id = :tid AND r.code = 'manager'"
            ), {"uid": user_id, "tid": tenant_id})

        # If any approver flag was set, assign leave_approver role
        if any([is_sec, is_unit, is_dept, is_div]):
            conn.execute(sa.text(
                "INSERT INTO user_roles (user_id, role_id) "
                "SELECT :uid, r.id FROM roles r WHERE r.tenant_id = :tid AND r.code = 'leave_approver'"
            ), {"uid": user_id, "tid": tenant_id})

    # Migrate existing leave approval data to leave_approval_steps
    leave_apps = conn.execute(sa.text(
        "SELECT id, section_approved_by, section_approved, section_approved_at, "
        "unit_approved_by, unit_approved, unit_approved_at FROM leave_applications "
        "WHERE section_approved_by IS NOT NULL OR unit_approved_by IS NOT NULL"
    )).fetchall()

    for la_id, sec_by, sec_approved, sec_at, unit_by, unit_approved, unit_at in leave_apps:
        step_order = 1
        if sec_by is not None:
            status = "approved" if sec_approved else "rejected"
            conn.execute(sa.text(
                "INSERT INTO leave_approval_steps (leave_application_id, approver_id, step_order, status, decided_at) "
                "VALUES (:la_id, :approver, :step, :status, :decided_at)"
            ), {"la_id": la_id, "approver": sec_by, "step": step_order, "status": status, "decided_at": sec_at})
            step_order += 1
        if unit_by is not None:
            status = "approved" if unit_approved else "rejected"
            conn.execute(sa.text(
                "INSERT INTO leave_approval_steps (leave_application_id, approver_id, step_order, status, decided_at) "
                "VALUES (:la_id, :approver, :step, :status, :decided_at)"
            ), {"la_id": la_id, "approver": unit_by, "step": step_order, "status": status, "decided_at": unit_at})

    # ---- Phase 3: Drop old columns ----

    op.drop_column('users', 'role')
    op.drop_column('users', 'is_section_approver')
    op.drop_column('users', 'is_unit_approver')
    op.drop_column('users', 'is_department_approver')
    op.drop_column('users', 'is_division_approver')

    op.drop_column('leave_applications', 'section_approved_by')
    op.drop_column('leave_applications', 'section_approved')
    op.drop_column('leave_applications', 'section_approved_at')
    op.drop_column('leave_applications', 'unit_approved_by')
    op.drop_column('leave_applications', 'unit_approved')
    op.drop_column('leave_applications', 'unit_approved_at')


def downgrade() -> None:
    # Add back old columns
    op.add_column('users', sa.Column('role', sa.String(50), nullable=True, server_default='employee'))
    op.add_column('users', sa.Column('is_section_approver', sa.Boolean(), server_default='false'))
    op.add_column('users', sa.Column('is_unit_approver', sa.Boolean(), server_default='false'))
    op.add_column('users', sa.Column('is_department_approver', sa.Boolean(), server_default='false'))
    op.add_column('users', sa.Column('is_division_approver', sa.Boolean(), server_default='false'))

    op.add_column('leave_applications', sa.Column('section_approved_by', sa.Integer(), nullable=True))
    op.add_column('leave_applications', sa.Column('section_approved', sa.Boolean(), nullable=True))
    op.add_column('leave_applications', sa.Column('section_approved_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('leave_applications', sa.Column('unit_approved_by', sa.Integer(), nullable=True))
    op.add_column('leave_applications', sa.Column('unit_approved', sa.Boolean(), nullable=True))
    op.add_column('leave_applications', sa.Column('unit_approved_at', sa.DateTime(timezone=True), nullable=True))

    # Drop new tables and columns
    op.drop_index('ix_users_reports_to_id', table_name='users')
    op.drop_column('users', 'reports_to_id')

    op.drop_column('tenants', 'industry')
    op.drop_column('tenants', 'company_size')
    op.drop_column('tenants', 'country')
    op.drop_column('tenants', 'timezone')

    op.drop_table('leave_approval_steps')
    op.drop_table('user_roles')
    op.drop_table('roles')
