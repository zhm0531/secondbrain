from pathlib import Path

from secondbrain_core.service import SecondBrainService


def test_replace_memory_creates_new_version(tmp_path: Path) -> None:
    service = SecondBrainService(tmp_path / "memory")
    try:
        agent = service.create_agent("Codex", agent_id="agent_codex")
        old = service.create_memory(
            content="The project uses SQLite.", memory_type="decision", scope="project",
            status="active", agent_id=agent["agent_id"],
        )
        result = service.replace_memory(
            old["memory_id"], content="The project uses PostgreSQL.", agent_id=agent["agent_id"]
        )
        assert result["new_memory"]["status"] == "active"
        assert result["new_memory"]["supersedes_memory_id"] == old["memory_id"]
        assert result["superseded_memory"]["status"] == "superseded"
        assert service.search_memories("SQLite") == []
        assert service.search_memories("PostgreSQL")[0]["status"] == "active"
    finally:
        service.close()
