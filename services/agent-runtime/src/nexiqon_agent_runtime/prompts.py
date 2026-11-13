"""Prompt templates from the Domain Pack (``{{variable}}`` placeholders, per locale) and the few
fixed phrases the runtime itself says."""

from __future__ import annotations

import re
from typing import Any

VAR = re.compile(r"\{\{\s*(\w+)\s*\}\}")

FIXED: dict[str, dict[str, str]] = {
    "declined": {
        "en": "Okay, I haven't done that. Is there anything else I can help with?",
        "ar": "حسنًا، لم أقم بذلك. هل هناك شيء آخر يمكنني المساعدة فيه؟",
        "es": "De acuerdo, no lo he hecho. ¿Puedo ayudarte con algo más?",
    },
    "handoff": {
        "en": "I'm passing this to a person on our team, with a summary so you don't have to repeat yourself.",
        "ar": "سأحيل هذا إلى أحد أعضاء فريقنا مع ملخص حتى لا تضطر إلى التكرار.",
        "es": "Paso esto a una persona de nuestro equipo, con un resumen para que no tengas que repetirte.",
    },
    "clarify": {
        "en": "Could you tell me a little more about what you need?",
        "ar": "هل يمكنك إخباري بالمزيد عما تحتاج إليه؟",
        "es": "¿Podrías contarme un poco más sobre lo que necesitas?",
    },
    "approve": {
        "en": "Should I go ahead with: {action}?",
        "ar": "هل أتابع: {action}؟",
        "es": "¿Procedo con: {action}?",
    },
    "blocked": {
        "en": "I can't help with that topic here. Is there something else I can help with?",
        "ar": "لا يمكنني المساعدة في هذا الموضوع هنا. هل هناك شيء آخر يمكنني المساعدة فيه؟",
        "es": "No puedo ayudar con ese tema aquí. ¿Hay algo más en lo que pueda ayudarte?",
    },
    "withheld": {
        "en": "I can't share that answer. Please rephrase your question or ask to talk to a person.",
        "ar": "لا يمكنني مشاركة هذه الإجابة. أعد صياغة سؤالك أو اطلب التحدث إلى شخص.",
        "es": "No puedo compartir esa respuesta. Reformula tu pregunta o pide hablar con una persona.",
    },
    "handoff_confirm": {
        "en": 'I can pass this to our team with this summary: "{summary}" Shall I send it?',
        "ar": 'يمكنني إحالة هذا إلى فريقنا مع هذا الملخص: "{summary}" هل أرسله؟',
        "es": 'Puedo pasar esto a nuestro equipo con este resumen: "{summary}" ¿Lo envío?',
    },
    "unavailable": {
        "en": "I can't do that right now. Please try again later or ask to talk to a person.",
        "ar": "لا يمكنني القيام بذلك الآن. حاول لاحقًا أو اطلب التحدث إلى شخص.",
        "es": "No puedo hacerlo ahora. Inténtalo más tarde o pide hablar con una persona.",
    },
}


def fixed(key: str, locale: str, **values: str) -> str:
    texts = FIXED[key]
    return texts.get(locale, texts["en"]).format(**values)


def pick_locale(text: Any, locale: str) -> str:
    """A pack string may be plain or per-locale ({"en": ..., "ar": ...})."""
    if isinstance(text, dict):
        value = text.get(locale) or text.get("en") or next(iter(text.values()), "")
        return str(value)
    return str(text or "")


def render(prompt: dict[str, Any] | None, locale: str, variables: dict[str, str]) -> str:
    if not prompt:
        return ""
    template = pick_locale(prompt.get("template"), locale)
    return VAR.sub(lambda m: variables.get(m.group(1), ""), template)
