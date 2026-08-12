"""
HTML email templates for the SchedulePro platform.

Each template function returns a tuple of (subject, html_body).
All templates share a common base wrapper for consistent branding.
"""


def _base_wrapper(content: str, site_name: str = "SchedulePro") -> str:
    """Wrap email content in a consistent HTML layout."""
    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{site_name}</title>
</head>
<body style="margin:0;padding:0;background-color:#f3f4f6;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f3f4f6;padding:32px 16px;">
<tr><td align="center">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:580px;background-color:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.1);">
<!-- Header -->
<tr>
<td style="background-color:#7c3aed;padding:24px 32px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0">
<tr>
<td>
<h1 style="margin:0;color:#ffffff;font-size:20px;font-weight:700;">{site_name}</h1>
</td>
</tr>
</table>
</td>
</tr>
<!-- Body -->
<tr>
<td style="padding:32px;">
{content}
</td>
</tr>
<!-- Footer -->
<tr>
<td style="padding:20px 32px;background-color:#f9fafb;border-top:1px solid #e5e7eb;">
<p style="margin:0;color:#9ca3af;font-size:12px;text-align:center;">
This is an automated message from {site_name}. Please do not reply directly to this email.
</p>
</td>
</tr>
</table>
</td></tr>
</table>
</body>
</html>"""


def _button(url: str, label: str) -> str:
    """Render a CTA button."""
    return f"""\
<table role="presentation" cellpadding="0" cellspacing="0" style="margin:24px 0;">
<tr>
<td style="background-color:#7c3aed;border-radius:8px;padding:12px 28px;">
<a href="{url}" style="color:#ffffff;text-decoration:none;font-size:14px;font-weight:600;display:inline-block;">{label}</a>
</td>
</tr>
</table>"""


def _info_row(label: str, value: str) -> str:
    """Render a key-value info row."""
    return f"""\
<tr>
<td style="padding:6px 0;color:#6b7280;font-size:14px;width:140px;vertical-align:top;">{label}</td>
<td style="padding:6px 0;color:#111827;font-size:14px;font-weight:500;">{value}</td>
</tr>"""


# ── Account Lifecycle ────────────────────────────────────────────────


def tenant_welcome_email(
    first_name: str,
    org_name: str,
    login_url: str,
    trial_days: int,
    site_name: str = "SchedulePro",
) -> tuple[str, str]:
    content = f"""\
<h2 style="margin:0 0 16px;color:#111827;font-size:22px;font-weight:700;">Welcome to {site_name}!</h2>
<p style="margin:0 0 16px;color:#374151;font-size:14px;line-height:1.6;">
Hi {first_name},
</p>
<p style="margin:0 0 16px;color:#374151;font-size:14px;line-height:1.6;">
Thank you for registering <strong>{org_name}</strong> on {site_name}. Your organization has been created and you've been set up as the administrator.
</p>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f0fdf4;border:1px solid #bbf7d0;border-radius:8px;padding:16px;margin:16px 0;">
<tr><td>
<p style="margin:0;color:#166534;font-size:14px;">
Your free trial is active for <strong>{trial_days} days</strong>. Enjoy full access to all features during this period.
</p>
</td></tr>
</table>
<p style="margin:0 0 16px;color:#374151;font-size:14px;line-height:1.6;">
Here's what you can do next:
</p>
<ul style="margin:0 0 16px;padding-left:20px;color:#374151;font-size:14px;line-height:1.8;">
<li>Set up your organization structure</li>
<li>Invite team members</li>
<li>Configure schedules and leave policies</li>
</ul>
{_button(login_url, "Go to Dashboard")}"""
    subject = f"[{site_name}] Welcome! Your Organization is Ready"
    return subject, _base_wrapper(content, site_name)


def password_changed_email(
    first_name: str,
    site_name: str = "SchedulePro",
) -> tuple[str, str]:
    content = f"""\
