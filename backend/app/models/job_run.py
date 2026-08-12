from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.database import Base


class JobRun(Base):
    """Idempotency ledger for background jobs.

    A job claims work by inserting a row with a unique (job_name, tenant_id,
    period_key). The unique constraint means a second attempt for the same
    period fails fast, so daily/yearly jobs run exactly once even across
    restarts or overlapping scheduler ticks.
    """

    __tablename__ = "job_runs"
    __table_args__ = (
        UniqueConstraint("job_name", "tenant_id", "period_key", name="uq_job_run_key"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_name = Column(String(50), nullable=False, index=True)
    # Nullable: some jobs are global rather than per-tenant.
    tenant_id = Column(UUID(as_uuid=True), nullable=True, index=True)
    # Logical run key, e.g. "2026" for a yearly job or "2026-08-11" for daily.
    period_key = Column(String(64), nullable=False)
    status = Column(String(20), nullable=False, default="running")  # running/success/failed
    started_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    error = Column(Text, nullable=True)
    meta = Column(JSONB, nullable=True)
