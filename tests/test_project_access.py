from pathlib import Path

from secondbrain_core.service import SecondBrainService


def test_project_access_controls_project_memory(tmp_path: Path) -> None:
    service = SecondBrainService(tmp_path / "memory")
    try:
        owner = service.create_agent("Codex", agent_id="agent_codex")
        other = service.create_agent("DeepSeek", agent_id="agent_deepseek")
        project = service.create_project("Shared", project_id="project_shared")
        memory = service.create_memory(content="Shared project decision", memory_type="decision", scope="project", status="active", project_id=project["project_id"], agent_id=owner["agent_id"])
        assert service.can_access_memory(memory, agent_id=other["agent_id"], project_id=project["project_id"]) is False
        service.grant_project_access(other["agent_id"], project["project_id"])
        assert service.can_access_memory(memory, agent_id=other["agent_id"], project_id=project["project_id"]) is True
        service.revoke_project_access(other["agent_id"], project["project_id"])
        assert service.can_access_memory(memory, agent_id=other["agent_id"], project_id=project["project_id"]) is False
    finally:
        service.close()