<h2 style="margin:0 0 16px;color:#111827;font-size:22px;font-weight:700;">Password Changed</h2>
<p style="margin:0 0 16px;color:#374151;font-size:14px;line-height:1.6;">
Hi {first_name},
</p>
<p style="margin:0 0 16px;color:#374151;font-size:14px;line-height:1.6;">
Your password has been successfully changed. If you did not make this change, please contact your administrator immediately.
</p>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#fef3c7;border:1px solid #fde68a;border-radius:8px;padding:16px;margin:16px 0;">
<tr><td>
<p style="margin:0;color:#92400e;font-size:13px;">
If you did not request this change, your account may be compromised. Contact your system administrator right away.
</p>
</td></tr>
</table>"""
    subject = f"[{site_name}] Your Password Has Been Changed"
    return subject, _base_wrapper(content, site_name)


def two_factor_enabled_email(
    first_name: str,
    site_name: str = "SchedulePro",
) -> tuple[str, str]:
    content = f"""\
<h2 style="margin:0 0 16px;color:#111827;font-size:22px;font-weight:700;">Two-Factor Authentication Enabled</h2>
<p style="margin:0 0 16px;color:#374151;font-size:14px;line-height:1.6;">
Hi {first_name},
</p>
<p style="margin:0 0 16px;color:#374151;font-size:14px;line-height:1.6;">
Two-factor authentication (2FA) has been successfully enabled on your account. You will now be required to enter a verification code from your authenticator app each time you sign in.
</p>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f0fdf4;border:1px solid #bbf7d0;border-radius:8px;padding:16px;margin:16px 0;">
<tr><td>
<p style="margin:0;color:#166534;font-size:13px;">
Your account is now more secure. Make sure to keep your authenticator app and recovery codes in a safe place.
</p>
</td></tr>
</table>"""
    subject = f"[{site_name}] Two-Factor Authentication Enabled"
    return subject, _base_wrapper(content, site_name)


def account_deactivated_email(
    first_name: str,
    site_name: str = "SchedulePro",
) -> tuple[str, str]:
    content = f"""\
<h2 style="margin:0 0 16px;color:#111827;font-size:22px;font-weight:700;">Account Deactivated</h2>
<p style="margin:0 0 16px;color:#374151;font-size:14px;line-height:1.6;">
Hi {first_name},
</p>
<p style="margin:0 0 16px;color:#374151;font-size:14px;line-height:1.6;">
Your account on {site_name} has been deactivated by an administrator. You will no longer be able to sign in.
</p>
<p style="margin:0 0 16px;color:#374151;font-size:14px;line-height:1.6;">
If you believe this was done in error, please contact your organization's administrator.
</p>"""
    subject = f"[{site_name}] Your Account Has Been Deactivated"
    return subject, _base_wrapper(content, site_name)


# ── Leave Notifications ──────────────────────────────────────────────


def leave_request_email(
    approver_name: str,
    employee_name: str,
    leave_type: str,
    start_date: str,
    end_date: str,
    days: float,
    reason: str,
    site_name: str = "SchedulePro",
) -> tuple[str, str]:
    leave_type_display = leave_type.replace("_", " ").title()
    content = f"""\
<h2 style="margin:0 0 16px;color:#111827;font-size:22px;font-weight:700;">New Leave Request</h2>
<p style="margin:0 0 16px;color:#374151;font-size:14px;line-height:1.6;">
Hi {approver_name},
</p>
<p style="margin:0 0 16px;color:#374151;font-size:14px;line-height:1.6;">
<strong>{employee_name}</strong> has submitted a leave request that requires your review.
</p>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f9fafb;border-radius:8px;padding:16px;margin:16px 0;">
<tr><td>
<table role="presentation" cellpadding="0" cellspacing="0" width="100%">
{_info_row("Leave Type", leave_type_display)}
{_info_row("From", start_date)}
{_info_row("To", end_date)}
{_info_row("Days", str(days))}
{_info_row("Reason", reason)}
</table>
</td></tr>
</table>
<p style="margin:0;color:#374151;font-size:14px;line-height:1.6;">
Please sign in to review this request.
</p>"""
    subject = f"[{site_name}] Leave Request from {employee_name} - {leave_type_display}"
    return subject, _base_wrapper(content, site_name)


def leave_approved_email(
    employee_name: str,
    leave_type: str,
    start_date: str,
    end_date: str,
    reviewer_name: str,
    site_name: str = "SchedulePro",
) -> tuple[str, str]:
    leave_type_display = leave_type.replace("_", " ").title()
    content = f"""\
