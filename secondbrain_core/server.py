from __future__ import annotations

import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .service import MemoryCommandError, SecondBrainService


# SQLite connection 以 check_same_thread=False 共享；ThreadingHTTPServer 并发进入时
# 会出现 "bad parameter or other API misuse" / "tuple index out of range"。
# 用一把全局锁把请求串行化：单用户本地服务，代价可忽略。
_REQUEST_LOCK = threading.Lock()

WEB_ROOT = Path(__file__).parent / "web"
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "application/javascript; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
}


def _json_body(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", "0"))
    raw = handler.rfile.read(length) if length else b"{}"
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("JSON body must be an object")
    return value


def _path_id(path: str, prefix: str) -> str | None:
    if not path.startswith(prefix):
        return None
    value = path[len(prefix) :].strip("/")
    return value or None


def make_handler(service: SecondBrainService):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args) -> None:
            return

        def send_json(self, status: int, payload: object) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def send_static(self, filename: str, content_type: str) -> None:
            path = WEB_ROOT / filename
            if not path.exists():
                self.send_json(404, {"error": "static file not found"})
                return
            body = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def handle_error(self, exc: Exception) -> None:
            if isinstance(exc, KeyError):
                self.send_json(404, {"error": str(exc)})
            elif isinstance(exc, MemoryCommandError):
                self.send_json(400, {"error": str(exc), "code": exc.code})
            elif isinstance(exc, (ValueError, json.JSONDecodeError)):
                self.send_json(400, {"error": str(exc)})
            else:
                self.send_json(500, {"error": str(exc)})

        def do_GET(self) -> None:
            with _REQUEST_LOCK:
                self._do_GET()

        def _do_GET(self) -> None:
            try:
                parsed = urlparse(self.path)
                if parsed.path == "/health":
                    self.send_json(200, {"ok": True, "service": "SecondBrain Core"})
                    return
                static_file = STATIC_FILES.get(parsed.path)
                if static_file:
                    self.send_static(*static_file)
                    return
                params = parse_qs(parsed.query)
                if parsed.path == "/api/agents":
                    self.send_json(200, {"items": service.list_agents()})
                    return
                if parsed.path == "/api/projects":
                    self.send_json(200, {"items": service.list_projects()})
                    return
                if parsed.path == "/api/projects/access":
                    self.send_json(200, {"items": service.list_project_access(params.get("project_id", [None])[0])})
                    return
                if parsed.path == "/api/sessions":
                    self.send_json(200, {"items": service.list_sessions(int(params.get("limit", ["100"])[0]))})
                    return
                if parsed.path == "/api/projects/access":
                    self.send_json(200, service.grant_project_access(payload["agent_id"], payload["project_id"]))
                    return
                if parsed.path == "/api/memories/search":
                    include_candidates = params.get("include_candidates", ["false"])[0].lower() == "true"
                    statuses = ("active", "candidate") if include_candidates else ("active",)
                    result = service.search_memories(
                        params.get("q", [""])[0],
                        scope=params.get("scope", [None])[0],
                        project_id=params.get("project_id", [None])[0],
                        agent_id=params.get("agent_id", [None])[0],
                        statuses=statuses,
                        limit=int(params.get("limit", ["50"])[0]),
                        session_id=params.get("request_session_id", [None])[0],
                        include_linked=True,
                    )
                    request_agent = params.get("request_agent_id", [None])[0]
                    request_project = params.get("request_project_id", [None])[0]
                    request_session = params.get("request_session_id", [None])[0]
                    if request_agent or request_project or request_session:
                        result = [item for item in result if service.can_access_memory(item, agent_id=request_agent, project_id=request_project, session_id=request_session)]
                    self.send_json(200, {"items": result})
                    return
                if parsed.path == "/api/memories/duplicates":
                    content = params.get("content", [""])[0]
                    self.send_json(200, {"items": service.find_similar_memories(content, scope=params.get("scope", [None])[0])})
                    return
                if parsed.path == "/api/memories/conflicts":
                    self.send_json(200, {"items": service.find_conflicts(content=params.get("content", [""])[0], scope=params.get("scope", [None])[0], memory_type=params.get("memory_type", [None])[0])})
                    return
                if parsed.path == "/api/reviews/conflicts":
                    self.send_json(200, {"items": service.review_conflicts()})
                    return
                memory_id = _path_id(parsed.path, "/api/memories/")
                if memory_id:
                    if memory_id.endswith("/history"):
                        self.send_json(200, {"items": service.memory_history(memory_id.removesuffix("/history"))})
                        return
                    result = service.get_memory_for_context(
                        memory_id,
                        agent_id=params.get("request_agent_id", [None])[0],
                        project_id=params.get("request_project_id", [None])[0],
                        session_id=params.get("request_session_id", [None])[0],
                        confirmed=params.get("confirmed", ["false"])[0].lower() == "true",
                    )
                    if result is None:
                        self.send_json(404, {"error": "memory not found"})
                    else:
                        self.send_json(200, result)
                    return
                self.send_json(404, {"error": "route not found"})
            except Exception as exc:
                self.handle_error(exc)

        def do_POST(self) -> None:
            with _REQUEST_LOCK:
                self._do_POST()

        def _do_POST(self) -> None:
            try:
                parsed = urlparse(self.path)
                payload = _json_body(self)
                if parsed.path == "/api/index/rebuild":
                    self.send_json(200, service.rebuild_index())
                    return
                if parsed.path == "/api/maintenance/repair-numbers":
                    self.send_json(200, service.repair_memory_numbers())
                    return
                if parsed.path == "/api/maintenance/expire":
                    self.send_json(200, {"archived_memory_ids": service.expire_memories()})
                    return
                if parsed.path == "/api/maintenance/audit":
                    self.send_json(200, service.audit_memories())
                    return
                if parsed.path == "/api/sessions":
                    self.send_json(201, service.create_session(**payload))
                    return
                if parsed.path == "/api/memories/add":
                    self.send_json(201, service.add_memory(**payload))
                    return
                if parsed.path == "/api/memories":
                    memory = service.create_memory(**payload)
                    conflicts = service.find_conflicts(content=memory["content"], scope=memory["scope"], memory_type=memory["memory_type"])
                    self.send_json(201, {**memory, "conflicts": conflicts, "requires_confirmation": bool(conflicts)})
                    return
                if parsed.path == "/api/reviews/resolve-all":
                    action = payload.get("action")
                    self.send_json(200, {"action": action, "items": service.resolve_all_conflicts(action)})
                    return
                if parsed.path == "/api/reviews/resolve":
                    self.send_json(200, service.resolve_conflict(**payload))
                    return
                memory_id = _path_id(parsed.path, "/api/memories/")
                if memory_id and memory_id.endswith("/replace"):
                    self.send_json(200, service.replace_memory(memory_id.removesuffix("/replace"), **payload))
                    return
                if memory_id and parsed.path.endswith("/approve"):
                    self.send_json(200, service.approve_memory(memory_id.removesuffix("/approve")))
                    return
                if memory_id and parsed.path.endswith("/reject"):
                    self.send_json(200, service.reject_memory(memory_id.removesuffix("/reject")))
                    return
                if memory_id and parsed.path.endswith("/archive"):
                    self.send_json(200, service.archive_memory(memory_id.removesuffix("/archive")))
                    return
                if memory_id and parsed.path.endswith("/link"):
                    self.send_json(200, service.link_memory(
                        memory_id.removesuffix("/link"),
                        scope=str(payload.get("scope", "")),
                        target_id=str(payload.get("target_id") or ""),
                        session_id=payload.get("session_id"),
                    ))
                    return
                if memory_id and parsed.path.endswith("/unlink"):
                    self.send_json(200, service.unlink_memory(
                        memory_id.removesuffix("/unlink"),
                        scope=str(payload.get("scope", "")),
                        target_id=str(payload.get("target_id") or ""),
                        session_id=payload.get("session_id"),
                    ))
                    return
                self.send_json(404, {"error": "route not found"})
            except Exception as exc:
                self.handle_error(exc)

        def do_PATCH(self) -> None:
            with _REQUEST_LOCK:
                self._do_PATCH()

        def _do_PATCH(self) -> None:
            try:
                parsed = urlparse(self.path)
                project_id = _path_id(parsed.path, "/api/projects/")
                if project_id:
                    self.send_json(200, service.update_project(project_id, **_json_body(self)))
                    return
                session_id = _path_id(parsed.path, "/api/sessions/")
                if session_id:
                    self.send_json(200, service.update_session(session_id, **_json_body(self)))
                    return
                memory_id = _path_id(parsed.path, "/api/memories/")
                if not memory_id or "/" in memory_id:
                    self.send_json(404, {"error": "route not found"})
                    return
                self.send_json(200, service.update_memory(memory_id, **_json_body(self)))
            except Exception as exc:
                self.handle_error(exc)

        def do_DELETE(self) -> None:
            with _REQUEST_LOCK:
                self._do_DELETE()

        def _do_DELETE(self) -> None:
            try:
                parsed = urlparse(self.path)
                if parsed.path == "/api/projects/access":
                    params = parse_qs(parsed.query)
                    service.revoke_project_access(params["agent_id"][0], params["project_id"][0])
                    self.send_json(200, {"revoked": True})
                    return
                memory_id = _path_id(parsed.path, "/api/memories/")
                if memory_id and "/" not in memory_id:
                    self.send_json(200, service.delete_memory(memory_id))
                    return
                self.send_json(404, {"error": "route not found"})
            except Exception as exc:
                self.handle_error(exc)

    return Handler


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="secondbrain-server")
    parser.add_argument("--root", default="memory")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    service = SecondBrainService(Path(args.root))
    server = ThreadingHTTPServer((args.host, args.port), make_handler(service))
    try:
        print(f"SecondBrain Core listening on http://{args.host}:{args.port}")
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
        service.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
