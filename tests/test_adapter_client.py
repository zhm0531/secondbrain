import json
import subprocess
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

from secondbrain_core.server import make_handler
from secondbrain_core.service import SecondBrainService


def test_portable_adapter_client(tmp_path: Path) -> None:
    service = SecondBrainService(tmp_path / "memory")
    service.create_agent("Adapter Agent", agent_id="agent_adapter")
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(service))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    script = Path(__file__).parents[1] / "skills" / "secondbrain" / "scripts" / "secondbrain_client.py"
    base_url = f"http://127.0.0.1:{server.server_port}"
    try:
        result = subprocess.run(
            [
                sys.executable,
                str(script),
                "--url",
                base_url,
                "propose",
                "--content",
                "Adapter memory",
                "--memory-type",
                "fact",
                "--scope",
                "global",
                "--agent-id",
                "agent_adapter",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        created = json.loads(result.stdout)
        assert created["status"] == "candidate"

        result = subprocess.run(
            [sys.executable, str(script), "--url", base_url, "search", "Adapter", "--include-candidates"],
            check=True,
            capture_output=True,
            text=True,
        )
        assert len(json.loads(result.stdout)["items"]) == 1
    finally:
        server.shutdown()
        server.server_close()
        service.close()
