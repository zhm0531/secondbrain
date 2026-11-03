from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

from .database import Database
from .storage import (
    append_audit,
    append_event,
    content_hash,
    new_id,
    read_record,
    utc_now,
    write_record,
)


VALID_MEMORY_TYPES = {
    "preference",
    "fact",
    "decision",
    "instruction",
    "context",
    "open_loop",
    "summary",
}
VALID_SCOPES = {"global", "project", "session", "agent"}
VALID_STATUSES = {"candidate", "active", "superseded", "archived", "rejected"}
STATUS_DIRS = {
    "candidate": "candidates",
    "active": "active",
    "superseded": "archived",
    "archived": "archived",
    "rejected": "rejected",
}


class SecondBrainService:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.sessions_dir = self.root / "sessions"
        self.memories_dir = self.root / "memories"
        self.db = Database(self.root / "index.sqlite3")
        for directory in (
            self.sessions_dir,
            self.memories_dir / "active",
            self.memories_dir / "candidates",
            self.memories_dir / "archived",
            self.memories_dir / "rejected",
            self.root / "system",
        ):
            directory.mkdir(parents=True, exist_ok=True)

    def close(self) -> None:
        self.db.close()

    def list_agents(self) -> list[dict[str, Any]]:
        return self.db.list_agents()

    def list_projects(self) -> list[dict[str, Any]]:
        return self.db.list_projects()

    def list_sessions(self, limit: int = 100) -> list[dict[str, Any]]:
        return self.db.list_sessions(limit)

    def update_project(self, project_id: str, *, name: str | None = None, description: str | None = None) -> dict[str, Any]:
        project = self.db.get_project(project_id)
        if project is None:
            raise KeyError(f"project not found: {project_id}")
        now = utc_now()
        self.db.upsert_project({**project, "name": name if name is not None else project["name"], "description": description if description is not None else project["description"], "updated_at": now})
        self.db.commit()
        return self.db.get_project(project_id) or {}

    def update_session(self, session_id: str, *, title: str | None = None, summary: str | None = None) -> dict[str, Any]:
        session = self.db.get_session(session_id)
        if session is None:
            raise KeyError(f"session not found: {session_id}")
        path = self.root / session["file_path"]
        metadata, body, _ = read_record(path)
        if title is not None:
            metadata["title"] = title
        if summary is not None:
            metadata["summary"] = summary
            body = re.sub(r"(?s)(# 当前摘要\n\n).*?(\n\n# 已确认决策)", rf"\1{summary}\2", body)
        metadata["updated_at"] = utc_now()
        write_record(path, metadata, body)
        self.rebuild_index()
        return self.db.get_session(session_id) or {}

    def create_agent(
        self,
        display_name: str,
        *,
        agent_id: str | None = None,
        adapter_type: str | None = None,
        settings: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        record = {
            "agent_id": agent_id or new_id("agent"),
            "display_name": display_name,
            "adapter_type": adapter_type,
            "settings": settings or {},
            "created_at": now,
            "last_seen_at": now,
        }
        self.db.upsert_agent(record)
        self.db.commit()
        return record

    def create_project(
        self,
        name: str,
        *,
        project_id: str | None = None,
        description: str = "",
        root_path: str | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        record = {
            "project_id": project_id or new_id("project"),
            "name": name,
            "description": description,
            "root_path": root_path,
            "created_at": now,
            "updated_at": now,
        }
        self.db.upsert_project(record)
        self.db.commit()
        return record

    def create_session(
        self,
        *,
        agent_id: str,
        title: str,
        project_id: str | None = None,
        summary: str = "",
        session_id: str | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        session_id = session_id or new_id("session")
        relative_path = Path("sessions") / session_id / "README.md"
        metadata = {
            "record_type": "session",
            "schema_version": 1,
            "session_id": session_id,
            "agent_id": agent_id,
            "project_id": project_id,
            "title": title,
            "status": "active",
            "created_at": now,
            "updated_at": now,
            "archived_at": None,
            "tags": tags or [],
        }
        body = (
            "# 会话目标\n\n"
            f"{title}\n\n"
            "# 当前摘要\n\n"
            f"{summary}\n\n"
            "# 已确认决策\n\n"
            "# 未解决问题\n\n"
            "# 相关记忆\n"
        )
        absolute_path = self.root / relative_path
        text = write_record(absolute_path, metadata, body)
        self.db.upsert_session(
            {
                **metadata,
                "summary": summary,
                "file_path": relative_path.as_posix(),
                "content_hash": content_hash(text),
                "indexed_at": now,
            }
        )
        self.db.commit()
        append_event(
            absolute_path.parent / "events.md",
            "session-created",
            {"actor": "system", "summary": title},
        )
        return {**metadata, "file_path": relative_path.as_posix()}

    def create_memory(
        self,
        *,
        content: str,
        memory_type: str,
        scope: str,
        status: str = "candidate",
        confidence: float = 0.5,
        agent_id: str | None = None,
        project_id: str | None = None,
        source_session_id: str | None = None,
        source_reference: str | None = None,
        tags: list[str] | None = None,
        expires_at: str | None = None,
        supersedes_memory_id: str | None = None,
        memory_id: str | None = None,
    ) -> dict[str, Any]:
        if memory_type not in VALID_MEMORY_TYPES:
            raise ValueError(f"unsupported memory_type: {memory_type}")
        if scope not in VALID_SCOPES:
            raise ValueError(f"unsupported scope: {scope}")
        if status not in VALID_STATUSES:
            raise ValueError(f"unsupported status: {status}")
        if not 0 <= confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        if not content.strip():
            raise ValueError("content must not be empty")

        now = utc_now()
        is_new_memory = memory_id is None
        memory_id = memory_id or new_id("memory")
        memory_number = self.db.next_memory_number() if is_new_memory else None
        relative_path = Path("memories") / STATUS_DIRS[status] / f"{memory_id}.md"
        metadata = {
            "record_type": "memory",
            "schema_version": 1,
            "memory_id": memory_id,
            "memory_number": memory_number,
            "scope": scope,
            "memory_type": memory_type,
            "status": status,
            "confidence": confidence,
            "agent_id": agent_id,
            "project_id": project_id,
            "source_session_id": source_session_id,
            "source_reference": source_reference,
            "created_at": now,
            "updated_at": now,
            "expires_at": expires_at,
            "supersedes_memory_id": supersedes_memory_id,
            "tags": tags or [],
        }
        body = content.strip()
        absolute_path = self.root / relative_path
        text = write_record(absolute_path, metadata, body)
        self.db.upsert_memory(
            {
                **metadata,
                "content": body,
                "file_path": relative_path.as_posix(),
                "content_hash": content_hash(text),
                "indexed_at": now,
            }
        )
        self.db.add_history({
            "history_id": new_id("event"), "memory_id": memory_id, "action": "created",
            "before_json": None, "after_json": json.dumps(metadata, ensure_ascii=False), "created_at": now,
        })
        self.db.commit()
        return {**metadata, "content": body, "file_path": relative_path.as_posix()}

    def can_access_memory(self, record: dict[str, Any], *, agent_id: str | None = None,
                          project_id: str | None = None, session_id: str | None = None) -> bool:
        if record.get("scope") == "global":
            return True
        if record.get("scope") == "agent":
            return bool(agent_id and record.get("agent_id") == agent_id)
        if record.get("scope") == "project":
            return bool(agent_id and project_id and record.get("project_id") == project_id and self.db.has_project_access(agent_id, project_id))
        if record.get("scope") == "session":
            return bool(session_id and record.get("source_session_id") == session_id)
        return False

    def grant_project_access(self, agent_id: str, project_id: str) -> dict[str, Any]:
        now = utc_now()
        self.db.grant_project_access(agent_id, project_id, now)
        self.db.commit()
        return {"agent_id": agent_id, "project_id": project_id, "granted_at": now}

    def revoke_project_access(self, agent_id: str, project_id: str) -> None:
        self.db.revoke_project_access(agent_id, project_id)
        self.db.commit()

    def list_project_access(self, project_id: str | None = None) -> list[dict[str, Any]]:
        return self.db.list_project_access(project_id)

    def get_memory_for_context(self, identifier: str, *, agent_id: str | None = None,
                               project_id: str | None = None, session_id: str | None = None,
                               confirmed: bool = False) -> dict[str, Any]:
        record = self.get_memory(identifier) or self.db.get_memory_by_number(identifier)
        if record is None:
            raise KeyError(f"memory not found: {identifier}")
        # The local Web UI is an administrative view when no Agent context is supplied.
        if not agent_id and not project_id and not session_id:
            return record
        if self.can_access_memory(record, agent_id=agent_id, project_id=project_id, session_id=session_id):
            return record
        if not confirmed:
            return {"memory": record, "requires_confirmation": True, "accessible": False}
        return record

    def replace_memory(self, old_memory_id: str, *, content: str, memory_type: str | None = None,
                       scope: str | None = None, confidence: float = 0.9,
                       agent_id: str | None = None, project_id: str | None = None,
                       source_session_id: str | None = None, source_reference: str | None = None,
                       tags: list[str] | None = None) -> dict[str, Any]:
        old = self.get_memory(old_memory_id)
        if old is None:
            raise KeyError(f"memory not found: {old_memory_id}")
        new = self.create_memory(
            content=content,
            memory_type=memory_type or old["memory_type"],
            scope=scope or old["scope"],
            status="active",
            confidence=confidence,
            agent_id=agent_id or old.get("agent_id"),
            project_id=project_id if project_id is not None else old.get("project_id"),
            source_session_id=source_session_id or old.get("source_session_id"),
            source_reference=source_reference or "automatic-replacement",
            tags=tags if tags is not None else old.get("tags", []),
            supersedes_memory_id=old_memory_id,
        )
        self._transition_memory(old_memory_id, "superseded", f"被新记忆 {new['memory_id']} 自动替代。")
        return {"new_memory": self.get_memory(new["memory_id"]), "superseded_memory": self.get_memory(old_memory_id)}

    def get_memory(self, memory_id: str) -> dict[str, Any] | None:
        record = self.db.get_memory(memory_id) or self.db.get_memory_by_number(memory_id)
        if record is None:
            return None
        path = self.root / record["file_path"]
        if path.exists():
            metadata, body, _ = read_record(path)
            record.update(metadata)
            record["content"] = body
        return record

    def memory_history(self, memory_id: str) -> list[dict[str, Any]]:
        record = self.get_memory(memory_id)
        return self.db.list_history(record["memory_id"] if record else memory_id)

    @staticmethod
    def _normalized_content(value: str) -> str:
        return re.sub(r"\s+", " ", value).strip().casefold()

    def find_similar_memories(self, content: str, *, scope: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
        target = self._normalized_content(content)
        candidates = self.db.search_memories("", scope=scope, statuses=("active", "candidate"), limit=500)
        return [item for item in candidates if self._normalized_content(item["content"]) == target][:limit]

    def find_conflicts(self, memory_id: str | None = None, *, content: str | None = None, scope: str | None = None, memory_type: str | None = None) -> list[dict[str, Any]]:
        current = self.get_memory(memory_id) if memory_id else None
        if current:
            content, scope, memory_type = current["content"], current["scope"], current["memory_type"]
        if not content or not scope:
            return []
        words = set(re.findall(r"[\w\u4e00-\u9fff]+", content.casefold()))
        matches = []
        for item in self.db.search_memories("", scope=scope, statuses=("active",), limit=500):
            if memory_id and item["memory_id"] == memory_id:
                continue
            if memory_type and item["memory_type"] != memory_type:
                continue
            other = set(re.findall(r"[\w\u4e00-\u9fff]+", item["content"].casefold()))
            overlap = len(words & other) / max(1, min(len(words), len(other)))
            if overlap >= 0.4 and self._normalized_content(content) != self._normalized_content(item["content"]):
                matches.append({**item, "overlap": round(overlap, 3)})
        return matches

    def propose_memory(self, **kwargs: Any) -> dict[str, Any]:
        memory = self.create_memory(**kwargs, status="candidate")
        conflicts = self.find_conflicts(
            content=memory["content"],
            scope=memory["scope"],
            memory_type=memory["memory_type"],
        )
        return {
            "memory": memory,
            "conflicts": conflicts,
            "requires_confirmation": bool(conflicts),
            "next_action": "ask_user_whether_to_replace" if conflicts else "review_or_approve",
        }

    def review_conflicts(self) -> list[dict[str, Any]]:
        queue = []
        for item in self.db.search_memories("", statuses=("candidate",), limit=500):
            conflicts = self.find_conflicts(content=item["content"], scope=item["scope"], memory_type=item["memory_type"])
            if conflicts:
                queue.append({"candidate": item, "conflicts": conflicts})
        return queue

    def resolve_conflict(self, candidate_id: str, action: str, old_memory_id: str | None = None) -> dict[str, Any]:
        candidate = self.get_memory(candidate_id)
        if candidate is None or candidate["status"] != "candidate":
            raise KeyError(f"candidate memory not found: {candidate_id}")
        if action == "keep":
            return {"action": action, "result": self.approve_memory(candidate_id)}
        if action == "reject":
            return {"action": action, "result": self.reject_memory(candidate_id)}
        if action == "replace":
            if not old_memory_id:
                raise ValueError("old_memory_id is required for replace")
            result = self.replace_memory(
                old_memory_id,
                content=candidate["content"],
                memory_type=candidate["memory_type"],
                scope=candidate["scope"],
                confidence=candidate["confidence"],
                agent_id=candidate.get("agent_id"),
                project_id=candidate.get("project_id"),
                source_session_id=candidate.get("source_session_id"),
                source_reference=candidate.get("source_reference"),
                tags=candidate.get("tags", []),
            )
            self.archive_memory(candidate_id, reason="候选记忆已用于替换旧版本。")
            return {"action": action, "result": result}
        raise ValueError("action must be keep, reject, or replace")

    def resolve_all_conflicts(self, action: str) -> list[dict[str, Any]]:
        if action not in {"keep", "reject", "replace"}:
            raise ValueError("bulk action must be keep, reject, or replace")
        results = []
        for item in self.review_conflicts():
            old_id = item["conflicts"][0]["memory_id"] if action == "replace" and item["conflicts"] else None
            results.append(self.resolve_conflict(item["candidate"]["memory_id"], action, old_id))
        return results

    def expire_memories(self) -> list[str]:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        ids = [item["memory_id"] for item in self.db.list_expired_memories(now)]
        for memory_id in ids:
            self.archive_memory(memory_id, reason="记忆已超过 expires_at。")
        return ids

    def search_memories(
        self,
        query: str = "",
        *,
        scope: str | None = None,
        project_id: str | None = None,
        agent_id: str | None = None,
        statuses: Iterable[str] = ("active",),
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        results = self.db.search_memories(
            query,
            scope=scope,
            project_id=project_id,
            agent_id=agent_id,
            statuses=statuses,
            limit=limit,
        )
        for item in results:
            conflicts = self.find_conflicts(content=item["content"], scope=item["scope"], memory_type=item["memory_type"])
            conflicts = [c for c in conflicts if c["memory_id"] != item["memory_id"]]
            item["has_conflicts"] = bool(conflicts)
            item["conflict_count"] = len(conflicts)
        return results

    def audit_memories(self) -> dict[str, Any]:
        active = self.db.search_memories("", statuses=("active",), limit=5000)
        conflicts = []
        seen: set[tuple[str, str]] = set()
        pollution = []
        for item in active:
            for other in self.find_conflicts(content=item["content"], scope=item["scope"], memory_type=item["memory_type"]):
                pair = tuple(sorted((item["memory_id"], other["memory_id"])))
                if pair not in seen:
                    seen.add(pair)
                    conflicts.append({"memory_id": item["memory_id"], "conflict_with": other["memory_id"], "overlap": other.get("overlap")})
            if item["scope"] == "agent" and not item.get("agent_id"):
                pollution.append({"memory_id": item["memory_id"], "issue": "agent scope missing agent_id"})
            if item["scope"] == "project" and not item.get("project_id"):
                pollution.append({"memory_id": item["memory_id"], "issue": "project scope missing project_id"})
            if item["scope"] == "session" and not item.get("source_session_id"):
                pollution.append({"memory_id": item["memory_id"], "issue": "session scope missing source_session_id"})
            if not item.get("agent_id") or not item.get("source_session_id"):
                pollution.append({"memory_id": item["memory_id"], "issue": "missing provenance"})
        return {"active_count": len(active), "conflicts": conflicts, "pollution": pollution}

    def update_memory(
        self,
        memory_id: str,
        *,
        content: str | None = None,
        confidence: float | None = None,
        tags: list[str] | None = None,
        expires_at: str | None = None,
        source_reference: str | None = None,
    ) -> dict[str, Any]:
        record = self.get_memory(memory_id)
        if record is None:
            raise KeyError(f"memory not found: {memory_id}")
        memory_id = record["memory_id"]
        if content is not None and not content.strip():
            raise ValueError("content must not be empty")
        if confidence is not None and not 0 <= confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")

        path = self.root / record["file_path"]
        metadata, body, _ = read_record(path)
        if content is not None:
            body = content.strip()
        if confidence is not None:
            metadata["confidence"] = confidence
        if tags is not None:
            metadata["tags"] = tags
        if expires_at is not None:
            metadata["expires_at"] = expires_at
        if source_reference is not None:
            metadata["source_reference"] = source_reference
        metadata["updated_at"] = utc_now()
        text = write_record(path, metadata, body)
        self.db.upsert_memory(
            {
                **metadata,
                "content": body,
                "file_path": record["file_path"],
                "content_hash": content_hash(text),
                "indexed_at": utc_now(),
            }
        )
        self.db.add_history({
            "history_id": new_id("event"), "memory_id": memory_id, "action": "updated",
            "before_json": json.dumps(record, ensure_ascii=False, default=str),
            "after_json": json.dumps(metadata, ensure_ascii=False), "created_at": metadata["updated_at"],
        })
        self.db.commit()
        return self.get_memory(memory_id) or {}

    def _transition_memory(self, memory_id: str, new_status: str, audit_message: str) -> dict[str, Any]:
        if new_status not in VALID_STATUSES:
            raise ValueError(f"unsupported status: {new_status}")
        record = self.get_memory(memory_id)
        if record is None:
            raise KeyError(f"memory not found: {memory_id}")
        memory_id = record["memory_id"]

        old_path = self.root / record["file_path"]
        metadata, body, _ = read_record(old_path)
        metadata["status"] = new_status
        metadata["updated_at"] = utc_now()
        body = append_audit(body, audit_message)
        new_relative_path = Path("memories") / STATUS_DIRS[new_status] / f"{memory_id}.md"
        new_path = self.root / new_relative_path
        write_record(new_path, metadata, body)
        if old_path != new_path and old_path.exists():
            old_path.unlink()
        text = new_path.read_text(encoding="utf-8")
        self.db.upsert_memory(
            {
                **metadata,
                "content": body,
                "file_path": new_relative_path.as_posix(),
                "content_hash": content_hash(text),
                "indexed_at": utc_now(),
            }
        )
        self.db.add_history({
            "history_id": new_id("event"), "memory_id": memory_id, "action": new_status,
            "before_json": json.dumps(record, ensure_ascii=False, default=str),
            "after_json": json.dumps(metadata, ensure_ascii=False), "created_at": metadata["updated_at"],
        })
        self.db.commit()
        return self.get_memory(memory_id) or {}

    def approve_memory(self, memory_id: str) -> dict[str, Any]:
        return self._transition_memory(memory_id, "active", "用户确认该候选记忆。")

    def reject_memory(self, memory_id: str) -> dict[str, Any]:
        return self._transition_memory(memory_id, "rejected", "用户拒绝该候选记忆。")

    def archive_memory(self, memory_id: str, reason: str = "记忆被归档。") -> dict[str, Any]:
        return self._transition_memory(memory_id, "archived", reason)

    def rebuild_index(self) -> dict[str, Any]:
        self.db.reset_indexes()
        report = {"sessions": 0, "memories": 0, "errors": []}
        for path in self.sessions_dir.glob("*/README.md"):
            try:
                metadata, body, text = read_record(path)
                now = utc_now()
                agent_id = metadata.get("agent_id")
                if agent_id:
                    self.db.upsert_agent(
                        {
                            "agent_id": agent_id,
                            "display_name": agent_id,
                            "adapter_type": "recovered",
                            "settings": {},
                            "created_at": metadata.get("created_at", now),
                            "last_seen_at": now,
                        }
                    )
                project_id = metadata.get("project_id")
                if project_id:
                    if self.db.get_project(project_id) is None:
                        self.db.upsert_project({"project_id": project_id, "name": project_id, "description": "Recovered from Markdown metadata.", "root_path": None, "created_at": metadata.get("created_at", now), "updated_at": now})
                self.db.upsert_session(
                    {
                        **metadata,
                        "summary": body,
                        "file_path": path.relative_to(self.root).as_posix(),
                        "content_hash": content_hash(text),
                        "indexed_at": now,
                    }
                )
                report["sessions"] += 1
            except Exception as exc:
                report["errors"].append({"path": str(path), "error": str(exc)})

        for status in ("active", "candidates", "archived", "rejected"):
            directory = self.memories_dir / status
            actual_status = "candidate" if status == "candidates" else status
            for path in directory.glob("*.md"):
                try:
                    metadata, body, text = read_record(path)
                    now = utc_now()
                    if not metadata.get("memory_number"):
                        metadata["memory_number"] = self.db.next_memory_number()
                        write_record(path, metadata, body)
                    agent_id = metadata.get("agent_id")
                    if agent_id:
                        self.db.upsert_agent(
                            {
                                "agent_id": agent_id,
                                "display_name": agent_id,
                                "adapter_type": "recovered",
                                "settings": {},
                                "created_at": metadata.get("created_at", now),
                                "last_seen_at": now,
                            }
                        )
                    project_id = metadata.get("project_id")
                    if project_id:
                        if self.db.get_project(project_id) is None:
                            self.db.upsert_project({"project_id": project_id, "name": project_id, "description": "Recovered from Markdown metadata.", "root_path": None, "created_at": metadata.get("created_at", now), "updated_at": now})
                    self.db.upsert_memory(
                        {
                            **metadata,
                            "status": actual_status,
                            "content": body,
                            "file_path": path.relative_to(self.root).as_posix(),
                            "content_hash": content_hash(text),
                            "indexed_at": now,
                        }
                    )
                    report["memories"] += 1
                except Exception as exc:
                    report["errors"].append({"path": str(path), "error": str(exc)})
        self.db.commit()
        return report
