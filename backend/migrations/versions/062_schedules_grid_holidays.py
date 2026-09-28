"""Schedule grid and holidays: provenance, live holiday feed, hour rules

Revision ID: 062_schedules_grid_holidays
Revises: 063_leave_approvals_engine
Create Date: 2026-09-28

Four things, all additive:

1. shifts.original_is_published and shifts.holiday_remark_id. A leave overlay
   now publishes the days it writes (they are the consequence of an approved
   decision; as drafts the employee could not see their own leave), so it
   needs somewhere to remember a draft was a draft for when the leave is
   reverted. holiday_remark_id records which holiday generated an automatic
   'holiday_off' shift, so editing or deleting that holiday can remove exactly
   the shifts it made and nothing an editor touched since.

2. date_remarks gains the columns the live holiday feed needs: source, the
   feed's event uid, tentative / regional / needs-review flags, a
   locally-modified guard, and a suppression tombstone so a feed holiday an
   admin deleted is not re-added by the next sync.

3. holiday_sources: one row per tenant saying where holidays come from and
   how the last sync went.

4. Four app_settings for working-hour rules (max hours per day and per week,
   minimum rest between working days, overlapping segments). All default off.

Existing data: leave-overlay shifts of APPROVED leave that are still drafts
are published, because employees could not see their own approved leave.
Downgrade does not un-publish them (it cannot tell them apart afterwards, and
approved leave being visible is correct); everything else reverses exactly.
Existing holiday_off shifts keep holiday_remark_id NULL: nobody knows which
holiday made them, so no holiday edit will ever remove them.
"""

from alembic import op
import sqlalchemy as sa

revision = "062_schedules_grid_holidays"
down_revision = "063_leave_approvals_engine"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("shifts", sa.Column("original_is_published", sa.Boolean(), nullable=True))
    op.add_column("shifts", sa.Column("holiday_remark_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_shifts_holiday_remark_id", "shifts", "date_remarks",
        ["holiday_remark_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index("ix_shifts_holiday_remark_id", "shifts", ["holiday_remark_id"])

    op.add_column("date_remarks", sa.Column("source", sa.String(20), nullable=False, server_default="manual"))
    op.add_column("date_remarks", sa.Column("external_uid", sa.Text(), nullable=True))
    op.add_column("date_remarks", sa.Column("is_tentative", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("date_remarks", sa.Column("region", sa.String(100), nullable=True))
    op.add_column("date_remarks", sa.Column("needs_review", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("date_remarks", sa.Column("locally_modified", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("date_remarks", sa.Column("is_suppressed", sa.Boolean(), nullable=False, server_default="false"))

    op.create_table(
        "holiday_sources",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(30), nullable=False, server_default="officeholidays"),
        sa.Column("country_slug", sa.String(100), nullable=True),
        sa.Column("feed_url", sa.Text(), nullable=True),
        sa.Column("include_regions", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("auto_sync", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(20), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_counts", sa.JSON(), nullable=True),
        sa.Column("discovered_regions", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", name="uq_holiday_sources_tenant"),
    )

    op.add_column("app_settings", sa.Column("max_work_hours_per_day", sa.Float(), nullable=False, server_default="0"))
    op.add_column("app_settings", sa.Column("max_work_hours_per_week", sa.Float(), nullable=False, server_default="0"))
    op.add_column("app_settings", sa.Column("min_rest_hours_between_shifts", sa.Float(), nullable=False, server_default="0"))
    op.add_column("app_settings", sa.Column("check_overlapping_shifts", sa.Boolean(), nullable=False, server_default="false"))

    # Approved leave the employee could not see: publish it.
    op.execute(
        """
        UPDATE shifts s
           SET is_published = true,
               published_at = COALESCE(s.published_at, now())
          FROM leave_applications la
         WHERE s.leave_application_id = la.id
           AND la.status = 'approved'
           AND s.is_published = false
        """
    )


def downgrade() -> None:
    op.drop_column("app_settings", "check_overlapping_shifts")
    op.drop_column("app_settings", "min_rest_hours_between_shifts")
    op.drop_column("app_settings", "max_work_hours_per_week")
    op.drop_column("app_settings", "max_work_hours_per_day")

    op.drop_table("holiday_sources")

    # Tombstones are not holidays and have no meaning without the feed; drop
    # them so the (tenant, date) uniqueness does not block a manual holiday.
    op.execute("DELETE FROM date_remarks WHERE is_suppressed = true")
    for col in ("is_suppressed", "locally_modified", "needs_review", "region",
                "is_tentative", "external_uid", "source"):
        op.drop_column("date_remarks", col)

    op.drop_index("ix_shifts_holiday_remark_id", table_name="shifts")
    op.drop_constraint("fk_shifts_holiday_remark_id", "shifts", type_="foreignkey")
    op.drop_column("shifts", "holiday_remark_id")
    op.drop_column("shifts", "original_is_published")
