import uuid

from nexiqon_core.events import InMemoryPublisher, OutboxEvent
from nexiqon_core.ids import uuid7


def test_uuid7_version_variant_and_order() -> None:
    ids = [uuid7() for _ in range(5000)]
    assert all(i.version == 7 for i in ids)
    assert all(i.variant == uuid.RFC_4122 for i in ids)
    assert ids == sorted(ids, key=lambda u: u.int)
    assert len(set(ids)) == len(ids)


async def test_cloudevent_shape() -> None:
    from datetime import UTC, datetime

    tenant = uuid.uuid4()
    e = OutboxEvent(
        id=uuid7(),
        tenant_id=tenant,
        type="nexiqon.ingestion.document.indexed",
        source="ingestion",
        subject="doc-1",
        actor_id="user-a",
        data={"chunks": 3},
        created_at=datetime.now(UTC),
    )
    ce = e.to_cloudevent()
    assert ce["specversion"] == "1.0"
    assert ce["nexiqontenantid"] == str(tenant)
    pub = InMemoryPublisher()
    await pub.publish(ce)
    assert pub.events[0]["subject"] == "doc-1"
