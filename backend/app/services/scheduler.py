"""The background scheduler: one leader, a registry of jobs, one tick a minute.

Why a leader. The API runs as several uvicorn workers (4 in the shipped
compose file), and each used to run its own copy of the scheduler loop with no
coordination: scheduled reports went out 2-4 times and every worker raced
every other for each job-ledger claim. Now every worker runs the loop, but a
job only runs in the worker holding a PostgreSQL session-level advisory lock
(LEADER_LOCK_KEY), taken on a dedicated connection and held for the life of
that worker. The others try to take it on every tick, so if the leader dies
(its connection closes and PostgreSQL releases the lock) another worker takes
over within a minute. The lock is released on shutdown. On any other database
(the SQLite test suite) there is nothing to coordinate and every caller leads.

The registry. JOBS lists each job by dotted path to an `async def run_due(db)`
that is idempotent and safe to call repeatedly. Each job runs in its own
session with its own error handling and a time limit, so one failing or hung
job cannot stop the others; its duration and result are logged, and recorded
in job_runs (shown under Settings > Background jobs) whenever it did something
or failed. Emails a job queues through EmailService.fire_and_forget join the
job's own transaction, like a request's.

Cadence:
  TICK    every tick (once a minute). For work that is due at a moment:
          scheduled reports, queued email, clock-outs and no-shows.
  HOURLY  once per clock hour. For jobs that judge "today" themselves in each
          company's timezone and keep their own once-a-day ledger (leave
          year-end and reminders), or that pace themselves (holiday sync:
          daily, a failing feed hourly). Running them every minute only cost
          queries.
  DAILY   once per company-local day. The scheduler checks hourly; the job
          claims each tenant's local day in job_runs, so it runs once a day
          per company at its own local time (housekeeping, after 03:00).

Areas add their jobs here by dotted path (see ops/AUDIT_FIX_CONTRACTS.md).
"""

from __future__ import annotations

import asyncio
import importlib
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, Optional, Sequence

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from app.utils.timeutil import utcnow

logger = logging.getLogger(__name__)

TICK = "tick"
HOURLY = "hourly"
DAILY = "daily"

TICK_SECONDS = 60
# Longest any one job may run before it is cancelled and recorded as failed.
JOB_TIMEOUT = timedelta(minutes=15)
# pg_advisory_lock key for the scheduler leader. Arbitrary but fixed; any other
# advisory lock in this database must use a different number.
LEADER_LOCK_KEY = 7_345_109_201_655_001


@dataclass(frozen=True)
class Job:
    name: str
    path: str
    cadence: str = TICK
    timeout: timedelta = JOB_TIMEOUT


JOBS: Sequence[Job] = (
    # Area R: scheduled report exports (claims each due run; sends directly).
    Job("scheduled_exports", "app.services.scheduled_export_service.run_due", TICK),
    # Area A: deliver the email outbox, with retry and backoff.
    Job("email_outbox", "app.services.email_service.run_due", TICK),
    # Area F: close forgotten clock-ins, mark no-shows absent.
    Job("attendance_automation", "app.services.attendance_automation.run_due", TICK),
    # Leave year-end carry-over, cash conversion and expiry (per tenant, own ledger).
    Job("leave_year_end", "app.services.job_service.run_due", HOURLY),
    # Area L: approval reminders, escalation and expiry (once a tenant-day).
    Job("leave_reminders", "app.services.leave_reminder_service.run_due", HOURLY),
    # Area S: live holiday feed (daily per tenant, failing feeds hourly).
    Job("holiday_sync", "app.services.holiday_sync_service.run_due", HOURLY),
    # Area A: prune sessions, read notifications, old logs (once a company day).
    Job("housekeeping", "app.services.housekeeping_service.run_due", DAILY),
)


def resolve(path: str) -> Callable[..., Any]:
    """The callable at a dotted path, e.g. 'app.services.x.run_due'."""
    module, _, attr = path.rpartition(".")
    return getattr(importlib.import_module(module), attr)


def period_key(cadence: str, now: datetime) -> str:
    """The slot a run belongs to: the minute for TICK jobs, else the hour."""
    return now.strftime("%Y-%m-%dT%H:%M" if cadence == TICK else "%Y-%m-%dT%H")


def did_work(result: Any) -> bool:
    """Whether a job's result reports anything done (any non-zero count)."""
    if isinstance(result, dict):
        return any(did_work(v) for v in result.values())
    if isinstance(result, bool):
        return result
    if isinstance(result, (int, float)):
        return result != 0
    return False


def _jsonable(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, default=str))
    except (TypeError, ValueError):
        return {"repr": repr(value)[:500]}


@dataclass
class SchedulerState:
    """What this leader last ran. In memory on purpose: a new leader starts
    empty and runs everything once, which idempotent jobs make harmless."""
    last_period: Dict[str, str] = field(default_factory=dict)

    def is_due(self, job: Job, now: datetime) -> bool:
        if job.cadence == TICK:
            return True
        return self.last_period.get(job.name) != period_key(job.cadence, now)

    def mark(self, job: Job, now: datetime) -> None:
        self.last_period[job.name] = period_key(job.cadence, now)


