"""Create SaaS schema

Revision ID: 001_create_saas_schema
Revises:
Create Date: 2024-01-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '001_create_saas_schema'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Alembic creates alembic_version.version_num as VARCHAR(32) by default. Some
    # of this project's revision identifiers are longer than 32 characters (e.g.
    # "030_session_revocation_and_indexes" is 34), which fails to stamp on a fresh
    # database. Widen the column at the very first migration — the table already
    # exists at this point (Alembic created it to record this revision), and this
    # ALTER is idempotent, so it is safe on new and existing installs alike.
    op.execute("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(255)")

    # Tenants
    op.create_table(
        'tenants',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('slug', sa.String(100), unique=True, nullable=False),
        sa.Column('domain', sa.String(255), unique=True, nullable=True),
        sa.Column('email', sa.String(255), nullable=False),
        sa.Column('phone', sa.String(50), nullable=True),
        sa.Column('plan', sa.String(50), nullable=False, server_default='free'),
        sa.Column('subscription_status', sa.String(50), nullable=False, server_default='trial'),
        sa.Column('subscription_ends_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('stripe_customer_id', sa.String(255), nullable=True),
        sa.Column('stripe_subscription_id', sa.String(255), nullable=True),
        sa.Column('max_users', sa.Integer(), server_default='10'),
        sa.Column('max_storage_gb', sa.Integer(), server_default='5'),
        sa.Column('settings', postgresql.JSONB(), nullable=True),
        sa.Column('branding', postgresql.JSONB(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )
    op.create_index('ix_tenants_slug', 'tenants', ['slug'])
    op.create_index('ix_tenants_domain', 'tenants', ['domain'])

    # Departments
    op.create_table(
        'departments',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('code', sa.String(50), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )
    op.create_index('ix_departments_tenant_id', 'departments', ['tenant_id'])

    # Divisions
    op.create_table(
        'divisions',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('department_id', sa.Integer(), sa.ForeignKey('departments.id', ondelete='SET NULL'), nullable=True),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('code', sa.String(50), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )
    op.create_index('ix_divisions_tenant_id', 'divisions', ['tenant_id'])

    # Sections
    op.create_table(
        'sections',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('division_id', sa.Integer(), sa.ForeignKey('divisions.id', ondelete='SET NULL'), nullable=True),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('code', sa.String(50), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )
    op.create_index('ix_sections_tenant_id', 'sections', ['tenant_id'])

    # Units
    op.create_table(
        'units',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('section_id', sa.Integer(), sa.ForeignKey('sections.id', ondelete='SET NULL'), nullable=True),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('code', sa.String(50), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )
    op.create_index('ix_units_tenant_id', 'units', ['tenant_id'])

    # Users
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('username', sa.String(80), nullable=False),
        sa.Column('email', sa.String(255), nullable=False),
        sa.Column('password_hash', sa.String(255), nullable=False),
        sa.Column('first_name', sa.String(100), nullable=False),
        sa.Column('last_name', sa.String(100), nullable=False),
        sa.Column('avatar', sa.String(255), nullable=True),
        sa.Column('contact_number', sa.String(50), nullable=True),
        sa.Column('role', sa.String(50), nullable=False, server_default='employee'),
        sa.Column('personnel_number', sa.String(50), nullable=True),
        sa.Column('typecode', sa.String(50), nullable=True),
        sa.Column('id_number', sa.String(100), nullable=True),
        sa.Column('hiring_date', sa.Date(), nullable=True),
        sa.Column('job_title', sa.String(200), nullable=True),
        sa.Column('rank', sa.String(100), nullable=True),
        sa.Column('div_department', sa.String(200), nullable=True),
        sa.Column('signature', sa.String(255), nullable=True),
        sa.Column('employee_type', sa.String(50), nullable=True),
        sa.Column('schedule_format', sa.String(50), nullable=True, server_default='8_hour'),
        sa.Column('section_id', sa.Integer(), sa.ForeignKey('sections.id', ondelete='SET NULL'), nullable=True),
        sa.Column('unit_id', sa.Integer(), sa.ForeignKey('units.id', ondelete='SET NULL'), nullable=True),
        sa.Column('department_id', sa.Integer(), sa.ForeignKey('departments.id', ondelete='SET NULL'), nullable=True),
        sa.Column('division_id', sa.Integer(), sa.ForeignKey('divisions.id', ondelete='SET NULL'), nullable=True),
        sa.Column('is_section_approver', sa.Boolean(), server_default='false'),
        sa.Column('is_unit_approver', sa.Boolean(), server_default='false'),
        sa.Column('is_department_approver', sa.Boolean(), server_default='false'),
        sa.Column('is_division_approver', sa.Boolean(), server_default='false'),
        sa.Column('is_active', sa.Boolean(), server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.UniqueConstraint('tenant_id', 'username', name='uq_tenant_username'),
        sa.UniqueConstraint('tenant_id', 'email', name='uq_tenant_email'),
    )
    op.create_index('ix_users_tenant_id', 'users', ['tenant_id'])
    op.create_index('ix_users_email', 'users', ['email'])
    op.create_index('ix_users_personnel_number', 'users', ['personnel_number'])

    # User Two Factor
    op.create_table(
        'user_two_factor',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), unique=True, nullable=False),
        sa.Column('status', sa.String(50), nullable=False, server_default='disabled'),
        sa.Column('method', sa.String(50), nullable=False, server_default='totp'),
        sa.Column('totp_secret', sa.String(255), nullable=True),
        sa.Column('totp_verified', sa.Boolean(), server_default='false'),
        sa.Column('backup_codes', postgresql.JSON(), nullable=True),
        sa.Column('grace_period_ends_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )

    # Trusted Devices
    op.create_table(
        'trusted_devices',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('device_token', sa.String(255), unique=True, nullable=False),
        sa.Column('device_name', sa.String(255), nullable=True),
        sa.Column('device_type', sa.String(100), nullable=True),
        sa.Column('ip_address', sa.String(50), nullable=True),
        sa.Column('user_agent', sa.Text(), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )

    # Shifts
    op.create_table(
        'shifts',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('employee_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('start_time', sa.Time(), nullable=True),
        sa.Column('end_time', sa.Time(), nullable=True),
        sa.Column('sequence_number', sa.Integer(), server_default='1'),
        sa.Column('status', sa.String(50), nullable=False, server_default='scheduled'),
        sa.Column('work_arrangement', sa.String(50), nullable=True),
        sa.Column('role_id', sa.Integer(), nullable=True),
        sa.Column('role_name', sa.String(100), nullable=True),
        sa.Column('color', sa.String(20), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('remarks', sa.Text(), nullable=True),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.UniqueConstraint('tenant_id', 'employee_id', 'date', 'sequence_number', name='uq_tenant_employee_date_seq'),
    )
    op.create_index('ix_shifts_tenant_id', 'shifts', ['tenant_id'])
    op.create_index('ix_shifts_employee_id', 'shifts', ['employee_id'])
    op.create_index('ix_shifts_date', 'shifts', ['date'])

    # Date Remarks
    op.create_table(
        'date_remarks',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_holiday', sa.Boolean(), server_default='false'),
        sa.Column('is_special', sa.Boolean(), server_default='false'),
        sa.Column('is_recurring', sa.Boolean(), server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )
    op.create_index('ix_date_remarks_tenant_id', 'date_remarks', ['tenant_id'])
    op.create_index('ix_date_remarks_date', 'date_remarks', ['date'])

    # Schedule Templates
    op.create_table(
        'schedule_templates',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('template_data', postgresql.JSONB(), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='true'),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )
    op.create_index('ix_schedule_templates_tenant_id', 'schedule_templates', ['tenant_id'])

    # Leave Applications
    op.create_table(
        'leave_applications',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('employee_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('leave_type', sa.String(50), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('end_date', sa.Date(), nullable=False),
        sa.Column('days_requested', sa.Float(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('supporting_documents', postgresql.JSON(), nullable=True),
        sa.Column('status', sa.String(50), nullable=False, server_default='pending'),
        sa.Column('reviewed_by', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('reviewer_notes', sa.Text(), nullable=True),
        sa.Column('section_approved_by', sa.Integer(), nullable=True),
        sa.Column('section_approved', sa.Boolean(), nullable=True),
        sa.Column('section_approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('unit_approved_by', sa.Integer(), nullable=True),
        sa.Column('unit_approved', sa.Boolean(), nullable=True),
        sa.Column('unit_approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )
    op.create_index('ix_leave_applications_tenant_id', 'leave_applications', ['tenant_id'])
    op.create_index('ix_leave_applications_employee_id', 'leave_applications', ['employee_id'])

    # Two Factor Settings
    op.create_table(
        'two_factor_settings',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), unique=True, nullable=False),
        sa.Column('require_2fa_all', sa.Boolean(), server_default='false'),
        sa.Column('require_2fa_admins', sa.Boolean(), server_default='false'),
        sa.Column('require_2fa_managers', sa.Boolean(), server_default='false'),
        sa.Column('grace_period_days', sa.Integer(), server_default='7'),
        sa.Column('remember_device_enabled', sa.Boolean(), server_default='true'),
        sa.Column('remember_device_days', sa.Integer(), server_default='30'),
        sa.Column('allow_totp', sa.Boolean(), server_default='true'),
        sa.Column('allow_sms', sa.Boolean(), server_default='false'),
        sa.Column('allow_email', sa.Boolean(), server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )

    # Email Settings
    op.create_table(
        'email_settings',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), unique=True, nullable=False),
        sa.Column('mail_server', sa.String(255), nullable=True),
        sa.Column('mail_port', sa.Integer(), server_default='587'),
        sa.Column('mail_use_tls', sa.Boolean(), server_default='true'),
        sa.Column('mail_use_ssl', sa.Boolean(), server_default='false'),
        sa.Column('mail_username', sa.String(255), nullable=True),
        sa.Column('mail_password', sa.String(255), nullable=True),
        sa.Column('mail_default_sender', sa.String(255), nullable=True),
        sa.Column('mail_sender_name', sa.String(255), nullable=True),
        sa.Column('templates', postgresql.JSONB(), nullable=True),
        sa.Column('is_configured', sa.Boolean(), server_default='false'),
        sa.Column('last_tested_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_test_result', sa.String(255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )

    # App Settings
    op.create_table(
        'app_settings',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id', ondelete='CASCADE'), unique=True, nullable=False),
        sa.Column('timezone', sa.String(100), server_default='UTC'),
        sa.Column('date_format', sa.String(50), server_default='YYYY-MM-DD'),
        sa.Column('time_format', sa.String(50), server_default='HH:mm'),
        sa.Column('week_starts_on', sa.String(20), server_default='monday'),
        sa.Column('default_leave_days', sa.Integer(), server_default='15'),
        sa.Column('allow_negative_leave', sa.Boolean(), server_default='false'),
        sa.Column('require_leave_approval', sa.Boolean(), server_default='true'),
        sa.Column('max_consecutive_leave_days', sa.Integer(), server_default='30'),
        sa.Column('default_shift_duration_hours', sa.Integer(), server_default='8'),
        sa.Column('allow_overtime', sa.Boolean(), server_default='true'),
        sa.Column('max_overtime_hours_per_week', sa.Integer(), server_default='20'),
        sa.Column('notify_on_leave_request', sa.Boolean(), server_default='true'),
        sa.Column('notify_on_leave_approval', sa.Boolean(), server_default='true'),
        sa.Column('notify_on_schedule_change', sa.Boolean(), server_default='true'),
        sa.Column('custom_settings', postgresql.JSONB(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )


def downgrade() -> None:
    op.drop_table('app_settings')
    op.drop_table('email_settings')
    op.drop_table('two_factor_settings')
    op.drop_table('leave_applications')
    op.drop_table('schedule_templates')
    op.drop_table('date_remarks')
    op.drop_table('shifts')
    op.drop_table('trusted_devices')
    op.drop_table('user_two_factor')
    op.drop_table('users')
    op.drop_table('units')
    op.drop_table('sections')
    op.drop_table('divisions')
    op.drop_table('departments')
    op.drop_table('tenants')
