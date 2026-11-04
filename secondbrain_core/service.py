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

MEMORY_TYPE_LABELS = {
    "fact": "事实",
    "rule": "规则",
    "preference": "偏好",
    "decision": "决策",
    "instruction": "指令",
    "context": "上下文",
    "open_loop": "未决事项",
    "summary": "摘要",
}
SCOPE_LABELS = {"global": "全局", "project": "项目", "session": "会话", "agent": "Agent"}


class MemoryCommandError(ValueError):
    """Raised by the manual add / delete / link / unlink commands."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


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
        for link in record.get("links") or []:
            if link.get("scope") == "agent" and agent_id and link.get("target_id") == agent_id:
                return True
            if link.get("scope") == "project" and project_id and link.get("target_id") == project_id:
                return True
            if link.get("scope") == "session" and session_id and link.get("target_id") == session_id:
                return True
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
        record = self.get_memory(identifier, session_id=session_id) or self.db.get_memory_by_number(identifier)
        if record is None:
            raise KeyError(f"memory not found: {identifier}")
        # The local Web UI is an administrative view when no Agent context is supplied.
        if not agent_id and not project_id and not session_id:
            return self._with_unlink_notice(record, session_id)
        if self.can_access_memory(record, agent_id=agent_id, project_id=project_id, session_id=session_id):
            return self._with_unlink_notice(record, session_id)
        if not confirmed:
            return {"memory": self._with_unlink_notice(record, session_id), "requires_confirmation": True, "accessible": False}
        return self._with_unlink_notice(record, session_id)

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

    def get_memory(self, memory_id: str, *, session_id: str | None = None) -> dict[str, Any] | None:
        record = self.db.get_memory(memory_id) or self.db.get_memory_by_number(memory_id)
        if record is None:
            return None
        path = self.root / record["file_path"]
        if path.exists():
            metadata, body, _ = read_record(path)
            record.update(metadata)
            record["content"] = body
        return self._with_unlink_notice(record, session_id)

    def memory_history(self, memory_id: str) -> list[dict[str, Any]]:
        record = self.get_memory(memory_id)
        return self.db.list_history(record["memory_id"] if record else memory_id)

    DUPLICATE_CONTAINMENT = 0.9
    DUPLICATE_DICE = 0.6
    DUPLICATE_STRONG_DICE = 0.8
    CONFLICT_DICE = 0.4

    @staticmethod
    def _body_text(value: str) -> str:
        """Strip the appended `## 审核记录` trail: audit metadata must never count as content."""
        marker = value.find("## 审核记录")
        return value if marker < 0 else value[:marker]

    @classmethod
    def _normalized_content(cls, value: str) -> str:
        return re.sub(r"\s+", " ", cls._body_text(value)).strip().casefold()

    @classmethod
    def _shingles(cls, value: str, size: int = 3) -> set[str]:
        """Character n-grams are language-agnostic: no tokenizer needed for CJK text."""
        compact = re.sub(r"[^\w\u4e00-\u9fff]+", "", cls._normalized_content(value))
        if not compact:
            return set()
        if len(compact) <= size:
            return {compact}
        return {compact[index:index + size] for index in range(len(compact) - size + 1)}

    @classmethod
    def _similarity(cls, left: str, right: str) -> tuple[float, float]:
        left_grams, right_grams = cls._shingles(left), cls._shingles(right)
        if not left_grams or not right_grams:
            return 0.0, 0.0
        shared = len(left_grams & right_grams)
        dice = 2 * shared / (len(left_grams) + len(right_grams))
        containment = shared / min(len(left_grams), len(right_grams))
        return dice, containment

    @classmethod
    def classify_relation(cls, left: str, right: str) -> tuple[str | None, float]:
        """Return ('duplicate'|'conflict'|None, similarity)."""
        if cls._normalized_content(left) == cls._normalized_content(right):
            return "duplicate", 1.0
        dice, containment = cls._similarity(left, right)
        if dice >= cls.DUPLICATE_STRONG_DICE or (dice >= cls.DUPLICATE_DICE and containment >= cls.DUPLICATE_CONTAINMENT):
            return "duplicate", dice
        if dice >= cls.CONFLICT_DICE:
            return "conflict", dice
        return None, dice

    @staticmethod
    def _relation_reason(kind: str, scope: str, memory_type: str | None, similarity: float) -> str:
        type_text = MEMORY_TYPE_LABELS.get(memory_type, memory_type) if memory_type else "记忆"
        scope_text = SCOPE_LABELS.get(scope, scope)
        percent = round(similarity * 100)
        if kind == "duplicate":
            return f"正文高度相似（{percent}%），同为{type_text}类型、同一生效范围（{scope_text}），可能重复"
        return f"同一生效范围（{scope_text}）和{type_text}类型，正文主题相似度 {percent}%，可能互相矛盾"

    def find_similar_memories(self, content: str, *, scope: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
        target = self._normalized_content(content)
        candidates = self.db.search_memories("", scope=scope, statuses=("active", "candidate"), limit=500)
        return [item for item in candidates if self._normalized_content(item["content"]) == target][:limit]

    def find_conflicts(self, memory_id: str | None = None, *, content: str | None = None, scope: str | None = None, memory_type: str | None = None) -> list[dict[str, Any]]:
        current = self.get_memory(memory_id) if memory_id else None
        if current:
            content, scope, memory_type = current["content"], current["scope"], current["memory_type"]
        if not content:
            return []
        matches = []
        for item in self.db.search_memories("", scope=scope, statuses=("active",), limit=500):
            if memory_id and item["memory_id"] == memory_id:
                continue
            if memory_type and item["memory_type"] != memory_type:
                continue
            kind, dice = self.classify_relation(content, item["content"])
            if not kind:
                continue
            matches.append({
                **item,
                "kind": kind,
                "similarity": round(dice, 3),
                "overlap": round(dice, 3),
                "reason": self._relation_reason(kind, scope or item["scope"], memory_type or item["memory_type"], dice),
            })
        matches.sort(key=lambda entry: entry["similarity"], reverse=True)
        return matches

    def find_duplicate_groups(self, *, statuses: tuple[str, ...] = ("active",)) -> list[dict[str, Any]]:
        """Group memories that are exact or near duplicates (expansions / whitespace variants)."""
        items = self.db.search_memories("", statuses=statuses, limit=5000)
        parent = {item["memory_id"]: item["memory_id"] for item in items}

        def root(node: str) -> str:
            while parent[node] != node:
                parent[node] = parent[parent[node]]
                node = parent[node]
            return node

        for index, left in enumerate(items):
            for right in items[index + 1:]:
                if left["scope"] != right["scope"]:
                    continue
                kind, _ = self.classify_relation(left["content"], right["content"])
                if kind != "duplicate":
                    continue
                left_root, right_root = root(left["memory_id"]), root(right["memory_id"])
                if left_root != right_root:
                    parent[right_root] = left_root

        groups: dict[str, list[dict[str, Any]]] = {}
        for item in items:
            groups.setdefault(root(item["memory_id"]), []).append(item)
        result = []
        for group in groups.values():
            if len(group) < 2:
                continue
            result.append({
                "content": group[0]["content"],
                "kind": "duplicate",
                "count": len(group),
                "memory_numbers": [item.get("memory_number") for item in group],
                "memory_ids": [item["memory_id"] for item in group],
                "items": [
                    {
                        "memory_id": item["memory_id"],
                        "memory_number": item.get("memory_number"),
                        "status": item["status"],
                        "scope": item["scope"],
                        "updated_at": item["updated_at"],
                    }
                    for item in group
                ],
            })
        return result

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

    def memory_visible_in(self, record: dict[str, Any], scope: str, target_id: str) -> bool:
        if record.get("scope") == "global":
            return True
        own = {
            "session": record.get("source_session_id"),
            "project": record.get("project_id"),
            "agent": record.get("agent_id"),
        }
        if record.get("scope") == scope and own.get(scope) == target_id:
            return True
        return any(
            link.get("scope") == scope and link.get("target_id") == target_id
            for link in (record.get("links") or [])
        )

    def _resolve_scope_target(self, scope: str, target_id: str | None) -> dict[str, Any]:
        if scope not in VALID_SCOPES:
            raise MemoryCommandError(
                "invalid-scope",
                f"生效范围无效: '{scope}'（可选 global、project、session、agent）",
            )
        target = (target_id or "").strip()
        if scope == "global":
            if target:
                raise MemoryCommandError("invalid-target", "global 范围不接受目标参数")
            return {}
        if not target:
            raise MemoryCommandError(
                "missing-target",
                f"缺少目标: 范围 {SCOPE_LABELS.get(scope, scope)} 需要 --target",
            )
        if scope == "session":
            session = self.db.get_session(target)
            if session is None:
                raise MemoryCommandError("target-not-found", f"会话不存在: {target}")
            return {
                "source_session_id": target,
                "agent_id": session.get("agent_id"),
                "project_id": session.get("project_id"),
            }
        if scope == "project":
            if self.db.get_project(target) is None:
                raise MemoryCommandError("target-not-found", f"项目不存在: {target}")
            return {"project_id": target}
        if self.db.get_agent(target) is None:
            raise MemoryCommandError("target-not-found", f"Agent 不存在: {target}")
        return {"agent_id": target}

    def _check_link_target(self, record: dict[str, Any], scope: str, target_id: str) -> dict[str, Any]:
        if scope not in {"session", "project", "agent"}:
            raise MemoryCommandError(
                "invalid-scope",
                f"不能关联到范围 '{scope}'（可选 project、session、agent；全局记忆无需关联）",
            )
        info = self._resolve_scope_target(scope, target_id)
        if scope == "session":
            session_project = info.get("project_id")
            memory_project = record.get("project_id")
            if memory_project and session_project and memory_project != session_project:
                raise MemoryCommandError(
                    "scope-mismatch",
                    f"会话 {target_id} 属于项目 {session_project}，记忆属于项目 {memory_project}，不能关联",
                )
            if memory_project and not session_project:
                raise MemoryCommandError(
                    "scope-mismatch",
                    f"会话 {target_id} 不属于任何项目，无法关联项目 {memory_project} 的记忆",
                )
        return info

    def _verify_links(self, memory_id: str, expected: list[dict[str, Any]]) -> None:
        wanted = sorted((str(link.get("scope")), str(link.get("target_id"))) for link in expected)

        def indexed_links() -> list[tuple[str, str]]:
            record = self.get_memory(memory_id) or {}
            return sorted((str(link.get("scope")), str(link.get("target_id"))) for link in (record.get("links") or []))

        if indexed_links() == wanted:
            return
        self.rebuild_index(repair_numbers=False)
        if indexed_links() != wanted:
            raise MemoryCommandError(
                "internal-error",
                f"记忆 {memory_id} 关联写入后校验失败：文件与索引不一致",
            )

    @staticmethod
    def _history_session(row: dict[str, Any]) -> str | None:
        for key in ("after_json", "before_json"):
            raw = row.get(key)
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except (TypeError, ValueError):
                continue
            if isinstance(payload, dict) and payload.get("session_id"):
                return str(payload["session_id"])
        return None

    def _unlink_notice_flags(self, memory_ids: Iterable[str], session_id: str | None) -> dict[str, bool]:
        """Session-precise stale-context notice derived from history, never stored on the memory."""
        if not session_id:
            return {}
        latest = self.db.latest_link_events(list(dict.fromkeys(memory_ids)))
        flags: dict[str, bool] = {}
        for memory_id, row in latest.items():
            if row.get("action") != "unlinked":
                continue
            if self._history_session(row) == session_id:
                flags[memory_id] = True
        return flags

    def _with_unlink_notice(self, record: dict[str, Any], session_id: str | None) -> dict[str, Any]:
        if record and session_id:
            flags = self._unlink_notice_flags([record["memory_id"]], session_id)
            record["unlink_notice"] = bool(flags.get(record["memory_id"]))
        return record

    def link_memory(self, identifier: str, *, scope: str, target_id: str,
                    session_id: str | None = None) -> dict[str, Any]:
        record = self.get_memory(identifier)
        if record is None:
            raise MemoryCommandError("memory-not-found", f"记忆不存在: {identifier}")
        info = self._check_link_target(record, scope, target_id)
        label = f"{record.get('memory_number') or record['memory_id']}"
        if record.get("scope") == "global":
            raise MemoryCommandError("global-memory", f"记忆 {label} 是全局范围，对所有范围可见，无需关联")
        if self.memory_visible_in(record, scope, target_id):
            raise MemoryCommandError(
                "already-linked",
                f"记忆 {label} 已在 {SCOPE_LABELS.get(scope, scope)} {target_id} 的生效范围内",
            )
        if scope == "session" and self.can_access_memory(
            record,
            agent_id=info.get("agent_id"),
            project_id=info.get("project_id"),
            session_id=target_id,
        ):
            raise MemoryCommandError(
                "already-visible",
                f"记忆 {label} 已通过项目归属对该会话可见，无需关联",
            )
        links = [dict(link) for link in (record.get("links") or [])]
        now = utc_now()
        links.append({"scope": scope, "target_id": target_id, "created_at": now})
        path = self.root / record["file_path"]
        metadata, body, _ = read_record(path)
        metadata["links"] = links
        metadata["updated_at"] = now
        text = write_record(path, metadata, body)
        self.db.upsert_memory(
            {
                **metadata,
                "content": body,
                "file_path": record["file_path"],
                "content_hash": content_hash(text),
                "indexed_at": now,
            }
        )
        self.db.add_history(
            {
                "history_id": new_id("event"),
                "memory_id": record["memory_id"],
                "action": "linked",
                "before_json": None,
                "after_json": json.dumps(
                    {"scope": scope, "target_id": target_id, "session_id": session_id}, ensure_ascii=False
                ),
                "created_at": now,
            }
        )
        self.db.commit()
        self._verify_links(record["memory_id"], links)
        body = str(record.get("content") or "").split("## 审核记录")[0].strip()
        return {
            "memory_id": record["memory_id"],
            "memory_number": record.get("memory_number"),
            "scope": scope,
            "target_id": target_id,
            "link_count": len(links),
            "memory": {
                "memory_number": record.get("memory_number"),
                "memory_type": record.get("memory_type"),
                "scope": record.get("scope"),
                "status": record.get("status"),
                "content": body,
            },
        }

    def unlink_memory(self, identifier: str, *, scope: str, target_id: str,
                      session_id: str | None = None) -> dict[str, Any]:
        record = self.get_memory(identifier)
        if record is None:
            raise MemoryCommandError("memory-not-found", f"记忆不存在: {identifier}")
        if scope not in {"session", "project", "agent"}:
            raise MemoryCommandError("invalid-scope", f"不能解除范围 '{scope}' 的关联")
        label = f"{record.get('memory_number') or record['memory_id']}"
        links = [dict(link) for link in (record.get("links") or [])]
        remaining = [link for link in links if not (link.get("scope") == scope and link.get("target_id") == target_id)]
        if len(remaining) == len(links):
            if record.get("scope") == scope:
                raise MemoryCommandError(
                    "not-linked",
                    f"记忆 {label} 的存储范围就是 {SCOPE_LABELS.get(scope, scope)}，unlink 只能解除关联，不能改存储范围",
                )
            raise MemoryCommandError(
                "not-linked",
                f"记忆 {label} 未关联到 {SCOPE_LABELS.get(scope, scope)} {target_id}",
            )
        path = self.root / record["file_path"]
        metadata, body, _ = read_record(path)
        if remaining:
            metadata["links"] = remaining
        else:
            metadata.pop("links", None)
        now = utc_now()
        metadata["updated_at"] = now
        text = write_record(path, metadata, body)
        self.db.upsert_memory(
            {
                **metadata,
                "content": body,
                "file_path": record["file_path"],
                "content_hash": content_hash(text),
                "indexed_at": now,
            }
        )
        self.db.add_history(
            {
                "history_id": new_id("event"),
                "memory_id": record["memory_id"],
                "action": "unlinked",
                "before_json": json.dumps({"scope": scope, "target_id": target_id}, ensure_ascii=False),
                "after_json": json.dumps({"session_id": session_id}, ensure_ascii=False),
                "created_at": now,
            }
        )
        self.db.commit()
        self._verify_links(record["memory_id"], remaining)
        return {
            "memory_id": record["memory_id"],
            "memory_number": record.get("memory_number"),
            "scope": scope,
            "target_id": target_id,
            "link_count": len(remaining),
            "notice": session_id is not None,
        }

    def check_new_memory(self, content: str, *, scope: str = "global") -> dict[str, list[dict[str, Any]]]:
        duplicates: list[dict[str, Any]] = []
        conflicts: list[dict[str, Any]] = []
        for item in self.db.search_memories("", statuses=("active",), limit=5000):
            if item["scope"] != scope:
                continue
            kind, similarity = self.classify_relation(content, item["content"])
            if kind is None:
                continue
            entry = {
                "memory_id": item["memory_id"],
                "memory_number": item.get("memory_number"),
                "kind": kind,
                "similarity": round(similarity, 3),
                "reason": self._relation_reason(kind, scope, item.get("memory_type"), similarity),
            }
            (duplicates if kind == "duplicate" else conflicts).append(entry)
        return {"duplicates": duplicates, "conflicts": conflicts}

    def add_memory(
        self,
        *,
        content: str,
        memory_type: str = "fact",
        scope: str = "global",
        target_id: str | None = None,
        confidence: float = 0.5,
        tags: list[str] | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        text = (content or "").strip()
        if not text:
            raise MemoryCommandError("missing-content", "缺少记忆内容")
        if memory_type not in VALID_MEMORY_TYPES:
            raise MemoryCommandError(
                "invalid-type",
                f"记忆类型无效: '{memory_type}'（可选 {'、'.join(sorted(VALID_MEMORY_TYPES))}）",
            )
        context = self._resolve_scope_target(scope, target_id)
        warnings = self.check_new_memory(text, scope=scope)
        if (warnings["duplicates"] or warnings["conflicts"]) and not force:
            return {"status": "warning", "scope": scope, "target_id": target_id, **warnings}
        record = self.create_memory(
            content=text,
            memory_type=memory_type,
            scope=scope,
            status="active",
            confidence=confidence,
            tags=tags,
            **context,
        )
        return {"status": "created", "memory": record, **warnings}

    def delete_memory(self, identifier: str) -> dict[str, Any]:
        record = self.get_memory(identifier)
        if record is None:
            raise MemoryCommandError("memory-not-found", f"记忆不存在: {identifier}")
        path = self.root / record["file_path"]
        existed = path.exists()
        if existed:
            path.unlink()
        report = self.rebuild_index(repair_numbers=False)
        return {
            "deleted": {
                "memory_id": record["memory_id"],
                "memory_number": record.get("memory_number"),
                "status": record.get("status"),
                "file_removed": existed,
            },
            "memories": report["memories"],
        }

    def search_memories(
        self,
        query: str = "",
        *,
        scope: str | None = None,
        project_id: str | None = None,
        agent_id: str | None = None,
        statuses: Iterable[str] = ("active",),
        limit: int = 50,
        session_id: str | None = None,
        include_linked: bool = False,
    ) -> list[dict[str, Any]]:
        results = self.db.search_memories(
            query,
            scope=scope,
            project_id=project_id,
            agent_id=agent_id,
            session_id=session_id,
            statuses=statuses,
            limit=limit,
            include_linked=include_linked,
        )
        if include_linked:
            for item in results:
                item["links"] = self.db.get_memory_links(item["memory_id"])
        for item in results:
            conflicts = self.find_conflicts(content=item["content"], scope=item["scope"], memory_type=item["memory_type"])
            conflicts = [c for c in conflicts if c["memory_id"] != item["memory_id"]]
            item["has_conflicts"] = bool(conflicts)
            item["conflict_count"] = len(conflicts)
            item["relation_kinds"] = sorted({c["kind"] for c in conflicts})
        flags = self._unlink_notice_flags([item["memory_id"] for item in results], session_id)
        for item in results:
            item["unlink_notice"] = bool(flags.get(item["memory_id"]))
        return results

    def audit_memories(self) -> dict[str, Any]:
        active = self.db.search_memories("", statuses=("active",), limit=5000)
        conflicts = []
        seen: set[tuple[str, str]] = set()
        pollution = []
        for item in active:
            for other in self.find_conflicts(content=item["content"], scope=item["scope"], memory_type=item["memory_type"]):
                if other.get("kind") != "conflict":
                    continue
                pair = tuple(sorted((item["memory_id"], other["memory_id"])))
                if pair not in seen:
                    seen.add(pair)
                    conflicts.append({
                        "memory_id": item["memory_id"],
                        "memory_number": item.get("memory_number"),
                        "conflict_with": other["memory_id"],
                        "conflict_with_number": other.get("memory_number"),
                        "kind": other.get("kind"),
                        "similarity": other.get("similarity"),
                        "overlap": other.get("overlap"),
                        "reason": other.get("reason"),
                    })
            if item["scope"] == "agent" and not item.get("agent_id"):
                pollution.append({"memory_id": item["memory_id"], "issue": "agent scope missing agent_id"})
            if item["scope"] == "project" and not item.get("project_id"):
                pollution.append({"memory_id": item["memory_id"], "issue": "project scope missing project_id"})
            if item["scope"] == "session" and not item.get("source_session_id"):
                pollution.append({"memory_id": item["memory_id"], "issue": "session scope missing source_session_id"})
            if not item.get("agent_id") or not item.get("source_session_id"):
                pollution.append({"memory_id": item["memory_id"], "issue": "missing provenance"})
        return {
            "active_count": len(active),
            "duplicates": self.find_duplicate_groups(statuses=("active",)),
            "conflicts": conflicts,
            "pollution": pollution,
            "duplicate_numbers": self.db.duplicate_memory_numbers(),
        }

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

    def _repair_duplicate_numbers_on_disk(self) -> dict[str, Any]:
        """把共享同一编号的记忆重新编号（直接改 Markdown 前置元数据，不依赖索引）。

        旧版 ``next_memory_number()`` 用 ``ORDER BY rowid DESC``，``rebuild_index()`` 重排行序后
        会发出重复编号；新库的 ``memory_number`` 带 UNIQUE 约束，重复编号会在重建时被静默丢弃，
        所以修复必须在写索引之前、直接对文件做。
        """

        records: list[tuple[Path, dict[str, Any], str]] = []
        for status in ("active", "candidates", "archived", "rejected"):
            for path in (self.memories_dir / status).glob("*.md"):
                try:
                    metadata, body, _ = read_record(path)
                except Exception:
                    continue
                records.append((path, metadata, body))

        groups: dict[str, list[tuple[Path, dict[str, Any], str]]] = {}
        highest = 0
        for path, metadata, body in records:
            raw = metadata.get("memory_number")
            if not raw:
                continue
            number = str(raw)
            groups.setdefault(number, []).append((path, metadata, body))
            digits = re.sub(r"\D", "", number)
            if digits:
                highest = max(highest, int(digits))

        repaired: list[dict[str, Any]] = []
        for number, items in groups.items():
            if len(items) < 2:
                continue
            items.sort(key=lambda entry: (str(entry[1].get("created_at") or ""), str(entry[1].get("memory_id") or "")))
            for path, metadata, body in items[1:]:
                highest += 1
                new_number = f"#{highest:06d}"
                metadata["memory_number"] = new_number
                write_record(path, metadata, body)
                repaired.append({
                    "memory_id": metadata.get("memory_id"),
                    "from": number,
                    "to": new_number,
                })

        return {
            "repaired_count": len(repaired),
            "groups": len([items for items in groups.values() if len(items) > 1]),
            "repaired": repaired,
        }

    def repair_memory_numbers(self) -> dict[str, Any]:
        """修复历史重号并重建索引，随后尝试加唯一索引（老库没有）。"""

        report = self._repair_duplicate_numbers_on_disk()
        rebuilt = self.rebuild_index(repair_numbers=False)
        report["memories"] = rebuilt["memories"]
        report["unique_index"] = self.db.ensure_unique_memory_numbers()
        return report

    def rebuild_index(self, *, repair_numbers: bool = True) -> dict[str, Any]:
        repaired = self._repair_duplicate_numbers_on_disk() if repair_numbers else {"repaired_count": 0}
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
        report["repaired_numbers"] = repaired["repaired_count"]
        return report
