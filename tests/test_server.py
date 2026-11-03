import json
import threading
from http.client import HTTPConnection
from pathlib import Path
from http.server import ThreadingHTTPServer

from secondbrain_core.server import make_handler
from secondbrain_core.service import SecondBrainService


def test_http_health_and_memory_search(tmp_path: Path) -> None:
    service = SecondBrainService(tmp_path / "memory")
    service.create_agent("HTTP Agent", agent_id="agent_http")
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(service))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = HTTPConnection("127.0.0.1", server.server_port)
    try:
        connection.request("GET", "/")
        response = connection.getresponse()
        assert response.status == 200
        assert b"SecondBrain" in response.read()

        connection.request("GET", "/health")
        response = connection.getresponse()
        assert response.status == 200
        assert json.loads(response.read())["ok"] is True

        payload = json.dumps(
            {
                "content": "HTTP memory",
                "memory_type": "fact",
                "scope": "global",
                "status": "active",
                "agent_id": "agent_http",
            }
        )
        connection.request(
            "POST",
            "/api/memories",
            body=payload,
            headers={"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        response_body = response.read()
        assert response.status == 201, response_body

        connection.request("GET", "/api/memories/search?q=HTTP")
        response = connection.getresponse()
        body = json.loads(response.read())
        assert response.status == 200
        assert len(body["items"]) == 1

        connection.request("GET", "/api/agents")
        response = connection.getresponse()
        assert response.status == 200
        assert json.loads(response.read())["items"][0]["agent_id"] == "agent_http"
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        service.close()
