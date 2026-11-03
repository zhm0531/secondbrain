from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser

from .service import SecondBrainService


def _json(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="secondbrain")
    parser.add_argument("--root", default="memory", help="SecondBrain data directory")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("rebuild", help="rebuild the SQLite index from Markdown")
    sub.add_parser("audit", help="audit conflicts and memory pollution")
    sub.add_parser("help", help="show SecondBrain commands")
    open_command = sub.add_parser("open", help="start Core if needed and open the Web UI")
    open_command.add_argument("--host", default="127.0.0.1")
    open_command.add_argument("--port", type=int, default=8765)

    create_agent = sub.add_parser("create-agent")
    create_agent.add_argument("--display-name", required=True)
    create_agent.add_argument("--agent-id")
    create_agent.add_argument("--adapter-type")

    create_project = sub.add_parser("create-project")
    create_project.add_argument("--name", required=True)
    create_project.add_argument("--project-id")
    create_project.add_argument("--description", default="")
    create_project.add_argument("--root-path")

    grant = sub.add_parser("grant-project-access")
    grant.add_argument("--agent-id", required=True)
    grant.add_argument("--project-id", required=True)
    revoke = sub.add_parser("revoke-project-access")
    revoke.add_argument("--agent-id", required=True)
    revoke.add_argument("--project-id", required=True)

    create_session = sub.add_parser("create-session")
    create_session.add_argument("--agent-id", required=True)
    create_session.add_argument("--title", required=True)
    create_session.add_argument("--project-id")
    create_session.add_argument("--summary", default="")

    create_memory = sub.add_parser("add-memory")
    create_memory.add_argument("--content", required=True)
    create_memory.add_argument("--memory-type", required=True)
    create_memory.add_argument("--scope", required=True)
    create_memory.add_argument("--status", default="candidate")
    create_memory.add_argument("--confidence", type=float, default=0.5)
    create_memory.add_argument("--agent-id")
    create_memory.add_argument("--project-id")
    create_memory.add_argument("--source-session-id")
    create_memory.add_argument("--tag", action="append", default=[])

    search = sub.add_parser("search")
    search.add_argument("query", nargs="?", default="")
    search.add_argument("--scope")
    search.add_argument("--project-id")
    search.add_argument("--agent-id")
    search.add_argument("--include-candidates", action="store_true")
    search.add_argument("--limit", type=int, default=20)

    get = sub.add_parser("get", help="get a memory by UUID or number")
    get.add_argument("identifier")

    for name in ("approve", "reject", "archive"):
        command = sub.add_parser(name)
        command.add_argument("memory_id")

    update = sub.add_parser("update")
    update.add_argument("memory_id")
    update.add_argument("--content")
    update.add_argument("--confidence", type=float)
    update.add_argument("--tag", action="append")
    update.add_argument("--expires-at")
    update.add_argument("--source-reference")
    replace = sub.add_parser("replace")
    replace.add_argument("old_memory_id")
    replace.add_argument("--content", required=True)
    replace.add_argument("--confidence", type=float, default=0.9)
    replace.add_argument("--agent-id")
    replace.add_argument("--project-id")
    replace.add_argument("--source-session-id")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    service = SecondBrainService(Path(args.root))
    try:
        if args.command == "open":
            url = f"http://{args.host}:{args.port}/"
            health_url = f"http://{args.host}:{args.port}/health"
            running = False
            try:
                with urllib.request.urlopen(health_url, timeout=1) as response:
                    running = response.status == 200
            except Exception:
                running = False
            if not running:
                creation_flags = 0
                if os.name == "nt":
                    creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
                subprocess.Popen(
                    [sys.executable, "-m", "secondbrain_core.server", "--root", str(Path(args.root).resolve()), "--host", args.host, "--port", str(args.port)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=creation_flags,
                    close_fds=True,
                )
                for _ in range(30):
                    time.sleep(0.1)
                    try:
                        with urllib.request.urlopen(health_url, timeout=1) as response:
                            if response.status == 200:
                                break
                    except Exception:
                        pass
            webbrowser.open(url)
            print(f"SecondBrain Web UI: {url}")
            return 0
        if args.command == "help":
            parser.print_help()
            print("\nCommon commands: @SecondBrain, search, propose, review, approve, reject, status")
            return 0
        if args.command == "audit":
            _json(service.audit_memories())
            return 0
        if args.command == "rebuild":
            _json(service.rebuild_index())
        elif args.command == "create-agent":
            _json(
                service.create_agent(
                    args.display_name,
                    agent_id=args.agent_id,
                    adapter_type=args.adapter_type,
                )
            )
        elif args.command == "create-project":
            _json(
                service.create_project(
                    args.name,
                    project_id=args.project_id,
                    description=args.description,
                    root_path=args.root_path,
                )
            )
        elif args.command == "grant-project-access":
            _json(service.grant_project_access(args.agent_id, args.project_id))
        elif args.command == "revoke-project-access":
            service.revoke_project_access(args.agent_id, args.project_id)
            _json({"revoked": True, "agent_id": args.agent_id, "project_id": args.project_id})
        elif args.command == "create-session":
            _json(
                service.create_session(
                    agent_id=args.agent_id,
                    title=args.title,
                    project_id=args.project_id,
                    summary=args.summary,
                )
            )
        elif args.command == "add-memory":
            _json(
                service.create_memory(
                    content=args.content,
                    memory_type=args.memory_type,
                    scope=args.scope,
                    status=args.status,
                    confidence=args.confidence,
                    agent_id=args.agent_id,
                    project_id=args.project_id,
                    source_session_id=args.source_session_id,
                    tags=args.tag,
                )
            )
        elif args.command == "search":
            statuses = ("active", "candidate") if args.include_candidates else ("active",)
            _json(
                service.search_memories(
                    args.query,
                    scope=args.scope,
                    project_id=args.project_id,
                    agent_id=args.agent_id,
                    statuses=statuses,
                    limit=args.limit,
                )
            )
        elif args.command == "get":
            record = service.get_memory(args.identifier)
            if record is None:
                raise KeyError(f"memory not found: {args.identifier}")
            _json(record)
        elif args.command == "approve":
            _json(service.approve_memory(args.memory_id))
        elif args.command == "reject":
            _json(service.reject_memory(args.memory_id))
        elif args.command == "archive":
            _json(service.archive_memory(args.memory_id))
        elif args.command == "update":
            _json(
                service.update_memory(
                    args.memory_id,
                    content=args.content,
                    confidence=args.confidence,
                    tags=args.tag,
                    expires_at=args.expires_at,
                    source_reference=args.source_reference,
                )
            )
        elif args.command == "replace":
            _json(
                service.replace_memory(
                    args.old_memory_id,
                    content=args.content,
                    confidence=args.confidence,
                    agent_id=args.agent_id,
                    project_id=args.project_id,
                    source_session_id=args.source_session_id,
                )
            )
        return 0
    finally:
        service.close()


if __name__ == "__main__":
    raise SystemExit(main())
