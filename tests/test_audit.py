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
