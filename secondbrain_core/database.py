from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS agents (
    agent_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    adapter_type TEXT,
    settings_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
    project_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    root_path TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_projects (
    agent_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    granted_at TEXT NOT NULL,
    PRIMARY KEY (agent_id, project_id),
    FOREIGN KEY (agent_id) REFERENCES agents(agent_id) ON DELETE CASCADE,
    FOREIGN KEY (project_id) REFERENCES projects(project_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    project_id TEXT,
    title TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    file_path TEXT NOT NULL UNIQUE,
    content_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    indexed_at TEXT NOT NULL,
    FOREIGN KEY (agent_id) REFERENCES agents(agent_id),
    FOREIGN KEY (project_id) REFERENCES projects(project_id)
);

CREATE TABLE IF NOT EXISTS memories (
    memory_id TEXT PRIMARY KEY,
    memory_number TEXT UNIQUE,
    scope TEXT NOT NULL,
    memory_type TEXT NOT NULL,
    status TEXT NOT NULL,
    content TEXT NOT NULL,
    confidence REAL NOT NULL,
    agent_id TEXT,
    project_id TEXT,
    source_session_id TEXT,
    source_reference TEXT,
    file_path TEXT NOT NULL UNIQUE,
    content_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    expires_at TEXT,
    supersedes_memory_id TEXT,
    indexed_at TEXT NOT NULL,
    FOREIGN KEY (agent_id) REFERENCES agents(agent_id),
    FOREIGN KEY (project_id) REFERENCES projects(project_id),
    FOREIGN KEY (source_session_id) REFERENCES sessions(session_id),
    FOREIGN KEY (supersedes_memory_id) REFERENCES memories(memory_id)
);

CREATE TABLE IF NOT EXISTS memory_tags (
    memory_id TEXT NOT NULL,
    tag TEXT NOT NULL,
    PRIMARY KEY (memory_id, tag),
    FOREIGN KEY (memory_id) REFERENCES memories(memory_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    actor_type TEXT NOT NULL,
    summary TEXT NOT NULL,
    file_path TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
);

CREATE TABLE IF NOT EXISTS memory_links (
    memory_id TEXT NOT NULL,
    scope TEXT NOT NULL,
    target_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (memory_id, scope, target_id),
    FOREIGN KEY (memory_id) REFERENCES memories(memory_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS memory_history (
    history_id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL,
    action TEXT NOT NULL,
    before_json TEXT,
    after_json TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (memory_id) REFERENCES memories(memory_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_memories_status ON memories(status);
CREATE INDEX IF NOT EXISTS idx_memories_scope ON memories(scope);
CREATE INDEX IF NOT EXISTS idx_memories_project ON memories(project_id);
CREATE INDEX IF NOT EXISTS idx_memories_agent ON memories(agent_id);
CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions(project_id);
CREATE INDEX IF NOT EXISTS idx_memory_links_target ON memory_links(scope, target_id);
"""


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.executescript(SCHEMA)
        columns = {row[1] for row in self.connection.execute("PRAGMA table_info(memories)").fetchall()}
        if "memory_number" not in columns:
            self.connection.execute("ALTER TABLE memories ADD COLUMN memory_number TEXT")
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def reset_indexes(self) -> None:
        self.connection.execute("DELETE FROM memory_links")
        self.connection.execute("DELETE FROM memory_tags")
        self.connection.execute("DELETE FROM events")
        self.connection.execute("DELETE FROM memories")
        self.connection.execute("DELETE FROM sessions")
        self.connection.commit()

    def upsert_agent(self, record: dict[str, Any]) -> None:
        self.connection.execute(
            """
            INSERT INTO agents(agent_id, display_name, adapter_type, settings_json, created_at, last_seen_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(agent_id) DO UPDATE SET
                display_name=excluded.display_name,
                adapter_type=excluded.adapter_type,
                settings_json=excluded.settings_json,
                last_seen_at=excluded.last_seen_at
            """,
            (
                record["agent_id"],
                record.get("display_name", record["agent_id"]),
                record.get("adapter_type"),
                json.dumps(record.get("settings", {}), ensure_ascii=False),
                record["created_at"],
                record.get("last_seen_at", record["created_at"]),
            ),
        )

    def upsert_project(self, record: dict[str, Any]) -> None:
        self.connection.execute(
            """
            INSERT INTO projects(project_id, name, description, root_path, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_id) DO UPDATE SET
                name=excluded.name,
                description=excluded.description,
                root_path=excluded.root_path,
                updated_at=excluded.updated_at
            """,
            (
                record["project_id"],
                record["name"],
                record.get("description", ""),
                record.get("root_path"),
                record["created_at"],
                record.get("updated_at", record["created_at"]),
            ),
        )

    def upsert_session(self, record: dict[str, Any]) -> None:
        self.connection.execute(
            """
            INSERT INTO sessions(
                session_id, agent_id, project_id, title, summary, status,
                file_path, content_hash, created_at, updated_at, indexed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                agent_id=excluded.agent_id,
                project_id=excluded.project_id,
                title=excluded.title,
                summary=excluded.summary,
                status=excluded.status,
                file_path=excluded.file_path,
                content_hash=excluded.content_hash,
                created_at=excluded.created_at,
                updated_at=excluded.updated_at,
                indexed_at=excluded.indexed_at
            """,
            (
                record["session_id"],
                record["agent_id"],
                record.get("project_id"),
                record["title"],
                record.get("summary", ""),
                record["status"],
                record["file_path"],
                record["content_hash"],
                record["created_at"],
                record["updated_at"],
                record["indexed_at"],
            ),
        )

    def upsert_memory(self, record: dict[str, Any]) -> None:
        self.connection.execute(
            """
            INSERT INTO memories(
                memory_id, memory_number, scope, memory_type, status, content, confidence,
                agent_id, project_id, source_session_id, source_reference,
                file_path, content_hash, created_at, updated_at, expires_at,
                supersedes_memory_id, indexed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(memory_id) DO UPDATE SET
                memory_number=excluded.memory_number,
                scope=excluded.scope,
                memory_type=excluded.memory_type,
                status=excluded.status,
                content=excluded.content,
                confidence=excluded.confidence,
                agent_id=excluded.agent_id,
                project_id=excluded.project_id,
                source_session_id=excluded.source_session_id,
                source_reference=excluded.source_reference,
                file_path=excluded.file_path,
                content_hash=excluded.content_hash,
                created_at=excluded.created_at,
                updated_at=excluded.updated_at,
                expires_at=excluded.expires_at,
                supersedes_memory_id=excluded.supersedes_memory_id,
                indexed_at=excluded.indexed_at
            """,
            (
                record["memory_id"],
                record.get("memory_number"),
                record["scope"],
                record["memory_type"],
                record["status"],
                record["content"],
                float(record.get("confidence", 0.5)),
                record.get("agent_id"),
                record.get("project_id"),
                record.get("source_session_id"),
                record.get("source_reference"),
                record["file_path"],
                record["content_hash"],
                record["created_at"],
                record["updated_at"],
                record.get("expires_at"),
                record.get("supersedes_memory_id"),
                record["indexed_at"],
            ),
        )
        self.connection.execute("DELETE FROM memory_tags WHERE memory_id = ?", (record["memory_id"],))
        self.connection.executemany(
            "INSERT INTO memory_tags(memory_id, tag) VALUES (?, ?)",
            [(record["memory_id"], tag) for tag in record.get("tags", [])],
        )
        self.connection.execute("DELETE FROM memory_links WHERE memory_id = ?", (record["memory_id"],))
        self.connection.executemany(
            "INSERT OR IGNORE INTO memory_links(memory_id, scope, target_id, created_at) VALUES (?, ?, ?, ?)",
            [
                (record["memory_id"], link["scope"], link["target_id"], link.get("created_at") or record["created_at"])
                for link in record.get("links", [])
                if link.get("scope") and link.get("target_id")
            ],
        )

    def commit(self) -> None:
        self.connection.commit()

    def list_agents(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT agent_id, display_name, adapter_type, created_at, last_seen_at "
            "FROM agents ORDER BY display_name"
        ).fetchall()
        return [dict(row) for row in rows]

    def list_projects(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT project_id, name, description, root_path, created_at, updated_at "
            "FROM projects ORDER BY name"
        ).fetchall()
        return [dict(row) for row in rows]

    def get_agent(self, agent_id: str) -> dict[str, Any] | None:
        row = self.connection.execute("SELECT * FROM agents WHERE agent_id = ?", (agent_id,)).fetchone()
        return dict(row) if row else None

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        row = self.connection.execute("SELECT * FROM projects WHERE project_id = ?", (project_id,)).fetchone()
        return dict(row) if row else None

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        row = self.connection.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
        return dict(row) if row else None

    def grant_project_access(self, agent_id: str, project_id: str, granted_at: str) -> None:
        self.connection.execute(
            "INSERT INTO agent_projects(agent_id, project_id, granted_at) VALUES (?, ?, ?) "
            "ON CONFLICT(agent_id, project_id) DO UPDATE SET granted_at=excluded.granted_at",
            (agent_id, project_id, granted_at),
        )

    def revoke_project_access(self, agent_id: str, project_id: str) -> None:
        self.connection.execute("DELETE FROM agent_projects WHERE agent_id = ? AND project_id = ?", (agent_id, project_id))

    def has_project_access(self, agent_id: str, project_id: str) -> bool:
        return self.connection.execute(
            "SELECT 1 FROM agent_projects WHERE agent_id = ? AND project_id = ?", (agent_id, project_id)
        ).fetchone() is not None

    def list_project_access(self, project_id: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT agent_id, project_id, granted_at FROM agent_projects"
        values: tuple[Any, ...] = ()
        if project_id:
            query += " WHERE project_id = ?"
            values = (project_id,)
        return [dict(row) for row in self.connection.execute(query + " ORDER BY granted_at", values).fetchall()]

    def list_sessions(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT * FROM sessions ORDER BY updated_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(row) for row in rows]

    def list_expired_memories(self, now: str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT * FROM memories WHERE status = 'active' AND expires_at IS NOT NULL AND expires_at <= ? "
            "ORDER BY expires_at",
            (now,),
        ).fetchall()
        return [dict(row) for row in rows]

    def add_history(self, record: dict[str, Any]) -> None:
        self.connection.execute(
            "INSERT INTO memory_history(history_id, memory_id, action, before_json, after_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (record["history_id"], record["memory_id"], record["action"], record.get("before_json"), record.get("after_json"), record["created_at"]),
        )

    def list_history(self, memory_id: str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT * FROM memory_history WHERE memory_id = ? ORDER BY created_at DESC", (memory_id,)
        ).fetchall()
        return [dict(row) for row in rows]

    def latest_link_events(self, memory_ids: list[str]) -> dict[str, dict[str, Any]]:
        """Return the most recent link/unlink event per memory, in insertion order."""
        if not memory_ids:
            return {}
        placeholders = ",".join("?" for _ in memory_ids)
        rows = self.connection.execute(
            f"SELECT memory_id, action, before_json, after_json, created_at FROM memory_history "
            f"WHERE memory_id IN ({placeholders}) AND action IN ('linked', 'unlinked') "
            f"ORDER BY created_at ASC, rowid ASC",
            tuple(memory_ids),
        ).fetchall()
        latest: dict[str, dict[str, Any]] = {}
        for row in rows:
            latest[row["memory_id"]] = dict(row)
        return latest

    def get_memory(self, memory_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT * FROM memories WHERE memory_id = ?", (memory_id,)
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["tags"] = [
            item[0]
            for item in self.connection.execute(
                "SELECT tag FROM memory_tags WHERE memory_id = ? ORDER BY tag", (memory_id,)
            ).fetchall()
        ]
        return result

    def get_memory_by_number(self, memory_number: str) -> dict[str, Any] | None:
        row = self.connection.execute("SELECT * FROM memories WHERE memory_number = ?", (memory_number,)).fetchone()
        return dict(row) if row else None

    def ensure_unique_memory_numbers(self) -> bool:
        """尽力给 memory_number 加唯一索引；老库迁移出来的列没有该约束。"""

        try:
            self.connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_memories_number_unique ON memories(memory_number)"
            )
            self.connection.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def duplicate_memory_numbers(self) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT memory_number, COUNT(*) AS n FROM memories WHERE memory_number IS NOT NULL "
            "GROUP BY memory_number HAVING n > 1 ORDER BY memory_number"
        ).fetchall()
        return [{"memory_number": row[0], "count": row[1]} for row in rows]

    def next_memory_number(self) -> str:
        # Use the numeric maximum instead of the last inserted row: an index rebuild
        # re-inserts rows in arbitrary order, so "rowid DESC" would hand out numbers
        # that already exist.
        row = self.connection.execute(
            "SELECT MAX(CAST(ltrim(memory_number, '#') AS INTEGER)) FROM memories WHERE memory_number IS NOT NULL"
        ).fetchone()
        if row and row[0]:
            return f"#{int(row[0]) + 1:06d}"
        count = self.connection.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        return f"#{count + 1:06d}"

    def get_memory_links(self, memory_id: str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT scope, target_id, created_at FROM memory_links WHERE memory_id = ? ORDER BY created_at",
            (memory_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def search_memories(
        self,
        query: str = "",
        *,
        scope: str | None = None,
        project_id: str | None = None,
        agent_id: str | None = None,
        session_id: str | None = None,
        statuses: Iterable[str] = ("active",),
        limit: int = 50,
        include_linked: bool = False,
    ) -> list[dict[str, Any]]:
        clauses = []
        values: list[Any] = []
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        if query:
            clauses.append("LOWER(content) LIKE LOWER(?)")
            values.append(f"%{query}%")
        status_values = list(statuses)
        if status_values:
            placeholders = ",".join("?" for _ in status_values)
            clauses.append(f"status IN ({placeholders})")
            values.extend(status_values)
        clauses.append("(expires_at IS NULL OR expires_at > ?)")
        values.append(now)
        if scope:
            clauses.append("scope = ?")
            values.append(scope)
        if project_id:
            clauses.append("project_id = ?")
            values.append(project_id)
        if agent_id:
            clauses.append("agent_id = ?")
            values.append(agent_id)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        values.append(limit)
        rows = self.connection.execute(
            f"SELECT * FROM memories {where} ORDER BY updated_at DESC LIMIT ?", values
        ).fetchall()
        results = [dict(row) for row in rows]

        if include_linked and (session_id or project_id or agent_id):
            link_clauses: list[str] = []
            link_values: list[Any] = []
            if session_id:
                link_clauses.append("(l.scope = 'session' AND l.target_id = ?)")
                link_values.append(session_id)
            if project_id:
                link_clauses.append("(l.scope = 'project' AND l.target_id = ?)")
                link_values.append(project_id)
            if agent_id:
                link_clauses.append("(l.scope = 'agent' AND l.target_id = ?)")
                link_values.append(agent_id)
            sql = (
                "SELECT m.* FROM memories m JOIN memory_links l ON l.memory_id = m.memory_id "
                f"WHERE ({' OR '.join(link_clauses)})"
            )
            extra_values = list(link_values)
            if query:
                sql += " AND LOWER(m.content) LIKE LOWER(?)"
                extra_values.append(f"%{query}%")
            if status_values:
                placeholders = ",".join("?" for _ in status_values)
                sql += f" AND m.status IN ({placeholders})"
                extra_values.extend(status_values)
            sql += " AND (m.expires_at IS NULL OR m.expires_at > ?)"
            extra_values.append(now)
            sql += " ORDER BY m.updated_at DESC LIMIT ?"
            extra_values.append(limit)
            known = {item["memory_id"] for item in results}
            for row in self.connection.execute(sql, extra_values).fetchall():
                if row["memory_id"] not in known:
                    results.append(dict(row))
                    known.add(row["memory_id"])
            results.sort(key=lambda item: item["updated_at"], reverse=True)
            results = results[:limit]

        for result in results:
            result["tags"] = [
                item[0]
                for item in self.connection.execute(
                    "SELECT tag FROM memory_tags WHERE memory_id = ? ORDER BY tag",
                    (result["memory_id"],),
                ).fetchall()
            ]
        return results