<h2 style="margin:0 0 16px;color:#111827;font-size:22px;font-weight:700;">Leave Request Approved</h2>
<p style="margin:0 0 16px;color:#374151;font-size:14px;line-height:1.6;">
Hi {employee_name},
</p>
<p style="margin:0 0 16px;color:#374151;font-size:14px;line-height:1.6;">
Your leave request has been <strong style="color:#059669;">approved</strong>.
</p>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f0fdf4;border:1px solid #bbf7d0;border-radius:8px;padding:16px;margin:16px 0;">
<tr><td>
<table role="presentation" cellpadding="0" cellspacing="0" width="100%">
{_info_row("Leave Type", leave_type_display)}
{_info_row("From", start_date)}
{_info_row("To", end_date)}
{_info_row("Approved By", reviewer_name)}
</table>
</td></tr>
</table>"""
    subject = f"[{site_name}] Your Leave Request Has Been Approved"
    return subject, _base_wrapper(content, site_name)


def leave_rejected_email(
    employee_name: str,
    leave_type: str,
    start_date: str,
    end_date: str,
    reviewer_name: str,
    reviewer_notes: str,
    site_name: str = "SchedulePro",
) -> tuple[str, str]:
    leave_type_display = leave_type.replace("_", " ").title()
    notes_html = ""
    if reviewer_notes:
        notes_html = f'{_info_row("Reviewer Notes", reviewer_notes)}'
    content = f"""\
<h2 style="margin:0 0 16px;color:#111827;font-size:22px;font-weight:700;">Leave Request Rejected</h2>
<p style="margin:0 0 16px;color:#374151;font-size:14px;line-height:1.6;">
Hi {employee_name},
</p>
<p style="margin:0 0 16px;color:#374151;font-size:14px;line-height:1.6;">
Unfortunately, your leave request has been <strong style="color:#dc2626;">rejected</strong>.
</p>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#fef2f2;border:1px solid #fecaca;border-radius:8px;padding:16px;margin:16px 0;">
<tr><td>
<table role="presentation" cellpadding="0" cellspacing="0" width="100%">
{_info_row("Leave Type", leave_type_display)}
{_info_row("From", start_date)}
{_info_row("To", end_date)}
{_info_row("Reviewed By", reviewer_name)}
{notes_html}
</table>
</td></tr>
</table>
<p style="margin:0;color:#374151;font-size:14px;line-height:1.6;">
Please contact your manager if you have questions.
</p>"""
    subject = f"[{site_name}] Your Leave Request Has Been Rejected"
    return subject, _base_wrapper(content, site_name)


# ── Schedule Notifications ───────────────────────────────────────────


def schedule_change_email(
    employee_name: str,
    changes: str,
    site_name: str = "SchedulePro",
) -> tuple[str, str]:
    content = f"""\
<h2 style="margin:0 0 16px;color:#111827;font-size:22px;font-weight:700;">Schedule Update</h2>
<p style="margin:0 0 16px;color:#374151;font-size:14px;line-height:1.6;">
Hi {employee_name},
</p>
<p style="margin:0 0 16px;color:#374151;font-size:14px;line-height:1.6;">
Your schedule has been updated. Here are the details:
</p>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#eff6ff;border:1px solid #bfdbfe;border-radius:8px;padding:16px;margin:16px 0;">
<tr><td>
<p style="margin:0;color:#1e40af;font-size:14px;line-height:1.6;white-space:pre-line;">{changes}</p>
</td></tr>
</table>
<p style="margin:0;color:#374151;font-size:14px;line-height:1.6;">
Please sign in to view your full schedule.
</p>"""
    subject = f"[{site_name}] Your Schedule Has Been Updated"
    return subject, _base_wrapper(content, site_name)


def invite_email(
    first_name: str,
    tenant_name: str,
    activation_url: str,
    site_name: str = "SchedulePro",
) -> tuple[str, str]:
    content = f"""\
