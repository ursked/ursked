"""Unlock PH-specific system deductions so existing tenants can edit them

Revision ID: 035_generic_seeds
Revises: 034_payroll_engine

Data-only. Existing tenants keep their seeded SSS/PhilHealth/Pag-IBIG rows, but
they become editable/deactivatable (is_system=false) now that the product is
country-neutral. New tenants get no government deductions at all.
"""

from alembic import op

revision = "035_generic_seeds"
down_revision = "034_payroll_engine"
branch_labels = None
depends_on = None

PH_CODES = (
    "sss", "sss_employer",
    "philhealth", "philhealth_employer",
    "pagibig", "pagibig_employer",
    "withholding_tax",
)


def upgrade() -> None:
    codes = ", ".join(f"'{c}'" for c in PH_CODES)
    op.execute(
        f"UPDATE deduction_types SET is_system = false WHERE code IN ({codes})"
    )


def downgrade() -> None:
    codes = ", ".join(f"'{c}'" for c in PH_CODES)
    op.execute(
        f"UPDATE deduction_types SET is_system = true WHERE code IN ({codes})"
    )
