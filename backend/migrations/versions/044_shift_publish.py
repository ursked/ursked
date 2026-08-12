"""Shift draft/publish

Revision ID: 044_shift_publish
Revises: 043_salary_enrollment

Adds draft/publish state to shifts so a schedule can be built privately and
released to employees deliberately:
- is_published BOOLEAN NOT NULL DEFAULT false — new shifts start as DRAFT and
  are hidden from employees until an editor publishes the range.
- published_at / published_by — audit of when/who released it.

Backfill: EXISTING shifts are set is_published=TRUE so nothing disappears from
employees' views on deploy (only shifts created AFTER this migration are drafts
by default).
"""
from alembic import op
import sqlalchemy as sa

revision = "044_shift_publish"
down_revision = "043_salary_enrollment"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "shifts",
        sa.Column("is_published", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("shifts", sa.Column("published_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("shifts", sa.Column("published_by", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_shifts_published_by_users", "shifts", "users",
        ["published_by"], ["id"], ondelete="SET NULL",
    )
    # Backfill: existing shifts are already "live" → mark them published.
    op.execute("UPDATE shifts SET is_published = TRUE")


def downgrade() -> None:
    op.drop_constraint("fk_shifts_published_by_users", "shifts", type_="foreignkey")
    op.drop_column("shifts", "published_by")
    op.drop_column("shifts", "published_at")
    op.drop_column("shifts", "is_published")
