#!/usr/bin/env python3
"""Portable standard-library client for the local SecondBrain Core API."""

from __future__ import annotations

import argparse
import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_URL = "http://127.0.0.1:8765"


def request(base_url: str, method: str, path: str, payload: dict | None = None) -> object:
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request_obj = Request(base_url.rstrip("/") + path, data=body, headers=headers, method=method)
    try:
        with urlopen(request_obj, timeout=10) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else None
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(raw)
        except json.JSONDecodeError:
            detail = raw
        raise RuntimeError(f"SecondBrain Core returned HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"SecondBrain Core is unavailable: {exc.reason}") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="secondbrain-client")
    parser.add_argument("--url", default=os.environ.get("SECONDBRAIN_URL", DEFAULT_URL))
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("health")

    search = sub.add_parser("search")
    search.add_argument("query", nargs="?", default="")
    search.add_argument("--scope")
    search.add_argument("--project-id")
    search.add_argument("--agent-id")
    search.add_argument("--include-candidates", action="store_true")
    search.add_argument("--limit", type=int, default=20)

    get = sub.add_parser("get")
    get.add_argument("memory_id")

    propose = sub.add_parser("propose")
    propose.add_argument("--content", required=True)
    propose.add_argument("--memory-type", required=True)
    propose.add_argument("--scope", required=True)
    propose.add_argument("--confidence", type=float, default=0.5)
    propose.add_argument("--agent-id")
    propose.add_argument("--project-id")
    propose.add_argument("--source-session-id")
    propose.add_argument("--source-reference")
    propose.add_argument("--tag", action="append", default=[])

    for name in ("approve", "reject", "archive"):
        action = sub.add_parser(name)
        action.add_argument("memory_id")

    update = sub.add_parser("update")
    update.add_argument("memory_id")
    update.add_argument("--content")
    update.add_argument("--confidence", type=float)
    update.add_argument("--expires-at")
    update.add_argument("--source-reference")
    update.add_argument("--tag", action="append")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "health":
            result = request(args.url, "GET", "/health")
        elif args.command == "search":
            query = {
                "q": args.query,
                "limit": args.limit,
                "include_candidates": str(args.include_candidates).lower(),
            }
            for key in ("scope", "project_id", "agent_id"):
                value = getattr(args, key)
                if value:
                    query[key] = value
            result = request(args.url, "GET", "/api/memories/search?" + urlencode(query))
        elif args.command == "get":
            result = request(args.url, "GET", f"/api/memories/{args.memory_id}")
        elif args.command == "propose":
            result = request(
                args.url,
                "POST",
                "/api/memories",
                {
                    "content": args.content,
                    "memory_type": args.memory_type,
                    "scope": args.scope,
                    "status": "candidate",
                    "confidence": args.confidence,
                    "agent_id": args.agent_id,
                    "project_id": args.project_id,
                    "source_session_id": args.source_session_id,
                    "source_reference": args.source_reference,
                    "tags": args.tag,
                },
            )
        elif args.command in {"approve", "reject", "archive"}:
            result = request(args.url, "POST", f"/api/memories/{args.memory_id}/{args.command}", {})
        elif args.command == "update":
            payload = {}
            for key in ("content", "confidence", "expires_at", "source_reference", "tag"):
                value = getattr(args, key)
                if value is not None:
                    payload["tags" if key == "tag" else key] = value
            result = request(args.url, "PATCH", f"/api/memories/{args.memory_id}", payload)
        else:
            raise RuntimeError(f"unsupported command: {args.command}")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
