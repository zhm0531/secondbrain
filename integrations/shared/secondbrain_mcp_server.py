#!/usr/bin/env python3
"""Minimal MCP stdio server that exposes SecondBrain Core to DeepSeek Harness."""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import webbrowser
from urllib.error import HTTPError, URLError
import re
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


def _default_project() -> Path | None:
    """Derive the repository root from this file when no project is configured."""
    candidate = Path(__file__).resolve().parents[4]
    return candidate if (candidate / "secondbrain_core").is_dir() else None


def _core_paths() -> tuple[Path, Path] | None:
    project = Path(CORE_PROJECT).expanduser().resolve() if CORE_PROJECT else _default_project()
    if project is None:
        return None
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


COMMAND_HINTS = {
    ("link", "invalid-scope"): "关联只支持 project、session、agent；全局记忆对所有范围可见。",
    ("unlink", "invalid-scope"): "只能解除 project、session、agent 的关联。",
    ("add", "invalid-scope"): "可选 global、project、session、agent。",
}


def _call_memory_command(method: str, path: str, payload: dict | None, command: str) -> object:
    """Run a Core call that may legitimately reject the request (link/delete/add)."""

    try:
        return core_request(method, path, payload)
    except RuntimeError as exc:
        match = re.match(r"SecondBrain Core HTTP (?:400|404): (.*)$", str(exc), re.S)
        if match:
            try:
                detail = ast.literal_eval(match.group(1))
            except (ValueError, SyntaxError):
                detail = None
            if isinstance(detail, dict) and detail.get("error"):
                raise UsageError(
                    str(detail["error"]),
                    _usage(command),
                    COMMAND_HINTS.get((command, str(detail.get("code") or ""))) or CODE_HINTS.get(str(detail.get("code") or "")),
                ) from None
        raise


def _confirm_delete(record: dict) -> str:
    label = record.get("memory_number") or record.get("memory_id")
    type_label = MEMORY_TYPE_LABELS.get(record.get("memory_type"), record.get("memory_type") or "记忆")
    scope_label = SCOPE_LABELS.get(record.get("scope"), record.get("scope") or "未知")
    body = (record.get("content") or "").split("## 审核记录")[0].strip().replace("\n", " ")
    if len(body) > 40:
        body = body[:40] + "…"
    return (
        f"确认删除 {label} [{type_label}·{scope_label}]？\n"
        f"摘要: {body}\n"
        f"回复 '@SecondBrain delete {label} --confirm' 执行；其它命令取消。"
    )


def _open_ui() -> dict:
    """Open the Web UI, starting the Core first when it is not running."""
    started = False
    if not _health_check():
        started = _ensure_core()
        if not _health_check():
            raise RuntimeError(
                "SecondBrain Core 未运行且自动启动失败。请手动执行 open_secondbrain.cmd，"
                "或 python -m secondbrain_core.cli --root memory open。"
            )
    url = CORE_URL.rstrip("/") + "/"
    try:
        opened = webbrowser.open(url)
    except Exception:
        opened = False
    return {"ok": True, "url": url, "core_started": started, "browser_opened": bool(opened)}


MEMORY_TYPE_LABELS = {
    "preference": "偏好",
    "fact": "事实",
    "rule": "规则",
    "decision": "决策",
    "instruction": "指令",
    "context": "上下文",
    "open_loop": "未决事项",
    "summary": "摘要",
}
SCOPE_LABELS = {"global": "全局", "project": "项目", "session": "会话", "agent": "Agent"}

CODE_HINTS = {
    "already-linked": "先用 '@SecondBrain get <memory-id>' 查看它现有的生效范围。",
    "not-linked": "先用 '@SecondBrain get <memory-id>' 查看它现有的生效范围。",
    "global-memory": "全局记忆对所有范围可见，不需要关联。",
    "scope-mismatch": "会话与记忆的项目归属必须一致；确实要换范围请用 replace。",
    "target-not-found": "先核对目标 id；项目、会话、Agent 的 id 都来自 Core 的索引。",
    "missing-target": "例如 --scope=project --target=<project-id>",
    "invalid-target": "global 范围不需要 --target。",
    "invalid-scope": "可选 global、project、session、agent。",
    "memory-not-found": "先用 '@SecondBrain search <关键词>' 确认编号。",
    "missing-content": "记忆内容写在命令末尾。",
    "invalid-type": "可选 preference、fact、decision、instruction、context、open_loop、summary。",
}


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


