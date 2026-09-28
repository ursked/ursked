"""In-process domain events, so one module can react to another's change
without either importing the other's internals.

Several defects in the 2026-09 audit were the same shape: a change in one
place that another place never heard about. Moving a shift left its attendance
and lateness stale; approving leave for a past day left the "absent" record
standing; separating an employee left their pending approvals routed to someone
who had gone; editing a finalized payroll period's shifts went unchallenged.

The owner of a change emits; interested modules subscribe. Handlers run inline,
in order, inside the caller's transaction and with the caller's session, so a
handler that raises (e.g. HTTPException 409 "this period is finalized") vetoes
the whole change and nothing is half-applied.

Events and their payload keys (all include `db`, `tenant_id`, `actor` which may
be None for system actions):

  shift.before_write   changes: list[(employee_id, date)]  -- may veto by raising
  shift.after_write    changes: list[(employee_id, date)]
  leave.status_changed application, old_status, new_status
  employee.separated   user
  holiday.changed      dates: set[date]

Handlers register with the `on` decorator at import time. Modules that hold
handlers are listed in HANDLER_MODULES and imported once on first emit, so a
handler cannot be silently missing because nothing happened to import it.
"""

from __future__ import annotations

import importlib
import logging
from collections import defaultdict
from typing import Any, Awaitable, Callable, Dict, List

logger = logging.getLogger(__name__)

Handler = Callable[..., Awaitable[None]]

EVENTS = {
    "shift.before_write",
    "shift.after_write",
    "leave.status_changed",
    "employee.separated",
    "holiday.changed",
}

# Every module that registers a handler. Add yours here.
HANDLER_MODULES: List[str] = [
    "app.services.leave_events",  # area L: leave, approvals, organization
    "app.services.payroll_events",  # area F: payroll lock, attendance re-derivation
]

_handlers: Dict[str, List[Handler]] = defaultdict(list)
_loaded = False


def on(event: str) -> Callable[[Handler], Handler]:
    if event not in EVENTS:
        raise ValueError(f"Unknown domain event: {event}")

    def register(fn: Handler) -> Handler:
        if fn not in _handlers[event]:
            _handlers[event].append(fn)
        return fn

    return register


def _load_handlers() -> None:
    global _loaded
    if _loaded:
        return
    for mod in HANDLER_MODULES:
        importlib.import_module(mod)
    _loaded = True


async def emit(event: str, **payload: Any) -> None:
    """Run every handler for `event`. Exceptions propagate to the caller."""
    if event not in EVENTS:
        raise ValueError(f"Unknown domain event: {event}")
    _load_handlers()
    for handler in list(_handlers.get(event, ())):
        await handler(**payload)
