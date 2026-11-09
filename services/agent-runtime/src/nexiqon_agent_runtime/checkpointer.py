"""Tenant-scoped LangGraph checkpointer on our Postgres (AG-02).

LangGraph's own Postgres saver uses its own driver and tables without row-level security. This
saver implements the same contract (modelled on ``InMemorySaver``) on the service's RLS-forced
tables: each instance is bound to one tenant context, and every read and write runs in a session
for that tenant, so a thread id from another tenant simply does not exist.
"""

from __future__ import annotations

import random
from collections.abc import AsyncIterator, Sequence
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    WRITES_IDX_MAP,
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    get_checkpoint_id,
    get_checkpoint_metadata,
)
from sqlalchemy import delete, select, tuple_
from sqlalchemy.dialects.postgresql import insert

from nexiqon_agent_runtime.models import Checkpoint as CheckpointRow
from nexiqon_agent_runtime.models import CheckpointBlob, CheckpointWrite
from nexiqon_core.db import TenantSessionFactory
from nexiqon_core.tenancy import TenantContext


class TenantCheckpointer(BaseCheckpointSaver[str]):
    def __init__(self, db: TenantSessionFactory, ctx: TenantContext) -> None:
        super().__init__()
        self.db = db
        self.ctx = ctx

    # ------------------------------------------------------------------ helpers

    def _values(self, blobs: Sequence[CheckpointBlob]) -> dict[str, Any]:
        return {
            b.channel: self.serde.loads_typed((b.type, b.blob))
            for b in blobs
            if b.type != "empty" and b.blob is not None
        }

    async def _tuple(self, row: CheckpointRow) -> CheckpointTuple:
        ns, thread = row.checkpoint_ns, row.thread_id
        checkpoint: Checkpoint = self.serde.loads_typed((row.type, row.checkpoint))
        versions = checkpoint.get("channel_versions", {})
        async with self.db.session(self.ctx) as s:
            blobs = (
                await s.scalars(
                    select(CheckpointBlob).where(
                        CheckpointBlob.thread_id == thread,
                        CheckpointBlob.checkpoint_ns == ns,
                        tuple_(CheckpointBlob.channel, CheckpointBlob.version).in_(
                            [(k, str(v)) for k, v in versions.items()]
                        ),
                    )
                )
            ).all()
            writes = (
                await s.scalars(
                    select(CheckpointWrite)
                    .where(
                        CheckpointWrite.thread_id == thread,
                        CheckpointWrite.checkpoint_ns == ns,
                        CheckpointWrite.checkpoint_id == row.checkpoint_id,
                    )
                    .order_by(
                        CheckpointWrite.task_path, CheckpointWrite.task_id, CheckpointWrite.idx
                    )
                )
            ).all()
        current = list(blobs)
        return CheckpointTuple(
            config={
                "configurable": {
                    "thread_id": thread,
                    "checkpoint_ns": ns,
                    "checkpoint_id": row.checkpoint_id,
                }
            },
            checkpoint={**checkpoint, "channel_values": self._values(current)},
            metadata=self.serde.loads_typed((row.metadata_type, row.meta)),
            pending_writes=[
                (w.task_id, w.channel, self.serde.loads_typed((w.type, w.blob))) for w in writes
            ],
            parent_config=(
                {
                    "configurable": {
                        "thread_id": thread,
                        "checkpoint_ns": ns,
                        "checkpoint_id": row.parent_checkpoint_id,
                    }
                }
                if row.parent_checkpoint_id
                else None
            ),
        )

    # ------------------------------------------------------------------ saver contract

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        conf = config["configurable"]
        query = select(CheckpointRow).where(
            CheckpointRow.thread_id == conf["thread_id"],
            CheckpointRow.checkpoint_ns == conf.get("checkpoint_ns", ""),
        )
        if checkpoint_id := get_checkpoint_id(config):
            query = query.where(CheckpointRow.checkpoint_id == checkpoint_id)
        else:
            query = query.order_by(CheckpointRow.checkpoint_id.desc()).limit(1)
        async with self.db.session(self.ctx) as s:
            row = await s.scalar(query)
        return await self._tuple(row) if row is not None else None

    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        query = select(CheckpointRow).order_by(CheckpointRow.checkpoint_id.desc())
        if config is not None:
            conf = config["configurable"]
            query = query.where(CheckpointRow.thread_id == conf["thread_id"])
            if "checkpoint_ns" in conf:
                query = query.where(CheckpointRow.checkpoint_ns == conf["checkpoint_ns"])
            if checkpoint_id := get_checkpoint_id(config):
                query = query.where(CheckpointRow.checkpoint_id == checkpoint_id)
        if before is not None and (before_id := get_checkpoint_id(before)):
            query = query.where(CheckpointRow.checkpoint_id < before_id)
        async with self.db.session(self.ctx) as s:
            rows = (await s.scalars(query)).all()
        count = 0
        for row in rows:
            tup = await self._tuple(row)
            if filter and not all(tup.metadata.get(k) == v for k, v in filter.items()):
                continue
            yield tup
            count += 1
            if limit is not None and count >= limit:
                return

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        conf = config["configurable"]
        thread, ns = conf["thread_id"], conf.get("checkpoint_ns", "")
        copy = checkpoint.copy()
        values: dict[str, Any] = copy.pop("channel_values")  # type: ignore[misc]
        type_, payload = self.serde.dumps_typed(copy)
        meta_type, meta = self.serde.dumps_typed(get_checkpoint_metadata(config, metadata))
        tenant = self.ctx.tenant_id
        async with self.db.session(self.ctx) as s:
            for channel, version in new_versions.items():
                blob_type, blob = (
                    self.serde.dumps_typed(values[channel])
                    if channel in values
                    else ("empty", None)
                )
                await s.execute(
                    insert(CheckpointBlob)
                    .values(
                        tenant_id=tenant,
                        thread_id=thread,
                        checkpoint_ns=ns,
                        channel=channel,
                        version=str(version),
                        type=blob_type,
                        blob=blob,
                    )
                    .on_conflict_do_nothing(
                        index_elements=[
                            "tenant_id",
                            "thread_id",
                            "checkpoint_ns",
                            "channel",
                            "version",
                        ]
                    )
                )
            await s.execute(
                insert(CheckpointRow)
                .values(
                    tenant_id=tenant,
                    thread_id=thread,
                    checkpoint_ns=ns,
                    checkpoint_id=checkpoint["id"],
                    parent_checkpoint_id=conf.get("checkpoint_id"),
                    type=type_,
                    checkpoint=payload,
                    metadata_type=meta_type,
                    meta=meta,
                )
                .on_conflict_do_update(
                    index_elements=["tenant_id", "thread_id", "checkpoint_ns", "checkpoint_id"],
                    set_={
                        "type": type_,
                        "checkpoint": payload,
                        "metadata_type": meta_type,
                        "meta": meta,
                    },
                )
            )
        return {
            "configurable": {
                "thread_id": thread,
                "checkpoint_ns": ns,
                "checkpoint_id": checkpoint["id"],
            }
        }

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        conf = config["configurable"]
        thread, ns, checkpoint_id = (
            conf["thread_id"],
            conf.get("checkpoint_ns", ""),
            conf["checkpoint_id"],
        )
        async with self.db.session(self.ctx) as s:
            for i, (channel, value) in enumerate(writes):
                idx = WRITES_IDX_MAP.get(channel, i)
                type_, blob = self.serde.dumps_typed(value)
                stmt = insert(CheckpointWrite).values(
                    tenant_id=self.ctx.tenant_id,
                    thread_id=thread,
                    checkpoint_ns=ns,
                    checkpoint_id=checkpoint_id,
                    task_id=task_id,
                    task_path=task_path,
                    idx=idx,
                    channel=channel,
                    type=type_,
                    blob=blob,
                )
                keys = [
                    "tenant_id",
                    "thread_id",
                    "checkpoint_ns",
                    "checkpoint_id",
                    "task_id",
                    "idx",
                ]
                # Special writes (errors, interrupts: negative idx) are replaced; regular ones kept.
                if idx < 0:
                    stmt = stmt.on_conflict_do_update(
                        index_elements=keys, set_={"channel": channel, "type": type_, "blob": blob}
                    )
                else:
                    stmt = stmt.on_conflict_do_nothing(index_elements=keys)
                await s.execute(stmt)

    async def adelete_thread(self, thread_id: str) -> None:
        async with self.db.session(self.ctx) as s:
            for model in (CheckpointWrite, CheckpointBlob, CheckpointRow):
                await s.execute(delete(model).where(model.thread_id == thread_id))

    def get_next_version(self, current: str | None, channel: None) -> str:
        current_v = 0 if current is None else int(str(current).split(".")[0])
        return f"{current_v + 1:032}.{random.random():016}"  # noqa: S311 - ordering tiebreak, not security
