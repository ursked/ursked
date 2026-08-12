"""Expand org_levels max level_number from 6 to 9.

Revision ID: 006_expand_org_levels_to_9
Revises: 005_flexible_org_hierarchy
Create Date: 2026-01-31
"""
from alembic import op

revision = "006_expand_org_levels_to_9"
down_revision = "005_flexible_org_hierarchy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_level_number_range", "org_levels", type_="check")
    op.create_check_constraint(
        "ck_level_number_range",
        "org_levels",
        "level_number >= 1 AND level_number <= 9",
    )


def downgrade() -> None:
    op.drop_constraint("ck_level_number_range", "org_levels", type_="check")
    op.create_check_constraint(
        "ck_level_number_range",
        "org_levels",
        "level_number >= 1 AND level_number <= 6",
    )
