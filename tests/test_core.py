from pathlib import Path

from secondbrain_core.service import SecondBrainService


def test_create_search_and_approve_memory(tmp_path: Path) -> None:
    service = SecondBrainService(tmp_path / "memory")
    try:
        agent = service.create_agent("Test Agent", agent_id="agent_test")
        project = service.create_project("SecondBrain", project_id="project_test")
        session = service.create_session(
            agent_id=agent["agent_id"],
            project_id=project["project_id"],
            title="Storage design",
            summary="Define the storage format.",
            session_id="session_test",
        )
        memory = service.create_memory(
            content="Markdown is the source of truth.",
            memory_type="decision",
            scope="project",
            project_id=project["project_id"],
            agent_id=agent["agent_id"],
            source_session_id=session["session_id"],
            tags=["storage"],
        )

        assert memory["status"] == "candidate"
        assert (tmp_path / "memory" / "memories" / "candidates" / f"{memory['memory_id']}.md").exists()
        assert service.search_memories("source of truth") == []
        assert len(service.search_memories("source of truth", statuses=("candidate",))) == 1

        approved = service.approve_memory(memory["memory_id"])
        assert approved["status"] == "active"
        results = service.search_memories("Markdown")
        assert len(results) == 1
        assert results[0]["memory_id"] == memory["memory_id"]
        assert (tmp_path / "memory" / "memories" / "active" / f"{memory['memory_id']}.md").exists()
    finally:
        service.close()


def test_rebuild_index_from_markdown(tmp_path: Path) -> None:
    root = tmp_path / "memory"
    service = SecondBrainService(root)
    agent = service.create_agent("Test Agent", agent_id="agent_test")
    memory = service.create_memory(
        content="Rebuild indexes from Markdown.",
        memory_type="instruction",
        scope="global",
        status="active",
        agent_id=agent["agent_id"],
    )
    service.close()
    (root / "index.sqlite3").unlink()

    service = SecondBrainService(root)
    try:
        assert service.search_memories("Rebuild") == []
        report = service.rebuild_index()
        assert report["memories"] == 1
        assert report["errors"] == []
        assert service.search_memories("Rebuild")[0]["memory_id"] == memory["memory_id"]
    finally:
        service.close()
