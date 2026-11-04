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


def test_numbers_stay_unique_after_index_rebuild(tmp_path: Path) -> None:
    service = SecondBrainService(tmp_path / "memory")
    try:
        first = service.create_memory(content="第一条记忆。", memory_type="fact", scope="global", status="active")
        second = service.create_memory(content="第二条记忆。", memory_type="fact", scope="global", status="active")
        root = tmp_path / "memory"
        # Force the file order to disagree with the number order: after a rebuild the
        # lower-numbered row is inserted last, so a "last rowid" lookup would reuse #000002.
        (root / first["file_path"]).rename(root / "memories" / "active" / "memory_zzz9.md")
        (root / second["file_path"]).rename(root / "memories" / "active" / "memory_aaa1.md")
        service.rebuild_index()
        third = service.create_memory(content="第三条记忆。", memory_type="fact", scope="global", status="active")
        numbers = [item["memory_number"] for item in service.db.search_memories("", statuses=("active",), limit=100)]
        assert len(numbers) == len(set(numbers))
        assert third["memory_number"] == "#000003"
    finally:
        service.close()


def _write_duplicate_number(service, tmp_path: Path, keep: dict, target: dict) -> None:
    from secondbrain_core.storage import read_record, write_record

    path = (tmp_path / "memory") / target["file_path"]
    metadata, body, _ = read_record(path)
    metadata["memory_number"] = keep["memory_number"]
    write_record(path, metadata, body)


def test_rebuild_repairs_duplicate_numbers_without_losing_memories(tmp_path: Path) -> None:
    service = SecondBrainService(tmp_path / "memory")
    try:
        first = service.create_memory(content="甲记忆。", memory_type="fact", scope="global", status="active")
        second = service.create_memory(content="乙记忆。", memory_type="fact", scope="global", status="active")
        _write_duplicate_number(service, tmp_path, first, second)

        report = service.rebuild_index()

        assert report["memories"] == 2, "重建不能静默丢记忆"
        assert report["repaired_numbers"] == 1
        assert report["errors"] == []
        assert service.db.duplicate_memory_numbers() == []
        rows = service.db.search_memories("", statuses=("active",), limit=100)
        numbers = [row["memory_number"] for row in rows]
        assert sorted(numbers) == ["#000001", "#000002"]
    finally:
        service.close()


def test_repair_memory_numbers_is_idempotent(tmp_path: Path) -> None:
    service = SecondBrainService(tmp_path / "memory")
    try:
        first = service.create_memory(content="甲记忆。", memory_type="fact", scope="global", status="active")
        second = service.create_memory(content="乙记忆。", memory_type="fact", scope="global", status="active")
        _write_duplicate_number(service, tmp_path, first, second)

        report = service.repair_memory_numbers()

        assert report["repaired_count"] == 1
        assert report["groups"] == 1
        assert report["memories"] == 2
        assert report["unique_index"] is True
        assert service.repair_memory_numbers()["repaired_count"] == 0
        third = service.create_memory(content="丙记忆。", memory_type="fact", scope="global", status="active")
        assert third["memory_number"] == "#000003"
    finally:
        service.close()
