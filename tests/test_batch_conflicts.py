from pathlib import Path

from secondbrain_core.service import SecondBrainService


def test_batch_conflict_modes(tmp_path: Path) -> None:
    service = SecondBrainService(tmp_path / "memory")
    try:
        agent = service.create_agent("Codex", agent_id="agent_codex")
        for text in ("Project uses SQLite.", "Project uses PostgreSQL."):
            service.create_memory(content=text, memory_type="decision", scope="project", status="active", agent_id=agent["agent_id"])
        candidate = service.propose_memory(content="Project uses DuckDB.", memory_type="decision", scope="project", agent_id=agent["agent_id"])
        queue = service.review_conflicts()
        assert queue and queue[0]["candidate"]["memory_id"] == candidate["memory"]["memory_id"]
        results = service.resolve_all_conflicts("reject")
        assert results[0]["result"]["status"] == "rejected"
    finally:
        service.close()