<h2 style="margin:0 0 16px;color:#111827;font-size:22px;font-weight:700;">You're Invited!</h2>
<p style="margin:0 0 16px;color:#374151;font-size:14px;line-height:1.6;">
Hi {first_name},
</p>
<p style="margin:0 0 16px;color:#374151;font-size:14px;line-height:1.6;">
You've been invited to join <strong>{tenant_name}</strong> on {site_name}. Click the button below to set your password and activate your account.
</p>
{_button(activation_url, "Activate Your Account")}
<p style="margin:0 0 16px;color:#9ca3af;font-size:12px;">
If the button doesn't work, copy and paste this URL into your browser: {activation_url}
</p>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#fef3c7;border:1px solid #fde68a;border-radius:8px;padding:16px;margin:16px 0;">
<tr><td>
<p style="margin:0;color:#92400e;font-size:13px;">
This invitation link will expire in 7 days. If it has expired, ask your administrator to resend the invite.
</p>
</td></tr>
</table>"""
    subject = f"[{site_name}] You've Been Invited to {tenant_name}"
    return subject, _base_wrapper(content, site_name)


def account_activated_email(
    first_name: str,
    login_url: str,
    site_name: str = "SchedulePro",
) -> tuple[str, str]:
    content = f"""\
<h2 style="margin:0 0 16px;color:#111827;font-size:22px;font-weight:700;">Account Activated!</h2>
<p style="margin:0 0 16px;color:#374151;font-size:14px;line-height:1.6;">
Hi {first_name},
</p>
<p style="margin:0 0 16px;color:#374151;font-size:14px;line-height:1.6;">
Your account has been successfully activated. You can now sign in with your email and the password you just set.
</p>
{_button(login_url, "Sign In to Your Account")}
<p style="margin:0;color:#9ca3af;font-size:12px;">
If the button doesn't work, copy and paste this URL into your browser: {login_url}
</p>"""
    subject = f"[{site_name}] Your Account Has Been Activated"
    return subject, _base_wrapper(content, site_name)


def scheduled_export_email(
    config_name: str,
    schedule_type: str,
    row_count: int = 0,
    site_name: str = "SchedulePro",
) -> tuple:
    """Email notification for a scheduled data export with CSV attachment."""
    freq_label = {"daily": "Daily", "weekly": "Weekly", "monthly": "Monthly"}.get(
        schedule_type, schedule_type.title()
    )
    content = f"""\
<h2 style="margin:0 0 16px;color:#111827;font-size:18px;font-weight:700;">Scheduled Export Ready</h2>
<p style="margin:0 0 12px;color:#374151;font-size:14px;line-height:1.6;">
Your <strong>{freq_label}</strong> scheduled export <strong>&ldquo;{config_name}&rdquo;</strong> has been generated successfully.
</p>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f3f4f6;border-radius:8px;padding:16px;margin:16px 0;">
<tr><td>
<p style="margin:0;color:#374151;font-size:14px;">
<strong>Export:</strong> {config_name}<br>
<strong>Frequency:</strong> {freq_label}<br>
<strong>Rows:</strong> {row_count:,}
</p>
</td></tr>
</table>
<p style="margin:0;color:#374151;font-size:14px;line-height:1.6;">
The CSV file is attached to this email. You can open it in any spreadsheet application.
</p>"""
    subject = f"[{site_name}] Scheduled Export: {config_name}"
    return subject, _base_wrapper(content, site_name)
