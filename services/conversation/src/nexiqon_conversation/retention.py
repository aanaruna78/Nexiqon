"""Retention sweep: deletes conversations past ``retain_until`` (messages and feedback cascade).

Runs as a narrow, transaction-scoped privilege (``app.retention_sweep``) whose RLS policy only
exposes already-expired rows, so the sweep cannot read or touch live conversations.
"""

from __future__ import annotations

from sqlalchemy import delete, func

from nexiqon_conversation.models import Conversation
from nexiqon_core.db import TenantSessionFactory


async def sweep(db: TenantSessionFactory) -> int:
    async with db.scoped({"retention_sweep": "on"}) as s:
        result = await s.execute(delete(Conversation).where(Conversation.retain_until < func.now()))
    return int(result.rowcount or 0)  # type: ignore[attr-defined]
