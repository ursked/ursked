"""Policy rule scoping + effective dating

Revision ID: 042_policy_rule_scoping
Revises: 041_payroll_run_payout

Adds optional scoping to policy_rules so a tenant can run different automation
per department/site and switch policies on a date:
- scope_org_node_ids: JSONB int array. When set, the rule only applies to
  employees in one of these org nodes (or their descendants). NULL = all.
- effective_from / effective_until: Date window (inclusive). The rule only
  applies to attendance whose date is within the window. NULL = open-ended.

The condition-tree, range-bands and stop_processing features reuse the existing
`conditions`/`actions` JSONB columns and need no schema change.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "042_policy_rule_scoping"
down_revision = "041_payroll_run_payout"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "policy_rules",
        sa.Column("scope_org_node_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "policy_rules",
        sa.Column("effective_from", sa.Date(), nullable=True),
    )
    op.add_column(
        "policy_rules",
        sa.Column("effective_until", sa.Date(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("policy_rules", "effective_until")
    op.drop_column("policy_rules", "effective_from")
    op.drop_column("policy_rules", "scope_org_node_ids")
