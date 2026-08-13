from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class EmailLog(Base):
    """One row per send attempt so 'did that email go out?' is answerable.

    Written 'pending' before the SMTP call and flipped to 'sent'/'failed' after,
    so a crash mid-send still leaves a visible record. There is deliberately NO
    body/html column: bodies carry invite/activation tokens and an admin-readable
    archive of them would be an uninventoried credential store.

    tenant_id is nullable: some sends (e.g. tenant-welcome during signup) happen
    without a tenant context.
    """

    __tablename__ = "email_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    type = Column(String(60), nullable=False, index=True)  # template key, e.g. 'invite'
    to_email = Column(String(255), nullable=False, index=True)
    subject = Column(String(500), nullable=False)
    status = Column(String(20), nullable=False, default="pending", index=True)  # pending|sent|failed
    error_message = Column(Text, nullable=True)
    sent_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, index=True)
