"""Remove the upper bound on org level_number (support very deep hierarchies)

Revision ID: 036_org_levels_unbounded
Revises: 035_generic_seeds

The old constraint capped hierarchies at 9 levels. That was an arbitrary
policy limit, not a technical one, and some organizations are deeper. Keep the
lower bound (>= 1); tree traversal now relies on visited-set cycle detection
rather than a depth cap, so there is no correctness risk to removing the cap.
"""
from alembic import op

revision = "036_org_levels_unbounded"
down_revision = "035_generic_seeds"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_level_number_range", "org_levels", type_="check")
    op.create_check_constraint(
        "ck_level_number_range",
        "org_levels",
        "level_number >= 1",
    )


def downgrade() -> None:
    op.drop_constraint("ck_level_number_range", "org_levels", type_="check")
    op.create_check_constraint(
        "ck_level_number_range",
        "org_levels",
        "level_number >= 1 AND level_number <= 9",
    )
