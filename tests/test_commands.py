from pathlib import Path

import pytest

from secondbrain_core.service import MemoryCommandError, SecondBrainService


def make_service(tmp_path: Path) -> SecondBrainService:
    return SecondBrainService(tmp_path / "memory")


def test_add_memory_creates_active_memory(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    try:
        result = service.add_memory(content="部署走内网镜像。", memory_type="decision")
        assert result["status"] == "created"
        memory = result["memory"]
        assert memory["status"] == "active"
        assert memory["scope"] == "global"
        assert service.get_memory(memory["memory_id"])["content"].startswith("部署走内网镜像")
    finally:
        service.close()


def test_add_memory_warns_on_duplicate_before_writing(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    try:
        assert service.add_memory(content="部署走内网镜像。", memory_type="decision")["status"] == "created"
        before = len(service.db.search_memories("", statuses=("active", "candidate"), limit=500))

        warned = service.add_memory(content="部署走内网镜像。", memory_type="decision")
        assert warned["status"] == "warning"
        assert warned["duplicates"]
        assert len(service.db.search_memories("", statuses=("active", "candidate"), limit=500)) == before

        forced = service.add_memory(content="部署走内网镜像。", memory_type="decision", force=True)
        assert forced["status"] == "created"
    finally:
        service.close()


def test_add_memory_rejects_bad_scope_and_target(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    try:
        with pytest.raises(MemoryCommandError) as bad_scope:
            service.add_memory(content="x", scope="universe")
        assert bad_scope.value.code == "invalid-scope"

        with pytest.raises(MemoryCommandError) as missing:
            service.add_memory(content="x", scope="project")
        assert missing.value.code == "missing-target"

        with pytest.raises(MemoryCommandError) as unknown:
            service.add_memory(content="x", scope="project", target_id="project_missing")
        assert unknown.value.code == "target-not-found"

        with pytest.raises(MemoryCommandError) as empty:
            service.add_memory(content="   ")
        assert empty.value.code == "missing-content"
    finally:
        service.close()


def test_link_makes_session_memory_visible_in_project(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    try:
        project = service.create_project("demo")
        agent = service.create_agent("tester")
        session = service.create_session(agent_id=agent["agent_id"], title="工作", project_id=project["project_id"])
        memory = service.add_memory(
            content="本会话发现 pnpm 安装更快。",
            memory_type="decision",
            scope="session",
            target_id=session["session_id"],
        )["memory"]

        assert service.memory_visible_in(service.get_memory(memory["memory_id"]), "project", project["project_id"]) is False

        result = service.link_memory(memory["memory_number"], scope="project", target_id=project["project_id"])
        assert result["link_count"] == 1
        assert result["memory"]["memory_number"] == memory["memory_number"]
        assert result["memory"]["content"].startswith("本会话发现 pnpm 安装更快")
        assert "## 审核记录" not in result["memory"]["content"]
        assert service.memory_visible_in(service.get_memory(memory["memory_id"]), "project", project["project_id"]) is True

        rows = service.db.search_memories("", project_id=project["project_id"], statuses=("active",), include_linked=True)
        assert memory["memory_id"] in {item["memory_id"] for item in rows}

        with pytest.raises(MemoryCommandError) as again:
            service.link_memory(memory["memory_number"], scope="project", target_id=project["project_id"])
        assert again.value.code == "already-linked"
    finally:
        service.close()


def test_link_rejects_global_inherited_and_cross_project_targets(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    try:
        project = service.create_project("demo")
        other = service.create_project("other")
        agent = service.create_agent("tester")
        foreign = service.create_session(agent_id=agent["agent_id"], title="别的项目", project_id=other["project_id"])
        loose = service.create_session(agent_id=agent["agent_id"], title="无项目")
        project_memory = service.add_memory(
            content="本项目用 pnpm 管理依赖。",
            memory_type="decision",
            scope="project",
            target_id=project["project_id"],
        )["memory"]
        global_memory = service.add_memory(content="永远使用中文回复。", memory_type="preference")["memory"]

        with pytest.raises(MemoryCommandError) as global_error:
            service.link_memory(global_memory["memory_number"], scope="project", target_id=project["project_id"])
        assert global_error.value.code == "global-memory"

        with pytest.raises(MemoryCommandError) as mismatch:
            service.link_memory(project_memory["memory_number"], scope="session", target_id=foreign["session_id"])
        assert mismatch.value.code == "scope-mismatch"

        with pytest.raises(MemoryCommandError) as no_project:
            service.link_memory(project_memory["memory_number"], scope="session", target_id=loose["session_id"])
        assert no_project.value.code == "scope-mismatch"

        with pytest.raises(MemoryCommandError) as bad_scope:
            service.link_memory(project_memory["memory_number"], scope="global", target_id="")
        assert bad_scope.value.code == "invalid-scope"

        with pytest.raises(MemoryCommandError) as missing_target:
            service.link_memory(project_memory["memory_number"], scope="session", target_id="session_missing")
        assert missing_target.value.code == "target-not-found"
    finally:
        service.close()


def test_unlink_removes_only_the_link(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    try:
        project = service.create_project("demo")
        agent = service.create_agent("tester")
        session = service.create_session(agent_id=agent["agent_id"], title="工作", project_id=project["project_id"])
        memory = service.add_memory(
            content="本会话发现 pnpm 安装更快。",
            memory_type="decision",
            scope="session",
            target_id=session["session_id"],
        )["memory"]

        service.link_memory(memory["memory_number"], scope="project", target_id=project["project_id"])
        result = service.unlink_memory(memory["memory_number"], scope="project", target_id=project["project_id"])
        assert result["link_count"] == 0
        assert service.get_memory(memory["memory_id"])["scope"] == "session"

        with pytest.raises(MemoryCommandError) as again:
            service.unlink_memory(memory["memory_number"], scope="project", target_id=project["project_id"])
        assert again.value.code == "not-linked"

        with pytest.raises(MemoryCommandError) as own_scope:
            service.unlink_memory(memory["memory_number"], scope="session", target_id=session["session_id"])
        assert own_scope.value.code == "not-linked"
    finally:
        service.close()


def test_delete_memory_removes_record_and_file(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    try:
        memory = service.add_memory(content="临时记录。", memory_type="context")["memory"]
        path = service.root / memory["file_path"]
        assert path.exists()

        result = service.delete_memory(memory["memory_number"])
        assert result["deleted"]["memory_number"] == memory["memory_number"]
        assert not path.exists()
        assert service.get_memory(memory["memory_id"]) is None

        with pytest.raises(MemoryCommandError) as missing:
            service.delete_memory(memory["memory_number"])
        assert missing.value.code == "memory-not-found"
    finally:
        service.close()


def test_rebuild_restores_links_after_index_drift(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    try:
        project = service.create_project("demo")
        agent = service.create_agent("tester")
        session = service.create_session(agent_id=agent["agent_id"], title="工作", project_id=project["project_id"])
        memory = service.add_memory(
            content="本会话发现 pnpm 安装更快。",
            memory_type="decision",
            scope="session",
            target_id=session["session_id"],
        )["memory"]
        service.link_memory(memory["memory_number"], scope="project", target_id=project["project_id"])

        service.db.connection.execute("DELETE FROM memory_links")
        service.db.commit()
        assert service.db.get_memory_links(memory["memory_id"]) == []

        service.rebuild_index(repair_numbers=False)

        links = service.db.get_memory_links(memory["memory_id"])
        assert [(row["scope"], row["target_id"]) for row in links] == [("project", project["project_id"])]
    finally:
        service.close()


def test_unlink_keeps_file_and_index_in_sync(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    try:
        project = service.create_project("demo")
        agent = service.create_agent("tester")
        session = service.create_session(agent_id=agent["agent_id"], title="工作", project_id=project["project_id"])
        memory = service.add_memory(
            content="本会话发现 pnpm 安装更快。",
            memory_type="decision",
            scope="session",
            target_id=session["session_id"],
        )["memory"]
        service.link_memory(memory["memory_number"], scope="project", target_id=project["project_id"])
        service.unlink_memory(memory["memory_number"], scope="project", target_id=project["project_id"])

        assert service.db.get_memory_links(memory["memory_id"]) == []
        text = (service.root / memory["file_path"]).read_text(encoding="utf-8")
        assert "links:" not in text
        assert service.get_memory(memory["memory_id"])["content"].startswith("本会话发现")
    finally:
        service.close()


def test_linked_memory_becomes_visible_to_target_session_then_hidden_after_unlink(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    try:
        project = service.create_project("demo")
        agent = service.create_agent("tester")
        service.grant_project_access(agent["agent_id"], project["project_id"])
        first = service.create_session(agent_id=agent["agent_id"], title="一", project_id=project["project_id"])
        second = service.create_session(agent_id=agent["agent_id"], title="二", project_id=project["project_id"])
        memory = service.add_memory(
            content="本会话发现 pnpm 安装更快。",
            memory_type="decision",
            scope="session",
            target_id=first["session_id"],
        )["memory"]

        def visible_to_second_session() -> set[str]:
            rows = service.search_memories("", session_id=second["session_id"], include_linked=True, limit=100)
            return {
                row["memory_id"]
                for row in rows
                if service.can_access_memory(row, session_id=second["session_id"])
            }

        assert memory["memory_id"] not in visible_to_second_session()

        service.link_memory(memory["memory_number"], scope="session", target_id=second["session_id"])
        assert memory["memory_id"] in visible_to_second_session()

        service.unlink_memory(memory["memory_number"], scope="session", target_id=second["session_id"])
        assert memory["memory_id"] not in visible_to_second_session()
    finally:
        service.close()


def test_link_grants_access_through_session_target(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    try:
        project = service.create_project("demo")
        agent = service.create_agent("tester")
        first = service.create_session(agent_id=agent["agent_id"], title="一", project_id=project["project_id"])
        second = service.create_session(agent_id=agent["agent_id"], title="二", project_id=project["project_id"])
        memory = service.add_memory(
            content="第一条会话里发现的镜像地址。",
            memory_type="context",
            scope="session",
            target_id=first["session_id"],
        )["memory"]

        assert service.can_access_memory(service.get_memory(memory["memory_id"]), session_id=second["session_id"]) is False

        service.link_memory(memory["memory_number"], scope="session", target_id=second["session_id"])

        assert service.can_access_memory(service.get_memory(memory["memory_id"]), session_id=second["session_id"]) is True
        rows = service.search_memories("", session_id=second["session_id"], include_linked=True, limit=100)
        assert memory["memory_id"] in {row["memory_id"] for row in rows}
    finally:
        service.close()