SCOPES = ("global", "project", "session", "agent")
CHECK_MODES = ("all", "conflicts", "duplicates")
MEMORY_TYPES = ("preference", "fact", "decision", "instruction", "context", "open_loop", "summary")
MEMORY_ID_PATTERN = re.compile(r"^(#[0-9]{1,6}|memory_[0-9a-fA-F-]{8,}|[0-9a-fA-F][0-9a-fA-F-]{7,})$")

COMMAND_USAGE = {
    "help": "@SecondBrain help",
    "load": "@SecondBrain load [query]",
    "search": "@SecondBrain search <query>",
    "get": "@SecondBrain get <memory-id>",
    "propose": "@SecondBrain propose",
    "review": "@SecondBrain review",
    "approve": "@SecondBrain approve <memory-id>",
    "reject": "@SecondBrain reject <memory-id>",
    "archive": "@SecondBrain archive <memory-id>",
    "status": "@SecondBrain status",
    "open": "@SecondBrain open",
    "check": "@SecondBrain check [all|conflicts|duplicates]",
    "conflicts": "@SecondBrain conflicts <content>",
    "duplicates": "@SecondBrain duplicates <content>",
    "add": "@SecondBrain add [--scope=<scope>] [--target=<id>] [--type=<type>] [--force] <content>",
    "delete": "@SecondBrain delete <memory-id> [--confirm]",
    "link": "@SecondBrain link <memory-id> --scope=<scope> --target=<id>",
    "unlink": "@SecondBrain unlink <memory-id> --scope=<scope> --target=<id>",
}
COMMAND_LIST = "、".join(sorted(COMMAND_USAGE, key=list(COMMAND_USAGE).index))

TOOL_COMMANDS = {
    "secondbrain_help": "help",
    "secondbrain_load": "load",
    "secondbrain_search": "search",
    "secondbrain_get": "get",
    "secondbrain_propose": "propose",
    "secondbrain_approve": "approve",
    "secondbrain_reject": "reject",
    "secondbrain_archive": "archive",
    "secondbrain_status": "status",
    "secondbrain_open": "open",
    "secondbrain_check": "check",
    "secondbrain_find_conflicts": "conflicts",
    "secondbrain_find_duplicates": "duplicates",
    "secondbrain_replace": "propose",
    "secondbrain_add": "add",
    "secondbrain_delete": "delete",
    "secondbrain_link": "link",
    "secondbrain_unlink": "unlink",
}
TOOL_ARGUMENTS = {
    "secondbrain_load": ("query", "scope", "project_id", "agent_id", "session_id", "limit"),
    "secondbrain_search": ("query", "scope", "project_id", "agent_id", "session_id", "include_candidates", "limit"),
    "secondbrain_propose": ("content", "memory_type", "scope", "confidence", "agent_id", "project_id", "source_session_id", "source_reference", "tags"),
    "secondbrain_replace": ("old_memory_id", "content", "confidence", "agent_id", "project_id", "source_session_id"),
    "secondbrain_get": ("memory_id", "session_id"),
    "secondbrain_approve": ("memory_id",),
    "secondbrain_reject": ("memory_id",),
    "secondbrain_archive": ("memory_id",),
    "secondbrain_status": (),
    "secondbrain_open": (),
    "secondbrain_help": (),
    "secondbrain_check": ("check",),
    "secondbrain_find_conflicts": ("content", "scope"),
    "secondbrain_find_duplicates": ("content", "scope"),
    "secondbrain_add": ("content", "memory_type", "scope", "target_id", "confidence", "tags", "force"),
    "secondbrain_delete": ("memory_id", "confirm"),
    "secondbrain_link": ("memory_id", "scope", "target_id", "session_id"),
    "secondbrain_unlink": ("memory_id", "scope", "target_id", "session_id"),
}


