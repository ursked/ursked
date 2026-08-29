"""Auto holiday-off setting, and one date remark per date.

Two changes:

1. `app_settings.auto_create_holiday_off` — opt-in generation of 'holiday_off'
   shifts when a date is marked as a holiday. Defaults to false because writing a
   row onto every employee's calendar is not something to do unasked.

2. A uniqueness constraint on `date_remarks (tenant_id, date)`. Without it the
   same date could carry several remarks; the API happily created duplicates and
   returned them all, while the grid keys remarks by date and silently displayed
   only one. Duplicates are collapsed before the constraint is added, keeping the
   lowest id per (tenant, date) — that is the first one created, which is the row
   the grid has been showing.

Revision ID: 054_holiday_off_and_remark_unique
Revises: 053_status_types_for_leave
"""
import sqlalchemy as sa
from alembic import op

revision = "054_holiday_off_and_remark_unique"
down_revision = "053_status_types_for_leave"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "app_settings",
        sa.Column(
            "auto_create_holiday_off",
            sa.Boolean(),
            nullable=True,
            server_default=sa.false(),
        ),
    )
    op.execute(
        "UPDATE app_settings SET auto_create_holiday_off = false "
        "WHERE auto_create_holiday_off IS NULL"
    )

    # Collapse duplicates before constraining. Keep the lowest id per
    # (tenant_id, date): it is the earliest created and therefore the one the
    # grid has been rendering, so nothing visibly changes.
    op.execute(
        """
        DELETE FROM date_remarks d
        USING date_remarks keep
        WHERE d.tenant_id = keep.tenant_id
          AND d.date = keep.date
          AND d.id > keep.id
        """
    )

    op.create_unique_constraint(
        "uq_date_remark_tenant_date", "date_remarks", ["tenant_id", "date"]
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_date_remark_tenant_date", "date_remarks", type_="unique"
    )
    op.drop_column("app_settings", "auto_create_holiday_off")
