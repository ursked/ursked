"""
Email notification service.

Uses site-wide SMTP configuration from SiteSettings.

Sending goes through an outbox (models/email_outbox.py). Every send helper
renders its template and INSERTS a row into email_outbox using the session it
is given; nothing talks to SMTP inside a request. The scheduler's
`email_outbox` job (run_due below) delivers queued rows, with retry and
backoff, so an email:

  * exists only if the change it announces committed. `fire_and_forget`
    parks the helper on the request's session (app.database.AppSession),
    which renders it into the same transaction right before committing. It
    used to run in a background task that could send before the request
    committed, or after it rolled back.
  * survives a worker restart. An in-flight background task died with its
    worker; a queued row is still there when the scheduler next runs.
  * is retried. A transient SMTP error used to lose the email.

Every attempt leaves an email_logs row: `sent`, `failed` (after the last
retry), or `skipped` when SMTP is not configured, so "did that email go out?"
has an honest answer. Before, a send with no SMTP left no trace at all.

Scheduled reports are the exception: their attachments can be large binary
workbooks, which do not belong in a table that is polled every minute, and
the report job is itself a claimed, logged, retried-next-run background job.
They send directly through `send_email_with_attachment`.
"""

import asyncio
import logging
import smtplib
from datetime import timedelta
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional, Tuple, Union

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import PENDING_EMAILS, AppSession, AsyncSessionLocal, current_session
from app.models.site_settings import SiteSettings
from app.utils.timeutil import utcnow

logger = logging.getLogger(__name__)

# Delivery attempts before a queued email is given up as `failed`, and the wait
# before each retry (after attempt 1, 2, ...). About six hours end to end: long
# enough to ride out a mail server restart or a rate limit, short enough that a
# "your leave was approved" email is not delivered days late.
MAX_ATTEMPTS = 6
RETRY_BACKOFF = (
    timedelta(minutes=1),
    timedelta(minutes=5),
    timedelta(minutes=15),
    timedelta(hours=1),
    timedelta(hours=4),
)
# Rows one scheduler tick sends; the rest wait a minute.
OUTBOX_BATCH = 50

SMTP_NOT_CONFIGURED = "Email (SMTP) is not configured, so this email was not sent."


def retry_delay(attempts: int) -> timedelta:
    """Wait before the next attempt, after `attempts` attempts so far."""
    return RETRY_BACKOFF[min(max(attempts, 1), len(RETRY_BACKOFF)) - 1]


