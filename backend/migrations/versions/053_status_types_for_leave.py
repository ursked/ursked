"""Provision shift status types for existing leave types.

Approving a leave writes the leave type's *code* into `shifts.status`, and the
schedule grid resolves colour/label by looking that code up in
`shift_status_types`. Installs seeded before this migration only ever received
the 'scheduled' and 'rest_day' system types, so every approved leave rendered as
an unrecognised grey cell with a truncated label and never appeared in the
calendar legend.

This backfills a status type for each existing leave type, plus the
'holiday_off' system type which the frontend has always known about but which
was never seeded.

Idempotent: rows are only inserted where the (tenant_id, code) pair is absent,
so the `uq_tenant_status_code` constraint holds and any colours an admin has
already chosen are left untouched.

Revision ID: 053_status_types_for_leave
Revises: 052_attendance_self_reported
"""
import zlib

import sqlalchemy as sa
from alembic import op

revision = "053_status_types_for_leave"
down_revision = "052_attendance_self_reported"
branch_labels = None
depends_on = None


# Mirrors app/services/settings_service.py. Duplicated deliberately: a migration
# must keep describing the schema as it was at this revision even if the service
# constants are later edited.
KNOWN = {
    "sick_leave": ("#ef4444", "bg-red-100 text-red-800", "SL"),
    "personal_leave": ("#f59e0b", "bg-amber-100 text-amber-800", "PL"),
    "emergency_leave": ("#dc2626", "bg-red-100 text-red-800", "EL"),
    "annual_vacation": ("#3b82f6", "bg-blue-100 text-blue-800", "AV"),
    "offset": ("#8b5cf6", "bg-violet-100 text-violet-800", "OFF"),
    "bereavement_leave": ("#374151", "bg-gray-200 text-gray-800", "BL"),
    "paternity_leave": ("#0ea5e9", "bg-sky-100 text-sky-800", "PatL"),
    "maternity_leave": ("#ec4899", "bg-pink-100 text-pink-800", "MatL"),
    "union_leave": ("#14b8a6", "bg-teal-100 text-teal-800", "UL"),
    "fire_calamity_leave": ("#f97316", "bg-orange-100 text-orange-800", "FCL"),
    "solo_parent_leave": ("#a855f7", "bg-purple-100 text-purple-800", "SPL"),
    "special_leave_women": ("#d946ef", "bg-fuchsia-100 text-fuchsia-800", "SLW"),
    "vawc_leave": ("#e11d48", "bg-rose-100 text-rose-800", "VAWC"),
    "sick": ("#ef4444", "bg-red-100 text-red-800", "SL"),
    "personal": ("#f59e0b", "bg-amber-100 text-amber-800", "PL"),
    "vacation": ("#3b82f6", "bg-blue-100 text-blue-800", "VL"),
}

FALLBACK_PALETTE = [
    ("#0891b2", "bg-cyan-100 text-cyan-800"),
    ("#65a30d", "bg-lime-100 text-lime-800"),
    ("#c026d3", "bg-fuchsia-100 text-fuchsia-800"),
    ("#ea580c", "bg-orange-100 text-orange-800"),
    ("#4f46e5", "bg-indigo-100 text-indigo-800"),
    ("#be123c", "bg-rose-100 text-rose-800"),
    ("#0d9488", "bg-teal-100 text-teal-800"),
    ("#7c2d12", "bg-amber-100 text-amber-900"),
]


def upgrade() -> None:
    conn = op.get_bind()

    # 1. 'holiday_off' for every tenant that lacks it.
    conn.execute(
        sa.text(
            """
            INSERT INTO shift_status_types
                (tenant_id, code, label, short_label, color, bg_class,
                 category, is_system, is_active, sort_order)
            SELECT DISTINCT s.tenant_id, 'holiday_off', 'Holiday Off', 'HO',
                   '#10b981', 'bg-emerald-100 text-emerald-800',
                   'rest', true, true, 2
            FROM shift_status_types s
            WHERE NOT EXISTS (
                SELECT 1 FROM shift_status_types x
                WHERE x.tenant_id = s.tenant_id AND x.code = 'holiday_off'
            )
            """
        )
    )

    # 2. One status type per existing leave type that has no matching code.
    rows = conn.execute(
        sa.text(
            """
            SELECT lt.tenant_id, lt.code, lt.name, lt.export_code
            FROM leave_types lt
            WHERE NOT EXISTS (
                SELECT 1 FROM shift_status_types s
                WHERE s.tenant_id = lt.tenant_id AND s.code = lt.code
            )
            """
        )
    ).fetchall()

    for tenant_id, code, name, export_code in rows:
        known = KNOWN.get(code)
        if known:
            color, bg_class, short = known
        else:
            idx = zlib.crc32(code.encode()) % len(FALLBACK_PALETTE)
            color, bg_class = FALLBACK_PALETTE[idx]
            short = None
        short_label = export_code or short
        if not short_label:
            words = (name or code).replace("_", " ").split()
            if len(words) > 1:
                short_label = "".join(w[0] for w in words).upper()[:10]
            else:
                short_label = (name or code)[:10]

        conn.execute(
            sa.text(
                """
                INSERT INTO shift_status_types
                    (tenant_id, code, label, short_label, color, bg_class,
                     category, is_system, is_active, sort_order)
                VALUES (:tenant_id, :code, :label, :short_label, :color,
                        :bg_class, 'leave', false, true, 50)
                """
            ),
            {
                "tenant_id": tenant_id,
                "code": code,
                "label": name or code,
                "short_label": short_label,
                "color": color,
                "bg_class": bg_class,
            },
        )


def downgrade() -> None:
    # Remove only the rows this migration could have added. Leave types that an
    # admin has since recoloured are still removed — the alternative is leaving
    # orphaned rows behind, and downgrade is a development path.
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            DELETE FROM shift_status_types s
            WHERE s.code = 'holiday_off'
               OR EXISTS (
                   SELECT 1 FROM leave_types lt
                   WHERE lt.tenant_id = s.tenant_id AND lt.code = s.code
               )
            """
        )
    )
