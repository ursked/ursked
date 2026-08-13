"""SMTP connection helpers shared by self-host and the operator console.

Deliberately neutral: takes a SiteSettings row and does the low-level SMTP
handshake / test-send. Kept out of any operator-console module so the Community
Edition can reuse it (the export never sees console-only code).
"""
import asyncio
import smtplib
from email.mime.text import MIMEText

from app.models.site_settings import SiteSettings


def _connect(settings: SiteSettings, timeout: int = 10) -> smtplib.SMTP:
    """Open an authenticated SMTP connection from a SiteSettings row."""
    if settings.smtp_use_ssl:
        server = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=timeout)
    else:
        server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=timeout)
        if settings.smtp_use_tls:
            server.starttls()
    if settings.smtp_username and settings.smtp_password:
        server.login(settings.smtp_username, settings.smtp_password)
    return server


async def test_connection(settings: SiteSettings) -> dict:
    """Open (and immediately close) an SMTP connection. Returns {success, message}."""
    if not settings.smtp_active or not settings.smtp_host:
        return {"success": False, "message": "SMTP is not configured or not active"}

    def _test() -> bool:
        server = _connect(settings)
        server.quit()
        return True

    try:
        await asyncio.to_thread(_test)
        return {"success": True, "message": "SMTP connection successful"}
    except Exception as e:  # noqa: BLE001 — surface the SMTP error to the admin
        return {"success": False, "message": f"SMTP connection failed: {e}"}


async def send_test_email(settings: SiteSettings, recipient: str) -> dict:
    """Send a fixed plain-text test email. Returns {success, message}."""
    if not settings.smtp_active or not settings.smtp_host:
        return {"success": False, "message": "SMTP is not configured or not active"}

    site_name = settings.site_name or "ursked"
    from_email = settings.smtp_from_email or settings.smtp_username

    def _send() -> None:
        msg = MIMEText(
            f"This is a test email from {site_name}.\n\n"
            f"If you received this email, your SMTP configuration is working correctly.",
            "plain",
            "utf-8",
        )
        msg["Subject"] = f"[{site_name}] SMTP Test Email"
        msg["From"] = f"{settings.smtp_from_name or site_name} <{from_email}>"
        msg["To"] = recipient
        server = _connect(settings)
        server.sendmail(from_email, [recipient], msg.as_string())
        server.quit()

    try:
        await asyncio.to_thread(_send)
        return {"success": True, "message": f"Test email sent to {recipient}"}
    except Exception as e:  # noqa: BLE001
        return {"success": False, "message": f"Failed to send test email: {e}"}