class EmailService:

    # ── Core ──────────────────────────────────────────────────────────

    @staticmethod
    async def _get_smtp_config(db: AsyncSession) -> Optional[dict]:
        """Read SMTP configuration from SiteSettings. Returns None if not configured."""
        result = await db.execute(select(SiteSettings).limit(1))
        settings = result.scalar_one_or_none()
        if not settings or not settings.smtp_active or not settings.smtp_host:
            return None
        return {
            "host": settings.smtp_host,
            "port": settings.smtp_port,
            "use_ssl": settings.smtp_use_ssl,
            "use_tls": settings.smtp_use_tls,
            "username": settings.smtp_username,
            "password": settings.smtp_password,
            "from_email": settings.smtp_from_email or settings.smtp_username,
            "from_name": settings.smtp_from_name or settings.site_name or "ursked",
            "site_name": settings.site_name or "ursked",
        }

    @staticmethod
    async def _site_name(db: AsyncSession, config: Optional[dict]) -> str:
        """The name emails are signed with, also when SMTP is off (the skipped
        log row still records the subject the email would have had)."""
        if config:
            return config["site_name"]
        name = (await db.execute(select(SiteSettings.site_name).limit(1))).scalar()
        return name or "ursked"

    @staticmethod
    def _html_to_text(html_body: str) -> str:
        """Crude HTML->text fallback so every email carries a plain-text part.

        Not a full renderer: strips tags and collapses whitespace. Good enough
        for spam-filter friendliness; templates may pass an explicit text_body.
        """
        import re
        from html import unescape

        text = re.sub(r"(?is)<(script|style).*?</\1>", "", html_body)
        text = re.sub(r"(?i)<br\s*/?>", "\n", text)
        text = re.sub(r"(?i)</(p|div|tr|h[1-6]|li)>", "\n", text)
        text = re.sub(r"<[^>]+>", "", text)
        text = unescape(text)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
        return text.strip()

    @staticmethod
    def _log_row(
        log_type: Optional[str],
        to_email: str,
        subject: str,
        status: str,
        *,
        tenant_id=None,
        user_id=None,
        error_message: Optional[str] = None,
    ):
        from app.models.email_log import EmailLog

        return EmailLog(
            tenant_id=tenant_id,
            user_id=user_id,
            type=log_type or "email",
            to_email=to_email,
            subject=(subject or "")[:500],
            status=status,
            error_message=(error_message[:2000] if error_message else None),
            sent_at=utcnow() if status == "sent" else None,
        )

    @staticmethod
    async def _log_email(
        log_type: Optional[str],
        to_email: str,
        subject: str,
        status: str,
        *,
        tenant_id=None,
        user_id=None,
        error_message: Optional[str] = None,
        log_id: Optional[int] = None,
    ) -> Optional[int]:
        """Write/update an EmailLog row in its own session. Best-effort: logging
        must never break a send. Returns the row id (for the pending->final flip).
        Used by the direct (attachment) path; queued mail logs in the caller's
        session instead."""
        if not log_type:
            return None
        from app.models.email_log import EmailLog

        try:
            async with AsyncSessionLocal() as db:
                if log_id is None:
                    row = EmailService._log_row(
                        log_type, to_email, subject, status,
                        tenant_id=tenant_id, user_id=user_id, error_message=error_message,
                    )
                    db.add(row)
                    await db.commit()
                    await db.refresh(row)
                    return row.id
                row = await db.get(EmailLog, log_id)
                if row is not None:
                    row.status = status
                    row.error_message = error_message[:2000] if error_message else None
                    if status == "sent":
                        row.sent_at = utcnow()
                    await db.commit()
                return log_id
        except Exception:
            logger.exception("Failed to write email_log (%s -> %s)", to_email, status)
            return log_id

    @staticmethod
    def _smtp_send_blocking(
        smtp_config: dict,
        to_email: str,
        subject: str,
        html_body: str,
        text_body: Optional[str] = None,
        attachment: Optional[Tuple[Union[str, bytes], str, str]] = None,
    ) -> None:
        """One SMTP transaction. Blocking; run it in a thread."""
        plain = text_body or EmailService._html_to_text(html_body or "")
        body = MIMEMultipart("alternative")
        # Order matters: least-preferred (text) first, best (html) last.
        body.attach(MIMEText(plain, "plain", "utf-8"))
        body.attach(MIMEText(html_body or "", "html", "utf-8"))
        if attachment is None:
            msg = body
        else:
            content, filename, mime = attachment
            msg = MIMEMultipart("mixed")
            msg.attach(body)
            maintype, subtype = mime.split("/", 1)
            part = MIMEBase(maintype, subtype)
            # Binary formats (xlsx) arrive as bytes; text ones as str.
            part.set_payload(content if isinstance(content, bytes) else content.encode("utf-8"))
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", "attachment", filename=filename)
            msg.attach(part)
        msg["Subject"] = subject
        msg["From"] = f"{smtp_config['from_name']} <{smtp_config['from_email']}>"
        msg["To"] = to_email

        if smtp_config["use_ssl"]:
            server = smtplib.SMTP_SSL(smtp_config["host"], smtp_config["port"], timeout=15)
        else:
            server = smtplib.SMTP(smtp_config["host"], smtp_config["port"], timeout=15)
            if smtp_config["use_tls"]:
                server.starttls()
        if smtp_config["username"] and smtp_config["password"]:
            server.login(smtp_config["username"], smtp_config["password"])
        server.sendmail(smtp_config["from_email"], [to_email], msg.as_string())
        server.quit()

    @staticmethod
    async def _smtp_send(
        smtp_config: dict,
        to_email: str,
        subject: str,
        html_body: str,
        text_body: Optional[str] = None,
        attachment: Optional[Tuple[Union[str, bytes], str, str]] = None,
    ) -> Tuple[bool, Optional[str]]:
        """Send one email now. Returns (delivered, error message)."""
        try:
            await asyncio.to_thread(
                EmailService._smtp_send_blocking,
                smtp_config, to_email, subject, html_body, text_body, attachment,
            )
            logger.info("Email sent to %s: %s", to_email, subject)
            return True, None
        except Exception as e:  # noqa: BLE001
            logger.exception("Failed to send email to %s: %s", to_email, subject)
            return False, str(e) or e.__class__.__name__

    @staticmethod
    async def _queue(
        db: AsyncSession,
        config: Optional[dict],
        to_email: str,
        subject: str,
        html_body: str,
        *,
        text_body: Optional[str] = None,
        log_type: Optional[str] = None,
        tenant_id=None,
        user_id=None,
    ) -> bool:
        """Put an email in the outbox, in `db`'s transaction. The caller (or
        the request's commit) commits it. Returns False, after logging a
        `skipped` row, when SMTP is not configured."""
        from app.models.email_outbox import EmailOutbox

        if not to_email:
            return False
        if config is None:
            logger.debug("SMTP not configured — skipping email to %s: %s", to_email, subject)
            db.add(EmailService._log_row(
                log_type, to_email, subject, "skipped",
                tenant_id=tenant_id, user_id=user_id, error_message=SMTP_NOT_CONFIGURED,
            ))
            return False
        db.add(EmailOutbox(
            tenant_id=tenant_id,
            user_id=user_id,
            to_email=to_email,
            subject=subject[:500],
            html_body=html_body,
            text_body=text_body,
            log_type=log_type,
            status="queued",
            attempts=0,
            next_attempt_at=utcnow(),
        ))
        return True

    @staticmethod
    async def _send_raw(
        smtp_config: Optional[dict],
        to_email: str,
        subject: str,
        html_body: str,
        *,
        text_body: Optional[str] = None,
        log_type: Optional[str] = None,
        tenant_id=None,
        user_id=None,
    ) -> bool:
        """Send immediately, outside any transaction, logging pending -> sent|failed.

        Kept for callers that must know the result now; everything in the app
        queues through `_queue` instead."""
        if smtp_config is None:
            await EmailService._log_email(
                log_type, to_email, subject, "skipped",
                tenant_id=tenant_id, user_id=user_id, error_message=SMTP_NOT_CONFIGURED,
            )
            return False
        log_id = await EmailService._log_email(
            log_type, to_email, subject, "pending", tenant_id=tenant_id, user_id=user_id
        )
        ok, error = await EmailService._smtp_send(smtp_config, to_email, subject, html_body, text_body)
        await EmailService._log_email(
            log_type, to_email, subject, "sent" if ok else "failed",
            tenant_id=tenant_id, user_id=user_id, error_message=error, log_id=log_id,
        )
        return ok

    @staticmethod
    async def send_email(
        db: AsyncSession,
        to_email: str,
        subject: str,
        html_body: str,
        *,
        log_type: Optional[str] = None,
        tenant_id=None,
        user_id=None,
    ) -> bool:
        """Queue an email in `db`'s transaction. Returns False (and logs a
        `skipped` row) if SMTP is not configured."""
        config = await EmailService._get_smtp_config(db)
        return await EmailService._queue(
            db, config, to_email, subject, html_body,
            log_type=log_type, tenant_id=tenant_id, user_id=user_id,
        )

    @staticmethod
    async def send_email_with_attachment(
        db: AsyncSession,
        to_email: str,
        subject: str,
        html_body: str,
        attachment_content: Union[str, bytes],
        attachment_filename: str,
        attachment_mime: str = "text/csv",
        *,
        log_type: Optional[str] = None,
        tenant_id=None,
        user_id=None,
    ) -> bool:
        """Send an email with a file attachment NOW (not queued; see the
        module docstring). With `log_type`, writes its own email_logs row:
        pending -> sent|failed, or skipped when SMTP is not configured."""
        config = await EmailService._get_smtp_config(db)
        if not config:
            logger.debug("SMTP not configured — skipping email to %s: %s", to_email, subject)
            await EmailService._log_email(
                log_type, to_email, subject, "skipped",
                tenant_id=tenant_id, user_id=user_id, error_message=SMTP_NOT_CONFIGURED,
            )
            return False
        log_id = await EmailService._log_email(
            log_type, to_email, subject, "pending", tenant_id=tenant_id, user_id=user_id
        )
        ok, error = await EmailService._smtp_send(
            config, to_email, subject, html_body,
            attachment=(attachment_content, attachment_filename, attachment_mime),
        )
        await EmailService._log_email(
            log_type, to_email, subject, "sent" if ok else "failed",
            tenant_id=tenant_id, user_id=user_id, error_message=error, log_id=log_id,
        )
        return ok

    # ── Queueing from request code ────────────────────────────────────

    @staticmethod
    def fire_and_forget(coro_factory):
        """
        Queue an email produced by `coro_factory(db)`.

        Usage (unchanged since this used to send from a background task):
            EmailService.fire_and_forget(
                lambda db: EmailService.send_invite_email(db, user_email, ...)
            )

        Inside a request (or a scheduler job) the factory is parked on that
        session and runs just before it commits, so the email is queued in the
        same transaction as the change it describes, and a rollback drops it.
        Outside one (a background task, a script) it runs in a session of its
        own that commits at once: still durable and retried, just not tied to
        anyone else's transaction.
        """
        session = current_session.get()
        if isinstance(session, AppSession) and not session.info.get("closed"):
            session.info.setdefault(PENDING_EMAILS, []).append(coro_factory)
            return

        async def _run():
            try:
                async with AsyncSessionLocal() as db:
                    await coro_factory(db)
                    await db.commit()
            except Exception:
                logger.exception("Queueing a background email failed")

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_run())
        except RuntimeError:
            logger.warning("No running event loop — cannot queue background email")

    @staticmethod
    async def drain_pending(db: AsyncSession, factories) -> None:
        """Run parked email factories against `db` (called by AppSession.commit).

        One broken template must not block the commit it rides on, or the
        other emails: a factory that raises is logged and skipped. Factories
        only read and add rows, so a failure leaves nothing half-written."""
        for factory in factories:
            try:
                await factory(db)
            except Exception:
                logger.exception("Could not queue an email; the change itself is still saved")

    # ── Delivery (scheduler job) ──────────────────────────────────────

    @staticmethod
    async def deliver_outbox(db: AsyncSession, *, now=None, limit: int = OUTBOX_BATCH) -> dict:
        """Send queued emails that are due. Each row is committed on its own,
        so one bad address cannot hold up or re-send the rest.

        The attempt is recorded (and the next retry scheduled) BEFORE talking
        to SMTP: if the worker dies mid-send, the row is retried after its
        backoff rather than every minute. Delivery is therefore at-least-once;
        a crash between the SMTP server accepting a message and the commit
        below can send it twice, which beats silently losing it.
        """
        from app.models.email_outbox import EmailOutbox

        now = now or utcnow()
        ids = (await db.execute(
            select(EmailOutbox.id)
            .where(EmailOutbox.status == "queued", EmailOutbox.next_attempt_at <= now)
            .order_by(EmailOutbox.next_attempt_at, EmailOutbox.id)
            .limit(limit)
        )).scalars().all()
        counts = {"due": len(ids), "sent": 0, "retrying": 0, "failed": 0, "skipped": 0}
        if not ids:
            return counts
        config = await EmailService._get_smtp_config(db)

        for oid in ids:
            row = await db.get(EmailOutbox, oid)
            if row is None or row.status != "queued":
                continue
            if config is None:
                # SMTP was switched off after this was queued. Kept (with its
                # body) so an admin can send it once email works again.
                row.status = "skipped"
                row.last_error = SMTP_NOT_CONFIGURED
                db.add(EmailService._log_row(
                    row.log_type, row.to_email, row.subject, "skipped",
                    tenant_id=row.tenant_id, user_id=row.user_id, error_message=SMTP_NOT_CONFIGURED,
                ))
                await db.commit()
                counts["skipped"] += 1
                continue

            row.attempts = (row.attempts or 0) + 1
            row.next_attempt_at = now + retry_delay(row.attempts)
            await db.commit()

            ok, error = await EmailService._smtp_send(
                config, row.to_email, row.subject, row.html_body or "", row.text_body
            )
            if ok:
                row.status = "sent"
                row.sent_at = utcnow()
                row.last_error = None
                # The body can carry activation and reset links; once
                # delivered there is no reason to keep a copy.
                row.html_body = None
                row.text_body = None
                db.add(EmailService._log_row(
                    row.log_type, row.to_email, row.subject, "sent",
                    tenant_id=row.tenant_id, user_id=row.user_id,
                ))
                counts["sent"] += 1
            else:
                row.last_error = (error or "")[:2000]
                if row.attempts >= MAX_ATTEMPTS:
                    row.status = "failed"
                    db.add(EmailService._log_row(
                        row.log_type, row.to_email, row.subject, "failed",
                        tenant_id=row.tenant_id, user_id=row.user_id,
                        error_message=f"Gave up after {row.attempts} attempts: {error}",
                    ))
                    counts["failed"] += 1
                else:
                    counts["retrying"] += 1
            await db.commit()
        return counts

    @staticmethod
    async def retry_outbox(
        db: AsyncSession, outbox_id: int, tenant_id, *, include_untenanted: bool = False
    ) -> bool:
        """Send a failed or skipped email again on the next tick, with a fresh
        set of attempts. False if there is no such retriable row for this
        tenant (tenant-less system mail only when `include_untenanted`)."""
        from app.models.email_outbox import EmailOutbox

        row = await db.get(EmailOutbox, outbox_id)
        if row is None or row.status not in ("failed", "skipped"):
            return False
        if row.tenant_id != tenant_id and not (row.tenant_id is None and include_untenanted):
            return False
        row.status = "queued"
        row.attempts = 0
        row.next_attempt_at = utcnow()
        row.last_error = None
        return True

    # ── Account Lifecycle ─────────────────────────────────────────────

    @staticmethod
    async def send_tenant_welcome_email(
        db: AsyncSession,
        to_email: str,
        first_name: str,
        org_name: str,
        login_url: str,
        trial_days: int = 14,
    ):
        from app.services.email_templates import tenant_welcome_email

        config = await EmailService._get_smtp_config(db)
        site_name = await EmailService._site_name(db, config)
        subject, html = tenant_welcome_email(first_name, org_name, login_url, trial_days, site_name)
        await EmailService._queue(db, config, to_email, subject, html, log_type="tenant_welcome")

    @staticmethod
    async def send_password_changed_email(
        db: AsyncSession,
        to_email: str,
        first_name: str,
    ):
        from app.services.email_templates import password_changed_email

        config = await EmailService._get_smtp_config(db)
        site_name = await EmailService._site_name(db, config)
        subject, html = password_changed_email(first_name, site_name)
        await EmailService._queue(db, config, to_email, subject, html, log_type="password_changed")

    @staticmethod
    async def send_2fa_enabled_email(
        db: AsyncSession,
        to_email: str,
        first_name: str,
    ):
        from app.services.email_templates import two_factor_enabled_email

        config = await EmailService._get_smtp_config(db)
        site_name = await EmailService._site_name(db, config)
        subject, html = two_factor_enabled_email(first_name, site_name)
        await EmailService._queue(db, config, to_email, subject, html, log_type="2fa_enabled")

    @staticmethod
    async def send_account_deactivated_email(
        db: AsyncSession,
        to_email: str,
        first_name: str,
    ):
        from app.services.email_templates import account_deactivated_email

        config = await EmailService._get_smtp_config(db)
        site_name = await EmailService._site_name(db, config)
        subject, html = account_deactivated_email(first_name, site_name)
        await EmailService._queue(db, config, to_email, subject, html, log_type="account_deactivated")

    @staticmethod
    async def send_invite_email(
        db: AsyncSession,
        to_email: str,
        first_name: str,
        tenant_name: str,
        activation_url: str,
    ):
        from app.services.email_templates import invite_email

        config = await EmailService._get_smtp_config(db)
        site_name = await EmailService._site_name(db, config)
        subject, html = invite_email(first_name, tenant_name, activation_url, site_name)
        await EmailService._queue(db, config, to_email, subject, html, log_type="invite")

    @staticmethod
    async def send_account_activated_email(
        db: AsyncSession,
        to_email: str,
        first_name: str,
        login_url: str,
    ):
        from app.services.email_templates import account_activated_email

        config = await EmailService._get_smtp_config(db)
        site_name = await EmailService._site_name(db, config)
        subject, html = account_activated_email(first_name, login_url, site_name)
        await EmailService._queue(db, config, to_email, subject, html, log_type="account_activated")

    # ── Leave Notifications ───────────────────────────────────────────

    @staticmethod
    async def send_leave_request_notification(
        db: AsyncSession,
        approver_email: str,
        approver_name: str,
        employee_name: str,
        leave_type: str,
        start_date: str,
        end_date: str,
        days: float,
        reason: str,
    ):
        from app.services.email_templates import leave_request_email

        config = await EmailService._get_smtp_config(db)
        site_name = await EmailService._site_name(db, config)
        subject, html = leave_request_email(
            approver_name, employee_name, leave_type, start_date, end_date, days, reason, site_name
        )
        await EmailService._queue(db, config, approver_email, subject, html, log_type="leave_request")

    @staticmethod
    async def send_leave_approved_email(
        db: AsyncSession,
        to_email: str,
        employee_name: str,
        leave_type: str,
        start_date: str,
        end_date: str,
        reviewer_name: str,
    ):
        from app.services.email_templates import leave_approved_email

        config = await EmailService._get_smtp_config(db)
        site_name = await EmailService._site_name(db, config)
        subject, html = leave_approved_email(
            employee_name, leave_type, start_date, end_date, reviewer_name, site_name
        )
        await EmailService._queue(db, config, to_email, subject, html, log_type="leave_approved")

    @staticmethod
    async def send_leave_rejected_email(
        db: AsyncSession,
        to_email: str,
        employee_name: str,
        leave_type: str,
        start_date: str,
        end_date: str,
        reviewer_name: str,
        reviewer_notes: str = "",
    ):
        from app.services.email_templates import leave_rejected_email

        config = await EmailService._get_smtp_config(db)
        site_name = await EmailService._site_name(db, config)
        subject, html = leave_rejected_email(
            employee_name, leave_type, start_date, end_date, reviewer_name, reviewer_notes, site_name
        )
        await EmailService._queue(db, config, to_email, subject, html, log_type="leave_rejected")

    # ── Schedule Notifications ────────────────────────────────────────

    @staticmethod
    async def send_schedule_change_email(
        db: AsyncSession,
        to_email: str,
        employee_name: str,
        changes_summary: str,
    ):
        from app.services.email_templates import schedule_change_email

        config = await EmailService._get_smtp_config(db)
        site_name = await EmailService._site_name(db, config)
        subject, html = schedule_change_email(employee_name, changes_summary, site_name)
        await EmailService._queue(db, config, to_email, subject, html, log_type="schedule_change")

    @staticmethod
    async def send_schedule_change_request_email(
        db: AsyncSession,
        approver_email: str,
        approver_name: str,
        requester_name: str,
        request_type: str,
        req_date: str,
        reason: str,
    ):
        from app.services.email_templates import schedule_change_request_email

        config = await EmailService._get_smtp_config(db)
        site_name = await EmailService._site_name(db, config)
        subject, html = schedule_change_request_email(
            approver_name, requester_name, request_type, req_date, reason, site_name
        )
        await EmailService._queue(
            db, config, approver_email, subject, html, log_type="schedule_change_request"
        )

    @staticmethod
    async def send_schedule_change_decision_email(
        db: AsyncSession,
        to_email: str,
        requester_name: str,
        decision: str,
        request_type: str,
        req_date: str,
        reviewer_name: str,
        notes: str = "",
    ):
        from app.services.email_templates import schedule_change_decision_email

        config = await EmailService._get_smtp_config(db)
        site_name = await EmailService._site_name(db, config)
        subject, html = schedule_change_decision_email(
            requester_name, decision, request_type, req_date, reviewer_name, notes,
            site_name,
        )
        log_type = "schedule_change_approved" if decision == "approved" else "schedule_change_rejected"
        await EmailService._queue(db, config, to_email, subject, html, log_type=log_type)

    # ── Overtime Notifications ────────────────────────────────────────

    @staticmethod
    async def send_overtime_decision_email(
        db: AsyncSession,
        to_email: str,
        employee_name: str,
        decision: str,
        ot_date: str,
        hours: str,
        reviewer_name: str,
        notes: str = "",
    ):
        from app.services.email_templates import overtime_decision_email

        config = await EmailService._get_smtp_config(db)
        site_name = await EmailService._site_name(db, config)
        subject, html = overtime_decision_email(
            employee_name, decision, ot_date, hours, reviewer_name, notes, site_name
        )
        log_type = {
            "approved": "overtime_approved",
            "rejected": "overtime_rejected",
            "converted": "overtime_converted",
        }.get(decision, "overtime_decision")
        await EmailService._queue(db, config, to_email, subject, html, log_type=log_type)

    # ── Account Access Changes ────────────────────────────────────────

    @staticmethod
    async def send_account_reinstated_email(
        db: AsyncSession,
        to_email: str,
        first_name: str,
        login_url: str,
    ):
        from app.services.email_templates import account_reinstated_email

        config = await EmailService._get_smtp_config(db)
        site_name = await EmailService._site_name(db, config)
        subject, html = account_reinstated_email(first_name, login_url, site_name)
        await EmailService._queue(db, config, to_email, subject, html, log_type="account_reinstated")

    @staticmethod
    async def send_roles_changed_email(
        db: AsyncSession,
        to_email: str,
        first_name: str,
        role_labels: str,
    ):
        from app.services.email_templates import roles_changed_email

        config = await EmailService._get_smtp_config(db)
        site_name = await EmailService._site_name(db, config)
        subject, html = roles_changed_email(first_name, role_labels, site_name)
        await EmailService._queue(db, config, to_email, subject, html, log_type="roles_changed")

    # ── Security ──────────────────────────────────────────────────────

    @staticmethod
    async def send_password_reset_email(
        db: AsyncSession,
        to_email: str,
        first_name: str,
        reset_url: str,
        expiry_minutes: int,
    ):
        from app.services.email_templates import password_reset_email

        config = await EmailService._get_smtp_config(db)
        site_name = await EmailService._site_name(db, config)
        subject, html = password_reset_email(
            first_name, reset_url, expiry_minutes, site_name
        )
        await EmailService._queue(db, config, to_email, subject, html, log_type="password_reset")

    @staticmethod
    async def send_security_alert_email(
        db: AsyncSession,
        to_email: str,
        first_name: str,
        event: str,
        ip_address: str,
        when: str,
        log_type: str = "security_alert",
    ):
        from app.services.email_templates import security_alert_email

        config = await EmailService._get_smtp_config(db)
        site_name = await EmailService._site_name(db, config)
        subject, html = security_alert_email(
            first_name, event, ip_address, when, site_name
        )
        await EmailService._queue(db, config, to_email, subject, html, log_type=log_type)


async def run_due(db: AsyncSession) -> dict:
    """Scheduler job: deliver queued emails that are due (see deliver_outbox).
    Safe to call every minute; only the scheduler leader calls it."""
    return await EmailService.deliver_outbox(db)
