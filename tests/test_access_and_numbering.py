from pathlib import Path

from secondbrain_core.service import SecondBrainService


def test_numbering_and_scope_confirmation(tmp_path: Path) -> None:
    service = SecondBrainService(tmp_path / "memory")
    try:
        service.create_agent("Codex", agent_id="agent_codex")
        service.create_agent("DeepSeek", agent_id="agent_deepseek")
        private = service.create_memory(content="Private note", memory_type="context", scope="agent", status="active", agent_id="agent_codex")
        assert private["memory_number"] == "#000001"
        blocked = service.get_memory_for_context(private["memory_id"], agent_id="agent_deepseek")
        assert blocked["requires_confirmation"] is True
        allowed = service.get_memory_for_context(private["memory_number"], agent_id="agent_codex")
        assert allowed["memory_id"] == private["memory_id"]
    finally:
        service.close()
