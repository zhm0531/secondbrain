import json
import os
import subprocess
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

from secondbrain_core.server import make_handler
from secondbrain_core.service import SecondBrainService


def test_mcp_stdio_server(tmp_path: Path) -> None:
    service = SecondBrainService(tmp_path / "memory")
    service.create_agent("MCP Agent", agent_id="agent_mcp")
    core = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(service))
    thread = threading.Thread(target=core.serve_forever, daemon=True)
    thread.start()
    script = (
        Path(__file__).parents[1]
        / "integrations"
        / "deepseek-harness"
        / "dsh-secondbrain-bridge"
        / "scripts"
        / "secondbrain_mcp_server.py"
    )
    environment = os.environ.copy()
    environment["SECONDBRAIN_URL"] = f"http://127.0.0.1:{core.server_port}"
    process = subprocess.Popen(
        [sys.executable, str(script)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
    )

    def call(message: dict) -> dict:
        assert process.stdin and process.stdout
        process.stdin.write(json.dumps(message) + "\n")
        process.stdin.flush()
        line = process.stdout.readline()
        assert line
        return json.loads(line)

    try:
        initialized = call({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        assert initialized["result"]["serverInfo"]["name"] == "secondbrain"
        tools = call({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        assert any(tool["name"] == "secondbrain_load" for tool in tools["result"]["tools"])
        proposed = call(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "secondbrain_propose",
                    "arguments": {
                        "content": "MCP memory",
                        "memory_type": "fact",
                        "scope": "global",
                        "agent_id": "agent_mcp",
                    },
                },
            }
        )
        assert proposed["result"]["isError"] is False
        result = json.loads(proposed["result"]["content"][0]["text"])
        assert result["status"] == "candidate"
    finally:
        if process.stdin:
            process.stdin.close()
        process.terminate()
        process.wait(timeout=5)
        core.shutdown()
        core.server_close()
        service.close()
