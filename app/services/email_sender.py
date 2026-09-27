"""
Sends outreach emails via SMTP and returns the Message-ID used, so a later
inbound reply (matched by In-Reply-To/References headers) can be tied back
to the exact OutreachEmail row that triggered it.
"""
import smtplib
from email.message import EmailMessage
from email.utils import make_msgid
from typing import Optional

from app.config import settings


def is_smtp_configured() -> bool:
    return bool(settings.smtp_host and settings.smtp_username and settings.smtp_password and settings.smtp_from_email)


def send_email(to_email: str, subject: str, body: str) -> tuple[bool, str, Optional[str]]:
    """Returns (success, message, message_id)."""
    if not is_smtp_configured():
        return False, "SMTP is not configured (set SMTP_HOST/SMTP_USERNAME/SMTP_PASSWORD/SMTP_FROM_EMAIL in .env)", None

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"{settings.smtp_from_name} <{settings.smtp_from_email}>"
    msg["To"] = to_email
    message_id = make_msgid()
    msg["Message-ID"] = message_id
    msg.set_content(body)

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as server:
            if settings.smtp_use_tls:
                server.starttls()
            server.login(settings.smtp_username, settings.smtp_password)
            server.send_message(msg)
        return True, "Sent successfully.", message_id
    except (smtplib.SMTPException, OSError) as exc:
        return False, f"SMTP send failed: {exc}", None
