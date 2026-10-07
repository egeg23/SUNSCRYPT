"""Письма. Сначала — в outbox_emails, затем отправка по SMTP, если он
настроен. В логи не пишем ни адреса, ни текст: в письмах ссылки-токены."""

import asyncio
import logging
import smtplib
from datetime import UTC, datetime
from email.message import EmailMessage

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import OutboxEmail

log = logging.getLogger(__name__)


def _send_smtp(to: str, subject: str, body: str) -> None:
    s = get_settings()
    msg = EmailMessage()
    msg["From"] = s.smtp_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    cls = smtplib.SMTP_SSL if s.smtp_port == 465 else smtplib.SMTP
    with cls(s.smtp_host, s.smtp_port, timeout=20) as smtp:
        if cls is smtplib.SMTP:
            smtp.starttls()
        if s.smtp_user and s.smtp_password:
            smtp.login(s.smtp_user, s.smtp_password.get_secret_value())
        smtp.send_message(msg)


async def send(session: AsyncSession, to: str, subject: str, body: str) -> None:
    mail = OutboxEmail(to=to, subject=subject, body=body)
    session.add(mail)
    await session.flush()
    if not get_settings().smtp_host:
        log.info("письмо #%s отложено: SMTP не настроен", mail.id)
        return
    try:
        await asyncio.to_thread(_send_smtp, to, subject, body)
        mail.sent_at = datetime.now(UTC)
        mail.body = ""  # ссылки из писем (сброс пароля) в базе и копиях не нужны
    except Exception as e:
        mail.error = type(e).__name__
        log.warning("письмо #%s не отправлено: %s", mail.id, type(e).__name__)
