"""Background job dispatcher.

Runs on the existing 60-second scheduler tick. Each daily/yearly job claims its
work by inserting a JobRun with a unique (job_name, tenant_id, period_key). The
unique constraint provides crash-safe, restart-safe, at-most-once execution:
a second attempt for the same period raises IntegrityError and is skipped.

Jobs are intentionally idempotent at the row level too (the leave year-end
service checks for existing adjustments before writing), so a job that crashes
mid-run can be retried by clearing its failed JobRun.
"""
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.job_run import JobRun

logger = logging.getLogger(__name__)


class JobService:

    @staticmethod
    async def claim(
        job_name: str,
        period_key: str,
        tenant_id: Optional[UUID] = None,
    ) -> Optional[int]:
        """Atomically claim a job slot. Returns the JobRun id if this caller won
        the claim, or None if the job already ran (or is running) for this
        period. Uses its own session so an IntegrityError does not poison the
        caller's transaction."""
        async with AsyncSessionLocal() as db:
            run = JobRun(
                job_name=job_name,
                tenant_id=tenant_id,
                period_key=period_key,
                status="running",
                started_at=datetime.utcnow(),
            )
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
            run.finished_at = datetime.utcnow()
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
    ) -> None:
        """Log a completed run in one shot (used for events like scheduled
        exports where claiming is not needed for idempotency)."""
        async with AsyncSessionLocal() as db:
            run = JobRun(
                job_name=job_name,
                tenant_id=tenant_id,
                period_key=period_key,
                status=status,
                started_at=datetime.utcnow(),
                finished_at=datetime.utcnow(),
                error=error,
                meta=meta,
            )
            db.add(run)
            try:
                await db.commit()
            except IntegrityError:
                await db.rollback()

    @staticmethod
    async def run_due_jobs() -> None:
        """Entry point called every scheduler tick. Runs the daily/yearly leave
        jobs. Import locally to avoid circular imports at module load."""
        from app.services.leave_yearend_service import LeaveYearEndService

        try:
            await LeaveYearEndService.run(JobService)
        except Exception:
            logger.exception("Leave year-end jobs failed")
