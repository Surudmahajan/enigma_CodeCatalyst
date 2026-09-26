"""Outbound email. ``console`` logs a redacted notice (development); ``smtp`` sends for real."""

import logging
import smtplib
from email.message import EmailMessage

from app.core.config import get_settings

logger = logging.getLogger("symbio.email")


def send_email(to: str, subject: str, body: str) -> None:
    settings = get_settings()
    if settings.email_provider == "smtp" and settings.smtp_host:
        message = EmailMessage()
        message["From"] = settings.email_from
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
            smtp.starttls()
            if settings.smtp_username:
                smtp.login(settings.smtp_username, settings.smtp_password or "")
            smtp.send_message(message)
        return
    # Development: the body contains single-use links, so only print it outside production.
    if settings.app_env == "production":
        logger.warning("Email provider not configured; email to recipient dropped", extra={"event": "email_dropped"})
    else:
        logger.info("DEV EMAIL to=%s subject=%s\n%s", to, subject, body, extra={"event": "email_console"})
