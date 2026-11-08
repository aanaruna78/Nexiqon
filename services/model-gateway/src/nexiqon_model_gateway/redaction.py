"""Reversible PII redaction before text leaves for a cloud provider.

Emails, phone numbers and payment-card numbers (Luhn-checked) become placeholders like
``[EMAIL_1]``. The same value always maps to the same placeholder within a request, so the model
can still reason about "the same person". Placeholders in the model's answer are restored.
"""

from __future__ import annotations

import re
from typing import Any

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
CARD = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")
PHONE = re.compile(r"(?<![\w+])\+?\(?\d[\d ().-]{6,}\d(?!\w)")
PLACEHOLDER = re.compile(r"\[(EMAIL|CARD|PHONE)_\d+\]")


def _luhn(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n = n * 2 - 9 if n > 4 else n * 2
        total += n
    return total % 10 == 0


def _is_phone(text: str) -> bool:
    digits = re.sub(r"\D", "", text)
    if text.startswith("+"):
        return 8 <= len(digits) <= 15
    # Without a country code require 10+ digits so dates and IDs like 2026-11-08 are left alone.
    return 10 <= len(digits) <= 15


class Redactor:
    def __init__(self) -> None:
        self._forward: dict[str, str] = {}
        self._reverse: dict[str, str] = {}
        self._counts: dict[str, int] = {}

    @property
    def mapping(self) -> dict[str, str]:
        """placeholder -> original (kept in memory only; never logged or stored)."""
        return dict(self._reverse)

    def _token(self, kind: str, value: str) -> str:
        existing = self._forward.get(value)
        if existing is not None:
            return existing
        self._counts[kind] = self._counts.get(kind, 0) + 1
        token = f"[{kind}_{self._counts[kind]}]"
        self._forward[value] = token
        self._reverse[token] = value
        return token

    def redact(self, text: str) -> str:
        text = EMAIL.sub(lambda m: self._token("EMAIL", m.group()), text)

        def card(m: re.Match[str]) -> str:
            digits = re.sub(r"\D", "", m.group())
            return self._token("CARD", m.group()) if _luhn(digits) else m.group()

        text = CARD.sub(card, text)

        def phone(m: re.Match[str]) -> str:
            return self._token("PHONE", m.group()) if _is_phone(m.group()) else m.group()

        return PHONE.sub(phone, text)

    def redact_value(self, value: Any) -> Any:
        """Redact strings inside JSON-like values (tool-call arguments)."""
        if isinstance(value, str):
            return self.redact(value)
        if isinstance(value, list):
            return [self.redact_value(v) for v in value]
        if isinstance(value, dict):
            return {k: self.redact_value(v) for k, v in value.items()}
        return value

    def restore(self, text: str) -> str:
        return PLACEHOLDER.sub(lambda m: self._reverse.get(m.group(), m.group()), text)

    def restore_value(self, value: Any) -> Any:
        """Restore placeholders inside JSON-like values (tool-call arguments)."""
        if isinstance(value, str):
            return self.restore(value)
        if isinstance(value, list):
            return [self.restore_value(v) for v in value]
        if isinstance(value, dict):
            return {k: self.restore_value(v) for k, v in value.items()}
        return value
