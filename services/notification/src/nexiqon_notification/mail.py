"""Email port. Adapters: SMTP (``adapters/smtp.py``) and an in-memory outbox for tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class Email:
    to: str
    subject: str
    text: str
    reply_to: str | None = None


class EmailSender(Protocol):
    async def send(self, email: Email) -> None: ...

    async def aclose(self) -> None: ...


@dataclass
class MemorySender:
    sent: list[Email] = field(default_factory=list)
    fail: bool = False

    async def send(self, email: Email) -> None:
        if self.fail:
            raise OSError("relay refused the message")
        self.sent.append(email)

    async def aclose(self) -> None:
        return None
