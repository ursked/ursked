"""Employee data: custom profile fields, a renameable employee number, and
case-insensitive uniqueness for emails and employee numbers

Revision ID: 061_employees_custom_fields
Revises: 059_permission_defaults
Create Date: 2026-09-28

Four additive changes (audit 2026-09-28, E-12, E-16, E-17 and the "can I add
my own employee code?" question):

1. `employee_field_definitions` / `employee_field_values` — company-defined
   profile fields. Uniqueness of a value, for fields marked unique, is a
   partial unique index over (field_id, value_norm) WHERE is_unique; the model
   explains why the flag is copied onto each value row.

2. `app_settings.employee_number_label` — what the company calls Personnel #.
   NULL means the default wording.

3. A unique index on users (tenant_id, lower(email)). Emails were compared
   case-sensitively, so "Ana@x.com" and "ana@x.com" could be two accounts and
   login could miss the one typed differently.

4. A unique index on users (tenant_id, lower(personnel_number)) where it is set.
   Duplicate employee numbers were allowed, so the number identified nobody.

3 and 4 are created ONLY when the existing data already satisfies them. A
migration that fails because a customer has two rows differing only by case
would leave the upgrade half-done and the app down; instead the conflicting
rows are printed so an administrator can tidy them, the application's own
checks keep new duplicates out in the meantime, and the printed CREATE INDEX
statement adds the index once the data is clean. No existing data is changed
by this migration.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "061_employees_custom_fields"
down_revision = "059_permission_defaults"
branch_labels = None
depends_on = None


EMAIL_INDEX = "uq_users_tenant_email_ci"
PERSONNEL_INDEX = "uq_users_tenant_personnel_number_ci"
PERSONNEL_WHERE = "personnel_number IS NOT NULL AND btrim(personnel_number) <> ''"


def _create_if_clean(bind, name: str, duplicates_sql: str, create_sql: str, what: str) -> None:
    dupes = bind.execute(sa.text(duplicates_sql)).fetchall()
    if dupes:
        print(
            f"[061_employees_custom_fields] NOT creating {name}: {len(dupes)} "
            f"{what} value(s) are shared by more than one user. Resolve them, then "
            f"run: {create_sql}"
        )
        for tenant_id, value, n in dupes[:50]:
            print(f"    tenant {tenant_id}: {value!r} used by {n} users")
        if len(dupes) > 50:
            print(f"    ... and {len(dupes) - 50} more")
        return
    bind.execute(sa.text(create_sql))


def upgrade() -> None:
    op.create_table(
        "employee_field_definitions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key", sa.String(50), nullable=False),
        sa.Column("label", sa.String(100), nullable=False),
        sa.Column("field_type", sa.String(20), nullable=False, server_default="text"),
        sa.Column("options", postgresql.JSONB(), nullable=True),
        sa.Column("is_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_unique", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("regex", sa.String(200), nullable=True),
        sa.Column("visibility", sa.String(20), nullable=False, server_default="hr_only"),
        sa.Column("is_sensitive", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("help_text", sa.String(300), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("tenant_id", "key", name="uq_employee_field_def_tenant_key"),
        sa.CheckConstraint(
            "field_type IN ('text','number','date','select','boolean')",
            name="ck_employee_field_def_type",
        ),
        sa.CheckConstraint(
            "visibility IN ('hr_only','managers','employee_view','employee_edit')",
            name="ck_employee_field_def_visibility",
        ),
    )
    op.create_index("ix_employee_field_definitions_tenant_id", "employee_field_definitions", ["tenant_id"])

    op.create_table(
        "employee_field_values",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("field_id", sa.Integer(), sa.ForeignKey("employee_field_definitions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("value_text", sa.Text(), nullable=True),
        sa.Column("value_norm", sa.String(500), nullable=True),
        sa.Column("is_unique", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("field_id", "user_id", name="uq_employee_field_value_field_user"),
    )
    op.create_index("ix_employee_field_values_tenant_id", "employee_field_values", ["tenant_id"])
    op.create_index("ix_employee_field_values_field_id", "employee_field_values", ["field_id"])
    op.create_index("ix_employee_field_values_user_id", "employee_field_values", ["user_id"])
    op.create_index(
        "uq_employee_field_value_unique",
        "employee_field_values",
        ["field_id", "value_norm"],
        unique=True,
        postgresql_where=sa.text("is_unique AND value_norm IS NOT NULL"),
    )

    op.add_column("app_settings", sa.Column("employee_number_label", sa.String(50), nullable=True))

    # The audit log viewer filters by target ("everything that happened to
    # this employee"); without an index that is a scan of the whole log.
    op.create_index("ix_audit_logs_resource", "audit_logs", ["resource_type", "resource_id"])

    bind = op.get_bind()
    _create_if_clean(
        bind,
        EMAIL_INDEX,
        """
        SELECT tenant_id, lower(email), count(*) FROM users
         GROUP BY tenant_id, lower(email) HAVING count(*) > 1
         ORDER BY tenant_id, lower(email)
        """,
        f"CREATE UNIQUE INDEX {EMAIL_INDEX} ON users (tenant_id, lower(email))",
        "email",
    )
    _create_if_clean(
        bind,
        PERSONNEL_INDEX,
        f"""
        SELECT tenant_id, lower(btrim(personnel_number)), count(*) FROM users
         WHERE {PERSONNEL_WHERE}
         GROUP BY tenant_id, lower(btrim(personnel_number)) HAVING count(*) > 1
         ORDER BY tenant_id, lower(btrim(personnel_number))
        """,
        f"CREATE UNIQUE INDEX {PERSONNEL_INDEX} ON users (tenant_id, lower(btrim(personnel_number))) WHERE {PERSONNEL_WHERE}",
        "employee number",
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {PERSONNEL_INDEX}")
    op.execute(f"DROP INDEX IF EXISTS {EMAIL_INDEX}")
    op.drop_index("ix_audit_logs_resource", table_name="audit_logs")
    op.drop_column("app_settings", "employee_number_label")
    op.drop_index("uq_employee_field_value_unique", table_name="employee_field_values")
    op.drop_index("ix_employee_field_values_user_id", table_name="employee_field_values")
    op.drop_index("ix_employee_field_values_field_id", table_name="employee_field_values")
    op.drop_index("ix_employee_field_values_tenant_id", table_name="employee_field_values")
    op.drop_table("employee_field_values")
    op.drop_index("ix_employee_field_definitions_tenant_id", table_name="employee_field_definitions")
    op.drop_table("employee_field_definitions")
