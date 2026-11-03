from pathlib import Path

from secondbrain_core.service import SecondBrainService


def test_search_marks_conflicts_and_audit_reports_pollution(tmp_path: Path) -> None:
    service = SecondBrainService(tmp_path / "memory")
    try:
        service.create_memory(content="Use SQLite for search.", memory_type="decision", scope="project", status="active")
        service.create_memory(content="Use PostgreSQL for search.", memory_type="decision", scope="project", status="active")
        results = service.search_memories("search", statuses=("active",))
        assert all(item["has_conflicts"] for item in results)
        report = service.audit_memories()
        assert report["conflicts"]
        assert report["pollution"]
    finally:
        service.close()


def test_audit_reports_exact_duplicate_groups_with_numbers(tmp_path: Path) -> None:
    service = SecondBrainService(tmp_path / "memory")
    try:
        first = service.create_memory(content="Keep Markdown as the source of truth.", memory_type="decision", scope="global", status="active")
        second = service.create_memory(content="  Keep   Markdown as the source of truth.  ", memory_type="decision", scope="global", status="active")
        report = service.audit_memories()
        assert len(report["duplicates"]) == 1
        group = report["duplicates"][0]
        assert group["count"] == 2
        assert set(group["memory_ids"]) == {first["memory_id"], second["memory_id"]}
        assert set(group["memory_numbers"]) == {first["memory_number"], second["memory_number"]}
    finally:
        service.close()
