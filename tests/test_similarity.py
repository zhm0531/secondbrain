from pathlib import Path

from secondbrain_core.service import SecondBrainService


def test_unrelated_memories_are_not_flagged(tmp_path: Path) -> None:
    service = SecondBrainService(tmp_path / "memory")
    try:
        service.create_memory(content="主人的真名叫周恒茂，学号为3024244549", memory_type="fact", scope="global", status="active")
        service.create_memory(content="这台机器上 anaconda python 3.13 没有 python-docx", memory_type="fact", scope="global", status="active")
        report = service.audit_memories()
        assert report["conflicts"] == []
        assert report["duplicates"] == []
    finally:
        service.close()


def test_expanded_memory_counts_as_duplicate(tmp_path: Path) -> None:
    service = SecondBrainService(tmp_path / "memory")
    try:
        service.create_memory(
            content="图表仍需 anaconda 的 librosa/matplotlib，所以分工是 anaconda 画图。",
            memory_type="decision",
            scope="global",
            status="active",
        )
        service.create_memory(
            content="图表仍需 anaconda 的 librosa/matplotlib，所以分工是 anaconda 画图，bundled python 生成报告。",
            memory_type="decision",
            scope="global",
            status="active",
        )
        report = service.audit_memories()
        assert report["conflicts"] == []
        assert len(report["duplicates"]) == 1
        assert report["duplicates"][0]["count"] == 2
    finally:
        service.close()


def test_conflict_reports_kind_similarity_and_reason(tmp_path: Path) -> None:
    service = SecondBrainService(tmp_path / "memory")
    try:
        service.create_memory(content="Use SQLite for search.", memory_type="decision", scope="project", status="active")
        matches = service.find_conflicts(content="Use PostgreSQL for search.", scope="project")
        assert matches
        top = matches[0]
        assert top["kind"] == "conflict"
        assert 0.4 <= top["similarity"] <= 1.0
        assert top["similarity"] == top["overlap"]
        assert "可能互相矛盾" in top["reason"]
        assert "（项目）" in top["reason"]
        assert "决策类型" in top["reason"]
    finally:
        service.close()


def test_audit_record_trail_is_stripped(tmp_path: Path) -> None:
    service = SecondBrainService(tmp_path / "memory")
    try:
        nl = chr(10)
        raw = "正文内容。" + nl + nl + "## 审核记录" + nl + "- 2026-11-03 12:00：approved"
        assert service._normalized_content(raw) == "正文内容。"
    finally:
        service.close()
