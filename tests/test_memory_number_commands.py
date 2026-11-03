from pathlib import Path

from secondbrain_core.service import SecondBrainService


def test_memory_number_can_drive_lifecycle_actions(tmp_path: Path) -> None:
    service = SecondBrainService(tmp_path / "memory")
    try:
        memory = service.create_memory(content="Numbered memory", memory_type="fact", scope="global", status="candidate")
        assert service.get_memory(memory["memory_number"])["memory_id"] == memory["memory_id"]
        approved = service.approve_memory(memory["memory_number"])
        assert approved["status"] == "active"
        archived = service.archive_memory(memory["memory_number"])
        assert archived["status"] == "archived"
    finally:
        service.close()
