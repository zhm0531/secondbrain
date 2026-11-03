#!/usr/bin/env python3
"""Minimal MCP stdio server that exposes SecondBrain Core to DeepSeek Harness."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen


SERVER_NAME = "secondbrain"
SERVER_VERSION = "0.1.0"
CORE_URL = os.environ.get("SECONDBRAIN_URL", "http://127.0.0.1:8765")
CORE_PROJECT = os.environ.get("SECONDBRAIN_PROJECT") or os.environ.get("SECONDBRAIN_HOME", "")
CORE_ROOT = os.environ.get("SECONDBRAIN_ROOT", "memory")
CORE_AUTOSTART = os.environ.get("SECONDBRAIN_AUTOSTART", "true").lower() not in {"0", "false", "no", "off"}
CORE_LOG = os.environ.get("SECONDBRAIN_CORE_LOG", str(Path(tempfile.gettempdir()) / "secondbrain-core.log"))
_core_process: subprocess.Popen | None = None
_core_lock = threading.Lock()


def _health_check() -> bool:
    try:
        with urlopen(CORE_URL.rstrip("/") + "/health", timeout=1) as response:
            return response.status == 200
    except Exception:
        return False


def _core_paths() -> tuple[Path, Path] | None:
    if not CORE_PROJECT:
        return None
    project = Path(CORE_PROJECT).expanduser().resolve()
    root = Path(CORE_ROOT).expanduser()
    if not root.is_absolute():
        root = project / root
    if not (project / "secondbrain_core").is_dir():
        return None
    return project, root.resolve()


def _ensure_core() -> bool:
    """Start the local Core on demand when the HTTP endpoint is down."""
    global _core_process
    if _health_check():
        return True
    if not CORE_AUTOSTART:
        return False
    with _core_lock:
        if _health_check():
            return True
        paths = _core_paths()
        if paths is None:
            return False
        project, root = paths
        if _core_process is not None and _core_process.poll() is None:
            return False
        root.mkdir(parents=True, exist_ok=True)
        environment = os.environ.copy()
        project_text = str(project)
        environment["PYTHONPATH"] = project_text + os.pathsep + environment.get("PYTHONPATH", "")
        command = [
            sys.executable,
            "-m",
            "secondbrain_core.server",
            "--root",
            str(root),
            "--host",
            urlsplit(CORE_URL).hostname or "127.0.0.1",
            "--port",
            str(urlsplit(CORE_URL).port or 8765),
        ]
        log_handle = None
        try:
            log_path = Path(CORE_LOG).expanduser()
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_handle = log_path.open("a", encoding="utf-8")
            creationflags = 0
            if os.name == "nt":
                creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
            _core_process = subprocess.Popen(
                command,
                cwd=project_text,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=log_handle,
                close_fds=True,
                creationflags=creationflags,
            )
        except OSError:
            return False
        finally:
            if log_handle is not None:
                log_handle.close()
        for _ in range(30):
            if _health_check():
                return True
            time.sleep(0.1)
        return False


def _perform_request(method: str, path: str, payload: dict | None = None) -> object:
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(CORE_URL.rstrip("/") + path, data=body, headers=headers, method=method)
    with urlopen(request, timeout=10) as response:
        raw = response.read().decode("utf-8")
        return json.loads(raw) if raw else None


def core_request(method: str, path: str, payload: dict | None = None) -> object:
    try:
        return _perform_request(method, path, payload)
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(raw)
        except json.JSONDecodeError:
            detail = raw
        raise RuntimeError(f"SecondBrain Core HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        if _ensure_core():
            try:
                return _perform_request(method, path, payload)
            except HTTPError as retry_exc:
                raw = retry_exc.read().decode("utf-8", errors="replace")
                try:
                    detail = json.loads(raw)
                except json.JSONDecodeError:
                    detail = raw
                raise RuntimeError(f"SecondBrain Core HTTP {retry_exc.code}: {detail}") from retry_exc
            except URLError as retry_exc:
                raise RuntimeError(f"SecondBrain Core unavailable at {CORE_URL}: {retry_exc.reason}") from retry_exc
        hint = " Set SECONDBRAIN_PROJECT to the SecondBrain source directory to enable auto-start."
        raise RuntimeError(f"SecondBrain Core unavailable at {CORE_URL}: {exc.reason}.{hint}") from exc


def text_result(value: object, *, is_error: bool = False) -> dict:
    return {
        "content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False, indent=2)}],
        "isError": is_error,
    }


def tool_definitions() -> list[dict]:
    return [
        {
            "name": "secondbrain_load",
            "description": "Load relevant active memories for the current task.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Current task or question."},
                    "scope": {"type": "string", "enum": ["global", "project", "session", "agent"]},
                    "project_id": {"type": "string"},
                    "agent_id": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                },
            },
        },
        {
            "name": "secondbrain_search",
            "description": "Search SecondBrain memories, optionally including candidates.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "scope": {"type": "string", "enum": ["global", "project", "session", "agent"]},
                    "project_id": {"type": "string"},
                    "agent_id": {"type": "string"},
                    "include_candidates": {"type": "boolean"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                },
            },
        },
        {
            "name": "secondbrain_propose",
            "description": "Create a candidate memory for later review.",
            "inputSchema": {
                "type": "object",
                "required": ["content", "memory_type", "scope"],
                "properties": {
                    "content": {"type": "string"},
                    "memory_type": {"type": "string"},
                    "scope": {"type": "string", "enum": ["global", "project", "session", "agent"]},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "agent_id": {"type": "string"},
                    "project_id": {"type": "string"},
                    "source_session_id": {"type": "string"},
                    "source_reference": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        {
            "name": "secondbrain_replace",
            "description": "Create a new active memory version and automatically supersede an old memory.",
            "inputSchema": {"type": "object", "required": ["old_memory_id", "content"], "properties": {
                "old_memory_id": {"type": "string"}, "content": {"type": "string"},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "agent_id": {"type": "string"}, "project_id": {"type": "string"},
                "source_session_id": {"type": "string"},
            }},
        },
        {
            "name": "secondbrain_get",
            "description": "Get one memory by ID.",
            "inputSchema": {"type": "object", "required": ["memory_id"], "properties": {"memory_id": {"type": "string"}}},
        },
        {
            "name": "secondbrain_approve",
            "description": "Approve a candidate memory and make it active.",
            "inputSchema": {"type": "object", "required": ["memory_id"], "properties": {"memory_id": {"type": "string"}}},
        },
        {
            "name": "secondbrain_reject",
            "description": "Reject a candidate memory.",
            "inputSchema": {"type": "object", "required": ["memory_id"], "properties": {"memory_id": {"type": "string"}}},
        },
        {
            "name": "secondbrain_archive",
            "description": "Archive a memory so it is excluded from default retrieval.",
            "inputSchema": {"type": "object", "required": ["memory_id"], "properties": {"memory_id": {"type": "string"}}},
        },
        {
            "name": "secondbrain_status",
            "description": "Check whether the local SecondBrain Core is reachable.",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "secondbrain_help",
            "description": "Show SecondBrain usage and available memory operations.",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "secondbrain_find_duplicates",
            "description": "Find active or candidate memories with identical normalized content.",
            "inputSchema": {"type": "object", "required": ["content"], "properties": {"content": {"type": "string"}, "scope": {"type": "string"}}},
        },
        {
            "name": "secondbrain_find_conflicts",
            "description": "Find active memories that may conflict with a proposed statement.",
            "inputSchema": {"type": "object", "required": ["content"], "properties": {"content": {"type": "string"}, "scope": {"type": "string"}}},
        },
    ]


def call_tool(name: str, arguments: dict) -> dict:
    if name in {"secondbrain_load", "secondbrain_search"}:
        params = {
            "q": arguments.get("query", ""),
            "include_candidates": "true" if name == "secondbrain_search" and arguments.get("include_candidates") else "false",
            "limit": arguments.get("limit", 8 if name == "secondbrain_load" else 20),
        }
        if arguments.get("scope"):
            params["scope"] = arguments["scope"]
        if arguments.get("agent_id"):
            params["request_agent_id"] = arguments["agent_id"]
        if arguments.get("project_id"):
            params["request_project_id"] = arguments["project_id"]
        if arguments.get("session_id"):
            params["request_session_id"] = arguments["session_id"]
        result = core_request("GET", "/api/memories/search?" + urlencode(params))
        return text_result(result)

    if name == "secondbrain_propose":
        payload = dict(arguments)
        payload["status"] = "candidate"
        return text_result(core_request("POST", "/api/memories", payload))

    if name == "secondbrain_replace":
        old_id = arguments.get("old_memory_id")
        if not old_id or not arguments.get("content"):
            raise ValueError("old_memory_id and content are required")
        payload = {key: value for key, value in arguments.items() if key != "old_memory_id" and value is not None}
        return text_result(core_request("POST", f"/api/memories/{old_id}/replace", payload))

    memory_id = arguments.get("memory_id")
    if name == "secondbrain_get":
        if not memory_id:
            raise ValueError("memory_id is required")
        return text_result(core_request("GET", f"/api/memories/{memory_id}"))
    if name in {"secondbrain_approve", "secondbrain_reject", "secondbrain_archive"}:
        if not memory_id:
            raise ValueError("memory_id is required")
        action = name.removeprefix("secondbrain_")
        return text_result(core_request("POST", f"/api/memories/{memory_id}/{action}", {}))
    if name == "secondbrain_status":
        return text_result(core_request("GET", "/health"))
    if name == "secondbrain_help":
        return text_result({
            "commands": [
                "@SecondBrain", "@SecondBrain load", "@SecondBrain search <query>",
                "@SecondBrain propose", "@SecondBrain review", "@SecondBrain approve <memory-id>",
                "@SecondBrain reject <memory-id>", "@SecondBrain status", "@SecondBrain help",
            ],
            "workflow": "load relevant active memories, propose candidates, then review and approve them",
        })
    if name in {"secondbrain_find_duplicates", "secondbrain_find_conflicts"}:
        path = "/api/memories/duplicates" if name.endswith("duplicates") else "/api/memories/conflicts"
        params = {"content": arguments.get("content", "")}
        if arguments.get("scope"):
            params["scope"] = arguments["scope"]
        return text_result(core_request("GET", path + "?" + urlencode(params)))
    raise ValueError(f"unknown tool: {name}")


def handle(message: dict) -> dict | None:
    method = message.get("method")
    request_id = message.get("id")
    if method == "notifications/initialized":
        return None
    if method == "ping":
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        }
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": tool_definitions()}}
    if method == "tools/call":
        params = message.get("params") or {}
        try:
            result = call_tool(params.get("name", ""), params.get("arguments") or {})
        except Exception as exc:
            result = text_result({"error": str(exc)}, is_error=True)
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    if request_id is None:
        return None
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def main() -> int:
    # MCP stdio is UTF-8 regardless of the Windows system locale.
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
            response = handle(message)
            if response is not None:
                sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
                sys.stdout.flush()
        except Exception as exc:
            print(f"[secondbrain-mcp] {exc}", file=sys.stderr, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
