from pathlib import Path

from secondbrain_core.service import SecondBrainService


def make_environment(tmp_path: Path):
    service = SecondBrainService(tmp_path / "memory")
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
    return service, project, session, memory


def notice_for(service: SecondBrainService, session_id: str | None) -> dict:
    items = service.search_memories("", statuses=("active",), limit=50, session_id=session_id)
    return {item["memory_number"]: item.get("unlink_notice", False) for item in items}


def test_unlink_notice_only_for_the_session_that_unlinked(tmp_path: Path) -> None:
    service, project, session, memory = make_environment(tmp_path)
    try:
        session_id = session["session_id"]
        service.unlink_memory(memory["memory_number"], scope="project", target_id=project["project_id"], session_id=session_id)

        assert notice_for(service, session_id)[memory["memory_number"]] is True
        assert notice_for(service, "session_someone_else")[memory["memory_number"]] is False
        assert notice_for(service, None)[memory["memory_number"]] is False
    finally:
        service.close()


def test_relink_in_same_session_clears_the_notice(tmp_path: Path) -> None:
    service, project, session, memory = make_environment(tmp_path)
    try:
        session_id = session["session_id"]
        service.unlink_memory(memory["memory_number"], scope="project", target_id=project["project_id"], session_id=session_id)
        assert notice_for(service, session_id)[memory["memory_number"]] is True

        service.link_memory(memory["memory_number"], scope="project", target_id=project["project_id"], session_id=session_id)
        assert notice_for(service, session_id)[memory["memory_number"]] is False
    finally:
        service.close()


def test_unlink_without_session_records_no_notice(tmp_path: Path) -> None:
    service, project, session, memory = make_environment(tmp_path)
    try:
        result = service.unlink_memory(memory["memory_number"], scope="project", target_id=project["project_id"])
        assert result["notice"] is False
        assert notice_for(service, session["session_id"])[memory["memory_number"]] is False
    finally:
        service.close()


def test_unlink_reports_notice_flag_and_get_exposes_it(tmp_path: Path) -> None:
    service, project, session, memory = make_environment(tmp_path)
    try:
        session_id = session["session_id"]
        result = service.unlink_memory(
            memory["memory_number"], scope="project", target_id=project["project_id"], session_id=session_id
        )
        assert result["notice"] is True

        detailed = service.get_memory(memory["memory_number"], session_id=session_id)
        assert detailed["unlink_notice"] is True
        assert service.get_memory(memory["memory_number"], session_id="session_someone_else")["unlink_notice"] is False
    finally:
        service.close()
