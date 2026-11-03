from pathlib import Path

from secondbrain_core.service import SecondBrainService


def test_propose_reports_conflict_without_replacing(tmp_path: Path) -> None:
    service = SecondBrainService(tmp_path / "memory")
    try:
        agent = service.create_agent("Codex", agent_id="agent_codex")
        old = service.create_memory(
            content="The project uses SQLite.", memory_type="decision", scope="project",
            status="active", agent_id=agent["agent_id"],
        )
        proposal = service.propose_memory(
            content="The project uses PostgreSQL.", memory_type="decision", scope="project",
            agent_id=agent["agent_id"],
        )
        assert proposal["requires_confirmation"] is True
        assert proposal["conflicts"][0]["memory_id"] == old["memory_id"]
        assert service.get_memory(old["memory_id"])["status"] == "active"
        assert proposal["memory"]["status"] == "candidate"
    finally:
        service.close()
