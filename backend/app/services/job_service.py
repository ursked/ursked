"""Background job ledger.

Each daily/yearly job claims its work by writing a JobRun with a unique
(job_name, tenant_id, period_key). The unique key gives crash-safe,
restart-safe, at-most-once execution: a second claim for the same period finds
the row and is skipped.

Claiming used to be a bare INSERT that relied on the unique constraint to
fail. Every worker did that for every tenant every minute, so PostgreSQL
logged a duplicate-key error per attempt and job_runs_id_seq climbed past half
a million for 47 real rows. A claim now looks first and only inserts when the
period is unclaimed, with `ON CONFLICT DO NOTHING` for the rare race; only the
scheduler leader runs jobs (app.services.scheduler), so the race is rarer still.

A claim left `running` by a crash used to block its period forever (a year-end
carry-over interrupted mid-run was simply never retried). A `running` claim
older than STALE_AFTER is now taken over by the next claimant. Jobs are
idempotent at the row level too (the leave year-end service checks for
existing adjustments before writing), so finishing someone else's half-done
run is safe.
"""
import logging
from datetime import timedelta
from typing import Optional
from uuid import UUID

from sqlalchemy import and_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from app.database import AsyncSessionLocal
from app.models.job_run import JobRun
from app.utils.timeutil import as_utc, utcnow

logger = logging.getLogger(__name__)

# How long a `running` claim may go without finishing before the next claimant
# may take it over. Thirty minutes: the slowest job (year-end carry-over for a
# whole company) takes seconds, the scheduler gives every job at most
# JOB_TIMEOUT (15 minutes), so a claim still `running` after 30 is a crash.
STALE_AFTER = timedelta(minutes=30)


def _tenant_match(tenant_id: Optional[UUID]):
    # NULL never equals NULL in SQL; a global job's claim has tenant_id NULL.
    return JobRun.tenant_id.is_(None) if tenant_id is None else JobRun.tenant_id == tenant_id


class JobService:

    @staticmethod
    async def claim(
        job_name: str,
        period_key: str,
        tenant_id: Optional[UUID] = None,
    ) -> Optional[int]:
        """Claim a job slot. Returns the JobRun id if this caller won the
        claim, or None if the job already ran (or is genuinely running) for
        this period. Uses its own session so a failure never poisons the
        caller's transaction."""
        async with AsyncSessionLocal() as db:
            key = and_(
                JobRun.job_name == job_name,
                JobRun.period_key == period_key,
                _tenant_match(tenant_id),
            )
            existing = (await db.execute(select(JobRun).where(key))).scalar_one_or_none()
            now = utcnow()
            if existing is not None:
                started = as_utc(existing.started_at)
                if existing.status != "running" or (started and now - started < STALE_AFTER):
                    return None
                # Reclaim a crashed run. Conditional on the old start time, so
                # two claimants cannot both take it over.
                result = await db.execute(
                    update(JobRun)
                    .where(JobRun.id == existing.id, JobRun.status == "running",
                           JobRun.started_at == existing.started_at)
                    .values(started_at=now, finished_at=None,
                            error=f"Taken over: the previous run started {started:%Y-%m-%d %H:%M} UTC "
                                  "and never finished.")
                    .execution_options(synchronize_session=False)
                )
                await db.commit()
                if result.rowcount != 1:
                    return None
                logger.warning("Reclaimed stale job run %s (%s %s)", existing.id, job_name, period_key)
                return existing.id

            values = dict(
                job_name=job_name, tenant_id=tenant_id, period_key=period_key,
                status="running", started_at=now,
            )
            if db.bind.dialect.name == "postgresql":
                run_id = (await db.execute(
                    pg_insert(JobRun).values(**values)
                    .on_conflict_do_nothing(constraint="uq_job_run_key")
                    .returning(JobRun.id)
                )).scalar_one_or_none()
                await db.commit()
                return run_id
            run = JobRun(**values)
            db.add(run)
            try:
                await db.commit()
            except IntegrityError:
                await db.rollback()
                return None
            return run.id

    @staticmethod
    async def finish(run_id: int, *, status: str = "success", error: Optional[str] = None, meta: Optional[dict] = None) -> None:
        async with AsyncSessionLocal() as db:
            run = await db.get(JobRun, run_id)
            if not run:
                return
            run.status = status
            run.error = error
            if meta is not None:
                run.meta = meta
            run.finished_at = utcnow()
            await db.commit()

    @staticmethod
    async def record(
        job_name: str,
        period_key: str,
        *,
        tenant_id: Optional[UUID] = None,
        status: str = "success",
        error: Optional[str] = None,
        meta: Optional[dict] = None,
        started_at=None,
    ) -> None:
        """Log a completed run in one shot (the scheduler's record of a job
        that needs no claim, e.g. a tick that sent some emails)."""
        async with AsyncSessionLocal() as db:
            now = utcnow()
            run = JobRun(
                job_name=job_name,
                tenant_id=tenant_id,
                period_key=period_key,
                status=status,
                started_at=started_at or now,
                finished_at=now,
                error=error,
                meta=meta,
            )
            db.add(run)
            try:
                await db.commit()
            except IntegrityError:
                await db.rollback()

    @staticmethod
    async def run_due_jobs() -> dict:
        """The leave year-end jobs (carry-over, cash conversion, expiry), each
        claimed per tenant per period. Import locally to avoid circular
        imports at module load."""
        from app.services.leave_yearend_service import LeaveYearEndService

        await LeaveYearEndService.run(JobService)
        return {}


async def run_due(db) -> dict:
    """Scheduler entry point for the leave year-end jobs. The session is not
    used: each claim and each unit of work has its own, so one tenant's
    failure is recorded against that tenant alone."""
    return await JobService.run_due_jobs()
