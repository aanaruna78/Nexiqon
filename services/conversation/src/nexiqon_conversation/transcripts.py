"""Conversation transcripts sent by email (W-03): plain text, in the conversation's language.

Only what the person saw: their questions, the answers and the sources cited. No run ids,
scores, tool arguments or anything else from behind the answer.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

LABELS: dict[str, dict[str, str]] = {
    "en": {
        "subject": "Your conversation with {name}",
        "you": "You",
        "sources": "Sources",
        "intro": "Here is a copy of your conversation with {name}.",
        "footer": "You asked for this copy. Replies to this email are not monitored.",
    },
    "es": {
        "subject": "Tu conversación con {name}",
        "you": "Tú",
        "sources": "Fuentes",
        "intro": "Aquí tienes una copia de tu conversación con {name}.",
        "footer": "Pediste esta copia. Las respuestas a este correo no se leen.",
    },
    "fr": {
        "subject": "Votre conversation avec {name}",
        "you": "Vous",
        "sources": "Sources",
        "intro": "Voici une copie de votre conversation avec {name}.",
        "footer": "Vous avez demandé cette copie. Les réponses à cet e-mail ne sont pas lues.",
    },
    "de": {
        "subject": "Ihre Unterhaltung mit {name}",
        "you": "Sie",
        "sources": "Quellen",
        "intro": "Hier ist eine Kopie Ihrer Unterhaltung mit {name}.",
        "footer": "Sie haben diese Kopie angefordert. Antworten auf diese E-Mail werden nicht gelesen.",
    },
    "ar": {
        "subject": "محادثتك مع {name}",
        "you": "أنت",
        "sources": "المصادر",
        "intro": "إليك نسخة من محادثتك مع {name}.",
        "footer": "طلبت هذه النسخة. لا تتم متابعة الردود على هذه الرسالة.",
    },
}


@dataclass(frozen=True)
class Line:
    role: str
    content: str
    contract: dict[str, Any]
    at: datetime


def render(name: str, locale: str, lines: Sequence[Line]) -> tuple[str, str]:
    """(subject, body) for a conversation with ``name`` (the assistant's display name)."""
    t = LABELS.get(locale[:2], LABELS["en"])
    out = [t["intro"].format(name=name), ""]
    for line in lines:
        who = t["you"] if line.role == "user" else name
        out.append(f"{who} ({line.at:%Y-%m-%d %H:%M} UTC):")
        out.append(line.content.strip())
        citations = (line.contract or {}).get("citations") or []
        if line.role == "assistant" and citations:
            out.append(f"{t['sources']}:")
            for c in citations:
                uri = c.get("source_uri") or ""
                link = f" <{uri}>" if uri.startswith(("http://", "https://")) else ""
                out.append(f"  [{c.get('marker')}] {c.get('citation')}{link}")
        out.append("")
    out += ["--", t["footer"]]
    return t["subject"].format(name=name)[:200], "\n".join(out)