class UsageError(Exception):
    """An invalid invocation that must be reported as a normalised usage message."""

    def __init__(self, message: str, usage: str | None = None, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.usage = usage
        self.hint = hint

    def render(self) -> str:
        lines = [f"secondbrain: {self.message}"]
        if self.usage:
            lines.append(f"用法: {self.usage}")
        if self.hint:
            lines.append(f"提示: {self.hint}")
        lines.append("尝试 '@SecondBrain help' 获取完整用法。")
        return "\n".join(lines)


def text_message(message: str, *, is_error: bool = True) -> dict:
    return {"content": [{"type": "text", "text": message}], "isError": is_error}


def _usage(command: str) -> str:
    return COMMAND_USAGE.get(command, "@SecondBrain <命令> [参数...]")


def _check_memory_id(value: object, command: str) -> str:
    if value is None or value == "":
        raise UsageError("缺少参数: memory-id", _usage(command))
    if not isinstance(value, str):
        raise UsageError(f"参数 memory-id 必须是字符串，收到 {type(value).__name__}", _usage(command))
    if not MEMORY_ID_PATTERN.match(value.strip()):
        raise UsageError(
            f"无法识别的记忆编号: '{value}'",
            _usage(command),
            "记忆编号形如 #000014，也可以是完整 UUID。",
        )
    return value.strip()


def _resolve_memory_id(value: object, command: str) -> str:
    identifier = _check_memory_id(value, command)
    if not identifier.startswith("#"):
        return identifier
    result = core_request("GET", "/api/memories/search?" + urlencode({"q": "", "include_candidates": "true", "limit": 500}))
    for item in (result or {}).get("items", []):
        if item.get("memory_number") == identifier:
            return item["memory_id"]
    raise UsageError(f"未找到记忆: {identifier}", _usage(command), "先用 '@SecondBrain search <关键词>' 确认编号。")


def _check_choice(value: object, field: str, choices: tuple[str, ...], command: str) -> str:
    if value is None or value == "":
        raise UsageError(f"缺少参数: {field}", _usage(command))
    text = str(value)
    if text not in choices:
        raise UsageError(
            f"参数 {field} 的值无效: '{text}'",
            _usage(command),
            f"可选值为 {'、'.join(choices)}。",
        )
    return text


def _check_int(value: object, field: str, low: int, high: int, command: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise UsageError(f"参数 {field} 必须是整数，收到 {value!r}", _usage(command))
    if not low <= value <= high:
        raise UsageError(f"参数 {field} 超出范围: {value}（允许 {low}-{high}）", _usage(command))
    return value


def _check_text(value: object, field: str, command: str, *, limit: int = 4000) -> str:
    if not isinstance(value, str) or not value.strip():
        raise UsageError(f"缺少参数: {field}", _usage(command))
    if len(value) > limit:
        raise UsageError(f"参数 {field} 过长: {len(value)} 字（上限 {limit}）", _usage(command))
    return value


def _validate_arguments(name: str, arguments: dict) -> dict:
    command = TOOL_COMMANDS.get(name)
    if command is None:
        short = name.removeprefix("secondbrain_") or name
        raise UsageError(f"未知命令: '{short}'", "@SecondBrain <命令> [参数...]", f"可用命令: {COMMAND_LIST}")
    if not isinstance(arguments, dict):
        raise UsageError("参数必须以对象形式提供", _usage(command))
    extra = sorted(set(arguments) - set(TOOL_ARGUMENTS.get(name, ())))
    if extra:
        raise UsageError(f"未知选项: {', '.join(extra)}", _usage(command))
    cleaned = {key: value for key, value in arguments.items() if value is not None}
    if name in {"secondbrain_load", "secondbrain_search"}:
        if "query" in cleaned and cleaned["query"] != "":
            cleaned["query"] = _check_text(cleaned["query"], "query", command)
        if "scope" in cleaned:
            cleaned["scope"] = _check_choice(cleaned["scope"], "scope", SCOPES, command)
        if "limit" in cleaned:
            cleaned["limit"] = _check_int(cleaned["limit"], "limit", 1, 50 if name == "secondbrain_load" else 100, command)
    if name == "secondbrain_propose":
        cleaned["content"] = _check_text(cleaned.get("content"), "content", command)
        cleaned["memory_type"] = _check_choice(cleaned.get("memory_type"), "memory_type", MEMORY_TYPES, command)
        cleaned["scope"] = _check_choice(cleaned.get("scope"), "scope", SCOPES, command)
        if "confidence" in cleaned:
            value = cleaned["confidence"]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
                raise UsageError(f"参数 confidence 超出范围: {value!r}（允许 0-1）", _usage(command))
    if name == "secondbrain_replace":
        cleaned["old_memory_id"] = _check_memory_id(cleaned.get("old_memory_id"), command)
        cleaned["content"] = _check_text(cleaned.get("content"), "content", command)
    if name in {"secondbrain_get", "secondbrain_approve", "secondbrain_reject", "secondbrain_archive"}:
        cleaned["memory_id"] = _check_memory_id(cleaned.get("memory_id"), command)
    if name == "secondbrain_check" and "check" in cleaned:
        cleaned["check"] = _check_choice(cleaned["check"], "check", CHECK_MODES, command)
    if name == "secondbrain_add":
        cleaned["content"] = _check_text(cleaned.get("content"), "content", command)
        cleaned["memory_type"] = _check_choice(cleaned.get("memory_type", "fact"), "memory_type", MEMORY_TYPES, command)
        cleaned["scope"] = _check_choice(cleaned.get("scope", "global"), "scope", SCOPES, command)
        if "target_id" in cleaned:
            cleaned["target_id"] = _check_text(cleaned["target_id"], "target_id", command, limit=200)
        if "confidence" in cleaned:
            value = cleaned["confidence"]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
                raise UsageError(f"参数 confidence 超出范围: {value!r}（允许 0-1）", _usage(command))
    if name == "secondbrain_delete":
        cleaned["memory_id"] = _check_memory_id(cleaned.get("memory_id"), command)
    if name in {"secondbrain_link", "secondbrain_unlink"}:
        cleaned["memory_id"] = _check_memory_id(cleaned.get("memory_id"), command)
        cleaned["scope"] = _check_choice(cleaned.get("scope"), "scope", SCOPES, command)
        cleaned["target_id"] = _check_text(cleaned.get("target_id"), "target_id", command, limit=200)
    if name in {"secondbrain_find_conflicts", "secondbrain_find_duplicates"}:
        cleaned["content"] = _check_text(cleaned.get("content"), "content", command)
        if "scope" in cleaned:
            cleaned["scope"] = _check_choice(cleaned["scope"], "scope", SCOPES, command)
    return cleaned


def parse_command(text: str) -> tuple[str, dict]:
    """Turn an "@SecondBrain ..." line into (tool name, arguments)."""

    raw = (text or "").strip()
    while raw.startswith("@"):
        raw = raw[1:].strip()
    if raw.lower().startswith("secondbrain"):
        raw = raw[len("secondbrain"):].strip()
        if raw.startswith("_"):
            raw = raw[1:].strip()
    parts = raw.split()
    if not parts:
        return "secondbrain_load", {"query": ""}
    command = parts[0].lower()
    args = parts[1:]
    if command not in COMMAND_USAGE:
        raise UsageError(f"未知命令: '{parts[0]}'", "@SecondBrain <命令> [参数...]", f"可用命令: {COMMAND_LIST}")
    options: dict[str, str] = {}
    positional: list[str] = []
    index = 0
    while index < len(args):
        arg = args[index]
        index += 1
        if not arg.startswith("--"):
            positional.append(arg)
            continue
        key, separator, value = arg[2:].partition("=")
        if key not in {"scope", "limit", "all", "type", "target", "confirm", "force", "session"}:
            raise UsageError(f"未知选项: '--{key}'", _usage(command))
        if key in {"all", "confirm", "force"} and not separator:
            options[key] = "true"
            continue
        if not separator:
            if index >= len(args) or args[index].startswith("--"):
                raise UsageError(f"选项 --{key} 缺少值", _usage(command))
            value = args[index]
            index += 1
        elif not value:
            raise UsageError(f"选项 --{key} 缺少值", _usage(command))
        options[key] = value

    if command in {"help", "status", "open", "propose", "review"}:
        if positional or options:
            raise UsageError(f"参数过多: '{' '.join(args)}'", _usage(command))
        mapping = {"help": "secondbrain_help", "status": "secondbrain_status", "open": "secondbrain_open",
                   "propose": "secondbrain_propose", "review": "secondbrain_search"}
        if command == "propose":
            return "secondbrain_propose", {}
        if command == "review":
            # limit 取上限：候选记忆按 updated_at 排序，默认 20 条会被 active 挤出窗口。
            return "secondbrain_search", {"query": "", "include_candidates": True, "limit": 100}
        return mapping[command], {}
    if command in {"load", "search"}:
        query = " ".join(positional)
        if command == "search" and not query:
            raise UsageError("缺少参数: <query>", _usage(command))
        arguments: dict = {"query": query}
        if options.get("session"):
            arguments["session_id"] = options["session"]
        if "scope" in options:
            arguments["scope"] = options["scope"]
        if "limit" in options:
            try:
                arguments["limit"] = int(options["limit"])
            except ValueError:
                raise UsageError(f"参数 limit 必须是整数: '{options['limit']}'", _usage(command)) from None
        if command == "search":
            arguments["include_candidates"] = options.get("all") == "true"
        return ("secondbrain_load" if command == "load" else "secondbrain_search"), arguments
    if command in {"get", "approve", "reject", "archive"}:
        if len(positional) != 1:
            if not positional:
                raise UsageError("缺少参数: memory-id", _usage(command))
            raise UsageError(f"参数过多: '{' '.join(positional[1:])}'", _usage(command))
        return f"secondbrain_{command}", {"memory_id": positional[0]}
    if command == "check":
        if len(positional) > 1:
            raise UsageError(f"参数过多: '{' '.join(positional[1:])}'", _usage(command))
        mode = positional[0].lower() if positional else "all"
        return "secondbrain_check", {"check": mode}
    if command in {"conflicts", "duplicates"}:
        content = " ".join(positional)
        if not content:
            raise UsageError("缺少参数: <content>", _usage(command))
        return f"secondbrain_find_{command}", {"content": content}
    if command == "add":
        content = " ".join(positional)
        if not content:
            raise UsageError("缺少参数: <content>", _usage(command), "记忆内容直接写在命令末尾。")
        arguments = {
            "content": content,
            "scope": options.get("scope", "global"),
            "memory_type": options.get("type", "fact"),
        }
        if "target" in options:
            arguments["target_id"] = options["target"]
        if options.get("force") == "true":
            arguments["force"] = True
        return "secondbrain_add", arguments
    if command in {"delete", "remove"}:
        if not positional:
            raise UsageError("缺少参数: memory-id", _usage(command))
        if len(positional) > 1:
            raise UsageError(f"参数过多: '{' '.join(positional[1:])}'", _usage(command))
        arguments = {"memory_id": positional[0]}
        if options.get("confirm") == "true":
            arguments["confirm"] = True
        return "secondbrain_delete", arguments
    if command in {"link", "unlink"}:
        if not positional:
            raise UsageError("缺少参数: memory-id", _usage(command))
        if len(positional) > 1:
            raise UsageError(f"参数过多: '{' '.join(positional[1:])}'", _usage(command))
        if "scope" not in options:
            raise UsageError("缺少参数: --scope", _usage(command), "可选 project、session、agent。")
        if "target" not in options:
            raise UsageError("缺少参数: --target", _usage(command), "例如 --scope=project --target=<project-id>")
        return f"secondbrain_{command}", {
            "memory_id": positional[0],
            "scope": options["scope"],
            "target_id": options["target"],
        }
    raise UsageError(f"未知命令: '{command}'", "@SecondBrain <命令> [参数...]", f"可用命令: {COMMAND_LIST}")


def run_command(text: str) -> dict:
    """Execute one @SecondBrain line, returning a text-only MCP result (errors normalised)."""

    try:
        name, arguments = parse_command(text)
        return call_tool(name, arguments)
    except UsageError as exc:
        return text_message(exc.render())


def text_result(value: object, *, is_error: bool = False) -> dict:
    return {
        "content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False, indent=2)}],
        "isError": is_error,
    }


HELP_SECTIONS = [
    (
        "读取",
        [
            ("load [关键词]", "载入与当前任务相关的记忆"),
            ("search <关键词>", "搜索记忆；--all 含候选，--limit=N 限条数"),
            ("get <#编号>", "查看全文、元数据与审核记录"),
            ("review", "列出待审候选（只含候选项）"),
            ("status", "Core 状态与记忆计数"),
            ("check [模式]", "整库体检：all / conflicts / duplicates"),
            ("conflicts <内容>", "检查一段内容的冲突；可加 --scope="),
            ("duplicates <内容>", "检查一段内容的重复；可加 --scope="),
        ],
    ),
    (
        "写入",
        [
            ("propose", "新建候选记忆，走候选→审核流程"),
            ("add <内容>", "直接写入生效记忆；先查重，有冲突只警告"),
        ],
    ),
    (
        "生命周期",
        [
            ("approve <#编号>", "批准候选，转为生效"),
            ("reject <#编号>", "拒绝候选"),
            ("archive <#编号>", "归档记忆"),
            ("replace <#编号>", "用新内容替换旧记忆"),
        ],
    ),
    (
        "关联与删除",
        [
            ("link <#编号>", "加入项目/会话/Agent 范围；需 --scope= 与 --target="),
            ("unlink <#编号>", "解除上面加的关联；需 --scope= 与 --target="),
            ("delete <#编号>", "删除记忆；需 --confirm 确认，否则只询问"),
        ],
    ),
    (
        "其它",
        [
            ("open", "在浏览器打开网页版"),
            ("help", "显示本帮助"),
        ],
    ),
]

HELP_NOTES = [
    "范围:  global 全局 · project 项目 · session 会话 · agent 智能体",
    "选项:  --scope= --target= --type= --limit= --session= --all --force --confirm",
    "示例:  @SecondBrain search 部署 --all",
    "       @SecondBrain link #000003 --scope=project --target=project_x",
]


def _display_width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def _pad(text: str, width: int) -> str:
    return text + " " * max(0, width - _display_width(text))


def _format_help() -> str:
    rows = [row for _, items in HELP_SECTIONS for row in items]
    width = max(_display_width(usage) for usage, _ in rows) + 2
    lines = ["SecondBrain 命令帮助", "用法: @SecondBrain <命令> [参数...]    不带参数 = load", ""]
    for title, items in HELP_SECTIONS:
        lines.append(title)
        for usage, description in items:
            lines.append("  " + _pad(usage, width) + description)
        lines.append("")
    lines.extend(HELP_NOTES)
    return chr(10).join(lines).rstrip()


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
                    "session_id": {"type": "string", "description": "Current session id; linked memories become visible."},
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
                    "session_id": {"type": "string", "description": "Current session id; linked memories become visible."},
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
            "inputSchema": {
                "type": "object",
                "required": ["memory_id"],
                "properties": {
                    "memory_id": {"type": "string"},
                    "session_id": {"type": "string", "description": "Current session id; enables stale-context notices."},
                },
            },
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
            "name": "secondbrain_open",
            "description": "Start the local SecondBrain Core if it is not running, then open its Web UI in the default browser.",
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
        {
            "name": "secondbrain_check",
            "description": "Audit all active memories for conflicts, exact repetitions, and provenance pollution.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "check": {"type": "string", "enum": ["all", "conflicts", "duplicates"], "description": "Which review to return."},
                },
            },
        },
        {
            "name": "secondbrain_add",
            "description": "Add a memory directly as active, after checking for duplicates and conflicts.",
            "inputSchema": {
                "type": "object",
                "required": ["content"],
                "properties": {
                    "content": {"type": "string"},
                    "memory_type": {"type": "string"},
                    "scope": {"type": "string", "enum": ["global", "project", "session", "agent"]},
                    "target_id": {"type": "string"},
                    "force": {"type": "boolean", "description": "Write even when a warning is found."},
                },
            },
        },
        {
            "name": "secondbrain_delete",
            "description": "Delete a memory record permanently after explicit confirmation.",
            "inputSchema": {
                "type": "object",
                "required": ["memory_id"],
                "properties": {
                    "memory_id": {"type": "string"},
                    "confirm": {"type": "boolean"},
                },
            },
        },
        {
            "name": "secondbrain_link",
            "description": "Make an existing memory visible in one more scope without copying it.",
            "inputSchema": {
                "type": "object",
                "required": ["memory_id", "scope", "target_id"],
                "properties": {
                    "memory_id": {"type": "string"},
                    "scope": {"type": "string", "enum": ["project", "session", "agent"]},
                    "target_id": {"type": "string"},
                    "session_id": {"type": "string", "description": "Current session id; scopes unlink notices and cancels them on re-link."},
                },
            },
        },
        {
            "name": "secondbrain_unlink",
            "description": "Remove one scope link that was previously added.",
            "inputSchema": {
                "type": "object",
                "required": ["memory_id", "scope", "target_id"],
                "properties": {
                    "memory_id": {"type": "string"},
                    "scope": {"type": "string", "enum": ["project", "session", "agent"]},
                    "target_id": {"type": "string"},
                    "session_id": {"type": "string", "description": "Current session id; scopes unlink notices and cancels them on re-link."},
                },
            },
        },
    ]


