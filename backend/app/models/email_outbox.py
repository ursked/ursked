from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base
from app.utils.timeutil import utcnow


class EmailOutbox(Base):
    """An email waiting to be sent, written in the same transaction as the
    change it announces.

    Emails used to be sent from a background task started inside the request,
    before the request's transaction committed: an "approved" email could go
    out for an approval that then rolled back, and a worker restart silently
    dropped whatever was in flight. Now the request only inserts a row here; if
    the request rolls back, so does the row. The scheduler's outbox job sends
    queued rows, retrying with backoff (see email_service.deliver_outbox).

    Unlike email_logs, this table does hold the body: it has to, to send it. A
    sent row's body is cleared once it is delivered, and the daily cleanup
    removes finished rows, so this is never an archive of activation links.
    Attachments are not stored here (scheduled reports send directly from their
    own job; see scheduled_export_service).
    """

    __tablename__ = "email_outbox"
    __table_args__ = (
        Index("ix_email_outbox_status_next", "status", "next_attempt_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    to_email = Column(String(255), nullable=False)
    subject = Column(String(500), nullable=False)
    html_body = Column(Text, nullable=True)
    text_body = Column(Text, nullable=True)
    # Template key, copied to email_logs when the row finishes (e.g. 'invite').
    log_type = Column(String(60), nullable=True)
    # queued -> sent | failed (gave up after MAX_ATTEMPTS) | skipped (SMTP off)
    status = Column(String(20), nullable=False, default="queued")
    attempts = Column(Integer, nullable=False, default=0)
    next_attempt_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
    sent_at = Column(DateTime(timezone=True), nullable=True)
