"""Make grid badge labels unique within a tenant.

Migration 053 derived `short_label` from the leave type's name without checking
what was already in use, so any two types sharing initials collided: "Sick
Leave" and "Study Leave" both became "SL". The short label is what the schedule
grid prints in the cell, so two statuses with the same badge defeat the point of
having one.

This renames only the *later* duplicates (lowest id keeps the label it has, so
the badge people are already used to does not move), widening the first word a
letter at a time -- SL -> STL -> STUL -- and numbering only if nothing readable
is free. Matching is case-insensitive: "SL" and "sl" read as the same badge.

No uniqueness constraint is added. An admin editing labels by hand may have a
deliberate reason to repeat one, and blocking that at the database level would
turn a cosmetic choice into an error.

Revision ID: 055_unique_short_labels
Revises: 054_holiday_off_and_remark_unique
"""
import sqlalchemy as sa
from alembic import op

revision = "055_unique_short_labels"
down_revision = "054_holiday_off_and_remark_unique"
branch_labels = None
depends_on = None

MAX = 10


def _candidates(name, code, preferred):
    if preferred:
        yield preferred[:MAX]
    words = (name or code or "").replace("_", " ").split()
    if len(words) > 1:
        head, rest = words[0], words[1:]
        tail = "".join(w[0] for w in rest).upper()
        for i in range(1, len(head) + 1):
            yield (head[:i] + tail).upper()[:MAX]
            if len(head[:i]) + len(tail) >= MAX:
                break
    elif words:
        word = words[0]
        for i in range(4, MAX + 1):
            yield word[:i]
            if i >= len(word):
                break


def _pick(name, code, preferred, taken_ci):
    seen = []
    for c in _candidates(name, code, preferred):
        if not c or c in seen:
            continue
        seen.append(c)
        if c.casefold() not in taken_ci:
            return c
    base = (seen[0] if seen else (code or "ST")[:2])[: MAX - 2]
    n = 2
    while f"{base}{n}".casefold() in taken_ci:
        n += 1
    return f"{base}{n}"[:MAX]


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            """
            SELECT id, tenant_id, code, label, short_label
            FROM shift_status_types
            ORDER BY tenant_id, id
            """
        )
    ).fetchall()

    taken_by_tenant: dict = {}
    for row_id, tenant_id, code, label, short_label in rows:
        taken = taken_by_tenant.setdefault(tenant_id, set())
        current = (short_label or "").casefold()

        if current and current not in taken:
            taken.add(current)
            continue

        # Either blank or a duplicate of one already claimed by a lower id.
        replacement = _pick(label, code, None, taken)
        taken.add(replacement.casefold())
        conn.execute(
            sa.text(
                "UPDATE shift_status_types SET short_label = :s WHERE id = :i"
            ),
            {"s": replacement, "i": row_id},
        )


def downgrade() -> None:
    # Renaming a badge back would need the pre-migration values, which were
    # ambiguous by definition. Nothing to restore.
    pass
