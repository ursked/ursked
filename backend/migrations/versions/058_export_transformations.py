"""Give saved exports a date window, grouping, aggregates, aliases and formats

Revision ID: 058_export_transformations
Revises: 057_time_clock_geolocation
Create Date: 2026-09-06

`data_export_configs` has been unchanged since migration 015 apart from one
string column, so a saved report could express "these columns, these row
filters, one sort" and nothing else. Everything a person opens Excel for --
group and total, rename a heading, format a date, "last month" rather than two
typed dates -- had nowhere to live.

All columns are additive and nullable with sane server defaults, so every
existing config and every running schedule keeps working untouched.

Worth recording why `date_preset` matters beyond convenience: a scheduled export
had nowhere to store a window at all, so a "Daily Attendance" schedule emailed
the ENTIRE attendance history every morning, growing without bound. An absolute
date pair cannot fix that -- only a relative window that re-resolves on each run
can.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "058_export_transformations"
down_revision = "057_time_clock_geolocation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "data_export_configs",
        sa.Column("group_by", postgresql.JSONB(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "data_export_configs",
        sa.Column("aggregations", postgresql.JSONB(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "data_export_configs",
        sa.Column("column_aliases", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "data_export_configs",
        sa.Column("column_formats", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    # Multi-key sorting. `sort_by`/`sort_direction` stay for backward
    # compatibility and are read as a fallback when `sorts` is empty.
    op.add_column(
        "data_export_configs",
        sa.Column("sorts", postgresql.JSONB(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "data_export_configs",
        sa.Column("date_preset", sa.String(30), nullable=True),
    )
    op.add_column(
        "data_export_configs",
        sa.Column("date_from", sa.String(10), nullable=True),
    )
    op.add_column(
        "data_export_configs",
        sa.Column("date_to", sa.String(10), nullable=True),
    )
    op.add_column(
        "data_export_configs",
        sa.Column("output_format", sa.String(10), nullable=False, server_default="csv"),
    )
    op.add_column(
        "data_export_configs",
        sa.Column("row_limit", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    for col in (
        "row_limit",
        "output_format",
        "date_to",
        "date_from",
        "date_preset",
        "sorts",
        "column_formats",
        "column_aliases",
        "aggregations",
        "group_by",
    ):
        op.drop_column("data_export_configs", col)
