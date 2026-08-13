"""
Email notification service.

Uses site-wide SMTP configuration from SiteSettings.
All sends are fire-and-forget via asyncio.create_task so they don't block API responses.
"""

import asyncio
import logging
import smtplib
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.site_settings import SiteSettings

logger = logging.getLogger(__name__)


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
        must never break a send. Returns the row id (for the pending->final flip)."""
        if not log_type:
            return None
        from datetime import datetime

        from app.models.email_log import EmailLog

        try:
            async with AsyncSessionLocal() as db:
                if log_id is None:
                    row = EmailLog(
                        tenant_id=tenant_id,
                        user_id=user_id,
                        type=log_type,
                        to_email=to_email,
                        subject=subject[:500],
                        status=status,
                        error_message=(error_message[:2000] if error_message else None),
                        sent_at=datetime.utcnow() if status == "sent" else None,
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
                        row.sent_at = datetime.utcnow()
                    await db.commit()
                return log_id
        except Exception:
            logger.exception("Failed to write email_log (%s -> %s)", to_email, status)
            return log_id

    @staticmethod
    async def _send_raw(
        smtp_config: dict,
        to_email: str,
        subject: str,
        html_body: str,
        *,
        text_body: Optional[str] = None,
        log_type: Optional[str] = None,
        tenant_id=None,
        user_id=None,
    ) -> bool:
        """Send a single email via SMTP. Runs blocking I/O in a thread.

        Records an EmailLog row (pending -> sent|failed) when log_type is given.
        Always attaches a plain-text alternative before the HTML part.
        """
        plain = text_body or EmailService._html_to_text(html_body)

        def _do_send():
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = f"{smtp_config['from_name']} <{smtp_config['from_email']}>"
            msg["To"] = to_email
            # Order matters: least-preferred (text) first, best (html) last.
            msg.attach(MIMEText(plain, "plain", "utf-8"))
            msg.attach(MIMEText(html_body, "html", "utf-8"))

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

        log_id = await EmailService._log_email(
            log_type, to_email, subject, "pending", tenant_id=tenant_id, user_id=user_id
        )
        try:
            await asyncio.to_thread(_do_send)
            logger.info("Email sent to %s: %s", to_email, subject)
            await EmailService._log_email(
                log_type, to_email, subject, "sent",
                tenant_id=tenant_id, user_id=user_id, log_id=log_id,
            )
            return True
        except Exception as e:  # noqa: BLE001
            logger.exception("Failed to send email to %s: %s", to_email, subject)
            await EmailService._log_email(
                log_type, to_email, subject, "failed",
                tenant_id=tenant_id, user_id=user_id, error_message=str(e), log_id=log_id,
            )
            return False

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
        """Public send method. Reads SMTP config and sends. Returns False if SMTP not configured."""
        config = await EmailService._get_smtp_config(db)
        if not config:
            logger.debug("SMTP not configured — skipping email to %s: %s", to_email, subject)
            return False
        return await EmailService._send_raw(
            config, to_email, subject, html_body,
            log_type=log_type, tenant_id=tenant_id, user_id=user_id,
        )

    @staticmethod
    async def send_email_with_attachment(
        db: AsyncSession,
        to_email: str,
        subject: str,
        html_body: str,
        attachment_content: str,
        attachment_filename: str,
        attachment_mime: str = "text/csv",
    ) -> bool:
        """Send an email with a file attachment."""
        config = await EmailService._get_smtp_config(db)
        if not config:
            logger.debug("SMTP not configured — skipping email to %s: %s", to_email, subject)
            return False

        def _do_send():
            msg = MIMEMultipart("mixed")
            msg["Subject"] = subject
            msg["From"] = f"{config['from_name']} <{config['from_email']}>"
            msg["To"] = to_email
            msg.attach(MIMEText(html_body, "html", "utf-8"))

            maintype, subtype = attachment_mime.split("/", 1)
            attachment = MIMEBase(maintype, subtype)
            attachment.set_payload(attachment_content.encode("utf-8"))
            encoders.encode_base64(attachment)
            attachment.add_header(
                "Content-Disposition", "attachment", filename=attachment_filename
            )
            msg.attach(attachment)

            if config["use_ssl"]:
                server = smtplib.SMTP_SSL(config["host"], config["port"], timeout=15)
            else:
                server = smtplib.SMTP(config["host"], config["port"], timeout=15)
                if config["use_tls"]:
                    server.starttls()
            if config["username"] and config["password"]:
                server.login(config["username"], config["password"])
            server.sendmail(config["from_email"], [to_email], msg.as_string())
            server.quit()

        try:
            await asyncio.to_thread(_do_send)
            logger.info("Email with attachment sent to %s: %s", to_email, subject)
            return True
        except Exception:
            logger.exception("Failed to send email with attachment to %s: %s", to_email, subject)
            return False

    @staticmethod
    def fire_and_forget(coro_factory):
        """
        Schedule an email send as a background task with its own DB session.

        Usage:
            EmailService.fire_and_forget(
                lambda db: EmailService.send_invite_email(db, user_email, ...)
            )
        """
        async def _run():
            try:
                async with AsyncSessionLocal() as db:
                    await coro_factory(db)
            except Exception:
                logger.exception("Background email task failed")

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_run())
        except RuntimeError:
            logger.warning("No running event loop — cannot schedule background email")

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
        if not config:
            logger.debug("SMTP not configured — skipping tenant welcome email to %s", to_email)
            return
        site_name = config["site_name"]
        subject, html = tenant_welcome_email(first_name, org_name, login_url, trial_days, site_name)
        await EmailService._send_raw(config, to_email, subject, html, log_type="tenant_welcome")

    @staticmethod
    async def send_password_changed_email(
        db: AsyncSession,
        to_email: str,
        first_name: str,
    ):
        from app.services.email_templates import password_changed_email

        config = await EmailService._get_smtp_config(db)
        if not config:
            return
        site_name = config["site_name"]
        subject, html = password_changed_email(first_name, site_name)
        await EmailService._send_raw(config, to_email, subject, html, log_type="password_changed")

    @staticmethod
    async def send_2fa_enabled_email(
        db: AsyncSession,
        to_email: str,
        first_name: str,
    ):
        from app.services.email_templates import two_factor_enabled_email

        config = await EmailService._get_smtp_config(db)
        if not config:
            return
        site_name = config["site_name"]
        subject, html = two_factor_enabled_email(first_name, site_name)
        await EmailService._send_raw(config, to_email, subject, html, log_type="2fa_enabled")

    @staticmethod
    async def send_account_deactivated_email(
        db: AsyncSession,
        to_email: str,
        first_name: str,
    ):
        from app.services.email_templates import account_deactivated_email

        config = await EmailService._get_smtp_config(db)
        if not config:
            return
        site_name = config["site_name"]
        subject, html = account_deactivated_email(first_name, site_name)
        await EmailService._send_raw(config, to_email, subject, html, log_type="account_deactivated")

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
        if not config:
            logger.debug("SMTP not configured — skipping invite email to %s", to_email)
            return
        site_name = config["site_name"]
        subject, html = invite_email(first_name, tenant_name, activation_url, site_name)
        await EmailService._send_raw(config, to_email, subject, html, log_type="invite")

    @staticmethod
    async def send_account_activated_email(
        db: AsyncSession,
        to_email: str,
        first_name: str,
        login_url: str,
    ):
        from app.services.email_templates import account_activated_email

        config = await EmailService._get_smtp_config(db)
        if not config:
            logger.debug("SMTP not configured — skipping activation email to %s", to_email)
            return
        site_name = config["site_name"]
        subject, html = account_activated_email(first_name, login_url, site_name)
        await EmailService._send_raw(config, to_email, subject, html, log_type="account_activated")

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
        if not config:
            return
        site_name = config["site_name"]
        subject, html = leave_request_email(
            approver_name, employee_name, leave_type, start_date, end_date, days, reason, site_name
        )
        await EmailService._send_raw(config, approver_email, subject, html, log_type="leave_request")

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
        if not config:
            return
        site_name = config["site_name"]
        subject, html = leave_approved_email(
            employee_name, leave_type, start_date, end_date, reviewer_name, site_name
        )
        await EmailService._send_raw(config, to_email, subject, html, log_type="leave_approved")

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
        if not config:
            return
        site_name = config["site_name"]
        subject, html = leave_rejected_email(
            employee_name, leave_type, start_date, end_date, reviewer_name, reviewer_notes, site_name
        )
        await EmailService._send_raw(config, to_email, subject, html, log_type="leave_rejected")

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
        if not config:
            return
        site_name = config["site_name"]
        subject, html = schedule_change_email(employee_name, changes_summary, site_name)
        await EmailService._send_raw(config, to_email, subject, html, log_type="schedule_change")

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
        if not config:
            return
        subject, html = schedule_change_request_email(
            approver_name, requester_name, request_type, req_date, reason, config["site_name"]
        )
        await EmailService._send_raw(
            config, approver_email, subject, html, log_type="schedule_change_request"
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
        if not config:
            return
        subject, html = schedule_change_decision_email(
            requester_name, decision, request_type, req_date, reviewer_name, notes,
            config["site_name"],
        )
        log_type = "schedule_change_approved" if decision == "approved" else "schedule_change_rejected"
        await EmailService._send_raw(config, to_email, subject, html, log_type=log_type)

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
        if not config:
            return
        subject, html = overtime_decision_email(
            employee_name, decision, ot_date, hours, reviewer_name, notes, config["site_name"]
        )
        log_type = {
            "approved": "overtime_approved",
            "rejected": "overtime_rejected",
            "converted": "overtime_converted",
        }.get(decision, "overtime_decision")
        await EmailService._send_raw(config, to_email, subject, html, log_type=log_type)

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
        if not config:
            return
        subject, html = account_reinstated_email(first_name, login_url, config["site_name"])
        await EmailService._send_raw(config, to_email, subject, html, log_type="account_reinstated")

    @staticmethod
    async def send_roles_changed_email(
        db: AsyncSession,
        to_email: str,
        first_name: str,
        role_labels: str,
    ):
        from app.services.email_templates import roles_changed_email

        config = await EmailService._get_smtp_config(db)
        if not config:
            return
        subject, html = roles_changed_email(first_name, role_labels, config["site_name"])
        await EmailService._send_raw(config, to_email, subject, html, log_type="roles_changed")

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
        if not config:
            logger.debug("SMTP not configured — skipping password reset email to %s", to_email)
            return
        subject, html = password_reset_email(
            first_name, reset_url, expiry_minutes, config["site_name"]
        )
        await EmailService._send_raw(config, to_email, subject, html, log_type="password_reset")

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
        if not config:
            return
        subject, html = security_alert_email(
            first_name, event, ip_address, when, config["site_name"]
        )
        await EmailService._send_raw(config, to_email, subject, html, log_type=log_type)