def call_tool(name: str, arguments: dict) -> dict:
    arguments = _validate_arguments(name, arguments or {})
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
        old_id = _resolve_memory_id(arguments.get("old_memory_id"), "propose")
        if not old_id or not arguments.get("content"):
            raise ValueError("old_memory_id and content are required")
        payload = {key: value for key, value in arguments.items() if key != "old_memory_id" and value is not None}
        return text_result(core_request("POST", f"/api/memories/{old_id}/replace", payload))

    memory_id = arguments.get("memory_id")
    if name in {"secondbrain_get", "secondbrain_approve", "secondbrain_reject", "secondbrain_archive"}:
        memory_id = _resolve_memory_id(memory_id, TOOL_COMMANDS[name])
    if name == "secondbrain_get":
        if not memory_id:
            raise ValueError("memory_id is required")
        params = {}
        if arguments.get("session_id"):
            params["request_session_id"] = arguments["session_id"]
        suffix = "?" + urlencode(params) if params else ""
        return text_result(core_request("GET", f"/api/memories/{memory_id}{suffix}"))
    if name in {"secondbrain_approve", "secondbrain_reject", "secondbrain_archive"}:
        if not memory_id:
            raise ValueError("memory_id is required")
        action = name.removeprefix("secondbrain_")
        return text_result(core_request("POST", f"/api/memories/{memory_id}/{action}", {}))
    if name == "secondbrain_status":
        return text_result(core_request("GET", "/health"))
    if name == "secondbrain_open":
        return text_result(_open_ui())
    if name == "secondbrain_help":
        return text_message(_format_help(), is_error=False)
    if name == "secondbrain_check":
        report = core_request("POST", "/api/maintenance/audit", {})
        check = str(arguments.get("check", "all")).lower()
        if check == "conflicts":
            return text_result({"active_count": report.get("active_count", 0), "conflicts": report.get("conflicts", [])})
        if check == "duplicates":
            return text_result({"active_count": report.get("active_count", 0), "duplicates": report.get("duplicates", [])})
        return text_result(report)
    if name in {"secondbrain_find_duplicates", "secondbrain_find_conflicts"}:
        path = "/api/memories/duplicates" if name.endswith("duplicates") else "/api/memories/conflicts"
        params = {"content": arguments.get("content", "")}
        if arguments.get("scope"):
            params["scope"] = arguments["scope"]
        result = core_request("GET", path + "?" + urlencode(params))
        if name == "secondbrain_find_duplicates":
            # duplicates 端点只返回正文完全相同的条目，补上 kind/similarity 供渲染层统一处理。
            for item in result.get("items", []) if isinstance(result, dict) else []:
                item.setdefault("kind", "duplicate")
                item["similarity"] = item.get("similarity", 1.0)
        return text_result(result)
    if name == "secondbrain_add":
        payload = {
            "content": arguments["content"],
            "memory_type": arguments.get("memory_type", "fact"),
            "scope": arguments.get("scope", "global"),
            "target_id": arguments.get("target_id"),
            "force": bool(arguments.get("force")),
        }
        return text_result(_call_memory_command("POST", "/api/memories/add", payload, "add"))
    if name == "secondbrain_delete":
        memory_id = _resolve_memory_id(arguments.get("memory_id"), "delete")
        if not arguments.get("confirm"):
            record = _call_memory_command("GET", f"/api/memories/{memory_id}", None, "delete")
            return text_message(_confirm_delete(record), is_error=False)
        return text_result(_call_memory_command("DELETE", f"/api/memories/{memory_id}", None, "delete"))
    if name in {"secondbrain_link", "secondbrain_unlink"}:
        command = TOOL_COMMANDS[name]
        memory_id = _resolve_memory_id(arguments.get("memory_id"), command)
        payload = {"scope": arguments["scope"], "target_id": arguments["target_id"]}
        if arguments.get("session_id"):
            payload["session_id"] = arguments["session_id"]
        return text_result(_call_memory_command("POST", f"/api/memories/{memory_id}/{command}", payload, command))
    raise UsageError(f"未知命令: '{name}'")


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
        except UsageError as exc:
            result = text_message(exc.render())
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
