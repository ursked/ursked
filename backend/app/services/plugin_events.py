"""Core's side of plugin events: what each event carries, and where it comes from
(ops/PLUGINS_AND_LICENSING.md 2.2).

Three events already exist inside core as domain_events (leave decisions,
separations, shift writes); the handlers below translate them. The others are
published by the code that makes the change, through the helpers here, so
every payload is built the same way: plain data, people as
{"id", "name", "email"}, and nothing about pay. plugin_host.publish then drops
what a plugin's scopes do not allow and queues it in the caller's transaction.

Payloads are the `data` of the envelope; their keys are a promise to plugin
authors and only ever gain fields.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import plugin_host
from app.services.domain_events import on

# A batch edit can touch thousands of (employee, day) pairs; past this many the
# list is cut and "truncated" says so. The counts stay exact.
MAX_CHANGES = 1000
DECIDED = {"approved", "rejected", "cancelled", "expired"}


def person(user) -> Optional[dict]:
    if user is None:
        return None
    name = f"{user.first_name or ''} {user.last_name or ''}".strip() or user.username
    return {"id": user.id, "name": name, "email": user.email}


async def _people(db: AsyncSession, ids: Iterable[int]) -> dict:
    from app.models.user import User

    ids = sorted({i for i in ids if i is not None})
    if not ids:
        return {}
    rows = (await db.execute(select(User).where(User.id.in_(ids)))).scalars().all()
    return {u.id: person(u) for u in rows}


def _leave(app, employee: Optional[dict]) -> dict:
    return {
        "id": app.id,
        "employee": employee,
        "leave_type": app.leave_type,
        "start_date": app.start_date.isoformat() if app.start_date else None,
        "end_date": app.end_date.isoformat() if app.end_date else None,
        "days": float(app.days_requested) if app.days_requested is not None else None,
        "half_day": bool(getattr(app, "half_day", False)),
        "status": app.status,
    }


async def changes_payload(db: AsyncSession, changes: Iterable[Tuple[int, object]]) -> dict:
    pairs = sorted({(e, d) for e, d in changes}, key=lambda p: (str(p[1]), p[0]))
    people = await _people(db, (e for e, _ in pairs))
    dates = sorted({d for _, d in pairs})
    by_emp = defaultdict(int)
    for e, _ in pairs:
        by_emp[e] += 1
    return {
        "count": len(pairs),
        "from": dates[0].isoformat() if dates else None,
        "to": dates[-1].isoformat() if dates else None,
        "employees": [dict(people.get(e) or {"id": e}, days=n) for e, n in sorted(by_emp.items())],
        "changes": [{"employee_id": e, "date": d.isoformat()} for e, d in pairs[:MAX_CHANGES]],
        "truncated": len(pairs) > MAX_CHANGES,
    }


# ── published by core code ──────────────────────────────────────────────────


async def schedule_published(db, tenant_id, start_date, end_date, shifts: List, actor=None) -> None:
    data = await changes_payload(db, [(s.employee_id, s.date) for s in shifts])
    data.update({"from": start_date.isoformat(), "to": end_date.isoformat(), "published_by": person(actor)})
    await plugin_host.publish(db, tenant_id, "schedule.published", data)


async def leave_requested(db, application, employee) -> None:
    await plugin_host.publish(db, application.tenant_id, "leave.requested", _leave(application, person(employee)))


async def clocked(db, tenant_id, punch, employee=None) -> None:
    if employee is None:
        employee = (await _people(db, [punch.employee_id])).get(punch.employee_id)
    else:
        employee = person(employee)
    at = getattr(punch, "punched_at", None) or getattr(punch, "timestamp", None)
    await plugin_host.publish(db, tenant_id, "attendance.clocked", {
        "employee": employee,
        "type": getattr(punch, "punch_type", None),
        "at": at.isoformat() if at else None,
        "source": getattr(punch, "source", None),
    })


async def missed(db, tenant_id, marked: List[Tuple[int, object]]) -> None:
    if not marked:
        return
    people = await _people(db, (e for e, _ in marked))
    for emp_id, day in marked:
        await plugin_host.publish(db, tenant_id, "attendance.missed", {
            "employee": people.get(emp_id) or {"id": emp_id},
            "date": day.isoformat(),
        })


async def employee_joined(db, user) -> None:
    await plugin_host.publish(db, user.tenant_id, "employee.joined", {
        "employee": person(user),
        "hiring_date": user.hiring_date.isoformat() if getattr(user, "hiring_date", None) else None,
    })


async def payroll_finalized(db, period, actor_id=None) -> None:
    actor = (await _people(db, [actor_id])).get(actor_id) if actor_id else None
    await plugin_host.publish(db, period.tenant_id, "payroll.finalized", {
        "period": {
            "id": period.id,
            "name": getattr(period, "name", None),
            "start_date": period.start_date.isoformat() if getattr(period, "start_date", None) else None,
            "end_date": period.end_date.isoformat() if getattr(period, "end_date", None) else None,
        },
        "finalized_by": actor,
    })


# ── translated from domain_events ───────────────────────────────────────────


@on("leave.status_changed")
async def _leave_status(db, tenant_id, actor, application, old_status, new_status, **_):
    if new_status not in DECIDED:
        return
    employee = (await _people(db, [application.employee_id])).get(application.employee_id)
    data = _leave(application, employee)
    data.update({"previous_status": old_status, "decided_by": person(actor)})
    await plugin_host.publish(db, tenant_id, "leave.decided", data)


@on("employee.separated")
async def _separated(db, tenant_id, actor, user, **_):
    await plugin_host.publish(db, tenant_id, "employee.separated", {
        "employee": person(user),
        "separation_date": user.separation_date.isoformat() if getattr(user, "separation_date", None) else None,
        "by": person(actor),
    })


@on("shift.after_write")
async def _shifts(db, tenant_id, actor, changes, **_):
    if not changes:
        return
    data = await changes_payload(db, changes)
    data["by"] = person(actor)
    await plugin_host.publish(db, tenant_id, "shift.changed", data)
