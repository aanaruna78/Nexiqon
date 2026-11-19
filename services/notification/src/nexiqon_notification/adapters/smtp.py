"""SMTP adapter (standard library, run in a worker thread so the event loop never blocks)."""

from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage
from email.utils import make_msgid

from nexiqon_notification.mail import Email
from nexiqon_notification.settings import EmailSettings


class SmtpSender:
    def __init__(self, settings: EmailSettings) -> None:
        self.s = settings

    def _send(self, email: Email) -> None:
        msg = EmailMessage()
        msg["From"] = self.s.sender
        msg["To"] = email.to
        msg["Subject"] = email.subject
        msg["Message-ID"] = make_msgid(domain="nexiqon")
        if email.reply_to:
            msg["Reply-To"] = email.reply_to
        msg.set_content(email.text)
        with smtplib.SMTP(self.s.host, self.s.port, timeout=self.s.timeout_seconds) as smtp:
            if self.s.starttls:
                smtp.starttls()
            if self.s.username and self.s.password:
                smtp.login(self.s.username, self.s.password.get_secret_value())
            smtp.send_message(msg)

    async def send(self, email: Email) -> None:
        await asyncio.to_thread(self._send, email)

    async def aclose(self) -> None:
        return None