class LeaderLock:
    """A PostgreSQL session-level advisory lock held on a dedicated connection.

    The connection comes from its own engine with no pool: returning a
    lock-holding connection to a shared pool would hand the lock to whatever
    request borrowed it next, and closing a pooled connection does not end
    the database session. Closing this one does, which releases the lock.
    """

    def __init__(self, url: str, key: int = LEADER_LOCK_KEY):
        self.url = url
        self.key = key
        self.enabled = make_url(url).get_backend_name() == "postgresql"
        self._engine: Optional[AsyncEngine] = None
        self._conn: Optional[AsyncConnection] = None

    @property
    def is_leader(self) -> bool:
        return not self.enabled or self._conn is not None

    async def hold(self) -> bool:
        """True if this process is (still) the leader. Cheap when it is."""
        if not self.enabled:
            return True
        if self._conn is not None:
            try:
                await self._conn.execute(text("SELECT 1"))
                await self._conn.commit()
                return True
            except Exception:  # noqa: BLE001 - the connection died, and the lock with it
                logger.warning("Scheduler leader lost its database connection; re-electing")
                await self._drop()
        try:
            if self._engine is None:
                self._engine = create_async_engine(self.url, poolclass=NullPool)
            conn = await self._engine.connect()
            got = (await conn.execute(
                text("SELECT pg_try_advisory_lock(:key)"), {"key": self.key}
            )).scalar()
            # Session-level: the lock outlives this transaction, so do not sit
            # "idle in transaction" for the life of the worker.
            await conn.commit()
        except Exception:  # noqa: BLE001 - database down; try again next tick
            logger.exception("Scheduler could not reach the database to elect a leader")
            return False
        if got:
            self._conn = conn
            logger.info("This worker is now the scheduler leader")
            return True
        await conn.close()
        return False

    async def _drop(self) -> None:
        conn, self._conn = self._conn, None
        if conn is not None:
            try:
                await conn.invalidate()
            except Exception:  # noqa: BLE001
                pass

    async def release(self) -> None:
        """Give up leadership (shutdown). Unlocks explicitly, then closes."""
        conn, self._conn = self._conn, None
        if conn is not None:
            try:
                await conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": self.key})
                await conn.commit()
            except Exception:  # noqa: BLE001 - closing below releases it anyway
                pass
            try:
                await conn.close()
            except Exception:  # noqa: BLE001
                pass
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None


async def run_job(job: Job, now: datetime, session_factory=None, *, record: bool = True) -> dict:
    """Run one job in its own session. Never raises (except cancellation).
    Returns {"status", "result", "error", "duration_s"}."""
    from app.database import AsyncSessionLocal, current_session
    from app.services.job_service import JobService

    session_factory = session_factory or AsyncSessionLocal
    started = utcnow()
    t0 = time.monotonic()
    result: Any = None
    error: Optional[str] = None
    try:
        fn = resolve(job.path)
        async with session_factory() as db:
            token = current_session.set(db)
            try:
                result = await asyncio.wait_for(fn(db), timeout=job.timeout.total_seconds())
                # Jobs commit their own work; this also queues any email the
                # job asked for after its last commit.
                await db.commit()
            finally:
                current_session.reset(token)
        status = "success"
    except asyncio.CancelledError:
        raise
    except asyncio.TimeoutError:
        status, error = "failed", f"Did not finish within {int(job.timeout.total_seconds() // 60)} minutes."
        logger.error("Scheduled job %s timed out", job.name)
    except Exception as exc:  # noqa: BLE001 - one job must not stop the others
        status, error = "failed", (str(exc) or exc.__class__.__name__)[:2000]
        logger.exception("Scheduled job %s failed", job.name)
    duration = round(time.monotonic() - t0, 3)
    result = _jsonable(result)
    log = logger.info if (status == "failed" or did_work(result) or job.cadence != TICK) else logger.debug
    log("Scheduled job %s: %s in %.2fs %s", job.name, status, duration, result if result is not None else "")

    if record and (status == "failed" or job.cadence != TICK or did_work(result)):
        try:
            await JobService.record(
                job.name, period_key(job.cadence, now), status=status, error=error,
                meta={"result": result, "duration_s": duration}, started_at=started,
            )
        except Exception:  # noqa: BLE001 - the ledger is informational here
            logger.exception("Could not record the run of %s", job.name)
    return {"status": status, "result": result, "error": error, "duration_s": duration}


async def run_tick(
    jobs: Sequence[Job], state: SchedulerState, now: Optional[datetime] = None,
    session_factory=None, *, record: bool = True,
) -> Dict[str, dict]:
    """Run every job that is due this tick, one after another."""
    now = now or utcnow()
    outcomes: Dict[str, dict] = {}
    for job in jobs:
        if not state.is_due(job, now):
            continue
        state.mark(job, now)
        outcomes[job.name] = await run_job(job, now, session_factory, record=record)
    return outcomes


async def scheduler_loop(
    jobs: Sequence[Job] = JOBS, *, url: Optional[str] = None, tick_seconds: float = TICK_SECONDS,
) -> None:
    """Run forever (until cancelled): each tick, if this worker leads, run
    the due jobs. Releases leadership when cancelled."""
    from app.config import settings

    leader = LeaderLock(url or settings.DATABASE_URL)
    state = SchedulerState()
    try:
        while True:
            await asyncio.sleep(tick_seconds)
            if not await leader.hold():
                continue
            await run_tick(jobs, state)
    finally:
        await leader.release()
