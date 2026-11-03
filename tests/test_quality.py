from datetime import datetime, timedelta, timezone
from pathlib import Path

from secondbrain_core.service import SecondBrainService


def test_expiry_history_duplicates_and_conflicts(tmp_path: Path) -> None:
    service = SecondBrainService(tmp_path / "memory")
    try:
        agent = service.create_agent("Quality Agent", agent_id="agent_quality")
        expired_at = (datetime.now(timezone.utc) - timedelta(minutes=1)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        first = service.create_memory(
            content="Use Markdown for durable memory storage.", memory_type="decision", scope="project",
            status="active", agent_id=agent["agent_id"],
        )
        expiring = service.create_memory(
            content="Temporary memory.", memory_type="context", scope="project",
            status="active", agent_id=agent["agent_id"], expires_at=expired_at,
        )
        duplicate = service.create_memory(
            content="Use Markdown for durable memory storage.", memory_type="decision", scope="project",
            agent_id=agent["agent_id"],
        )
        service.create_memory(
            content="Use SQLite for durable memory storage.", memory_type="decision", scope="project",
            status="active", agent_id=agent["agent_id"],
        )
        assert service.find_similar_memories(first["content"], scope="project")
        assert service.find_conflicts(content="Use SQLite for durable memory storage.", scope="project")
        assert service.expire_memories() == [expiring["memory_id"]]
        assert service.search_memories("Temporary", statuses=("active",)) == []
        assert len(service.memory_history(duplicate["memory_id"])) >= 1
    finally:
        service.close()
