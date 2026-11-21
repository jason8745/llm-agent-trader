"""Instant-start MCP front for the trader server. Standard library only, Python 3.9+.

Claude Code gives an MCP server 30 seconds to start, but the first `uvx` install of pandas,
numpy and yfinance takes minutes. This front answers `initialize` and `tools/list` at once
from mcp_manifest.json, starts the real server in the background, and forwards each
`tools/call` once the real server is ready. Tool calls have no 30-second limit, so the
first call simply waits for the install.

    uv run --no-project --managed-python --python 3.12 src/trader/mcp_launcher.py
"""

import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import workspace  # noqa: E402  (stdlib-only module shared with the real server)

# Answered here without waiting for the real server, so the first exchange is instant.
LOCAL = {"get_research_guide": workspace.guide, "setup_workspace": workspace.setup}


def child_command():
    override = os.environ.get("TRADER_MCP_CHILD")
    if override:
        return json.loads(override)
    # uv exports its own path as UV; Claude Desktop's bundled uv is not on PATH.
    uv = os.environ.get("UV") or shutil.which("uv") or "uv"
    root = str(HERE.parents[1])
    return [uv, "tool", "run", "--managed-python", "--from", root, "llm-agent-trader", "mcp"]


class Child:
    """The real MCP server as a subprocess, spoken to over newline-delimited JSON-RPC."""

    def __init__(self, cmd, protocol_version):
        self.proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=sys.stderr,
            text=True,
            encoding="utf-8",
        )
        self.lock = threading.Lock()
        self.pending = {}
        self.next_id = 0
        threading.Thread(target=self._read, daemon=True).start()
        self.init = self.request(
            "initialize",
            {
                "protocolVersion": protocol_version,
                "capabilities": {},
                "clientInfo": {"name": "llm-agent-trader-launcher", "version": "1"},
            },
        )
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def _send(self, msg):
        with self.lock:
            self.proc.stdin.write(json.dumps(msg) + "\n")
            self.proc.stdin.flush()

    def _read(self):
        for line in self.proc.stdout:
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            slot = self.pending.pop(msg.get("id"), None) if "method" not in msg else None
            if slot is not None:
                slot[1] = msg
                slot[0].set()
        for event, _ in list(self.pending.values()):
            event.set()

    def request(self, method, params):
        with self.lock:
            self.next_id += 1
            rid = self.next_id
        slot = [threading.Event(), None]
        self.pending[rid] = slot
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        slot[0].wait()
        if slot[1] is None:
            raise RuntimeError(f"the trader server exited (code {self.proc.poll()})")
        if "error" in slot[1]:
            raise RuntimeError(slot[1]["error"].get("message", "unknown error"))
        return slot[1]["result"]

    def alive(self):
        return self.proc.poll() is None


class Front:
    def __init__(self):
        self.out_lock = threading.Lock()
        self.child_lock = threading.Lock()
        self.child = None
        self.child_error = None
        self.protocol_version = "2025-06-18"
        self.manifest = json.loads((HERE / "mcp_manifest.json").read_text(encoding="utf-8"))

    def write(self, msg):
        with self.out_lock:
            sys.stdout.write(json.dumps(msg) + "\n")
            sys.stdout.flush()

    def ensure_child(self):
        with self.child_lock:
            if self.child is None or not self.child.alive():
                try:
                    self.child = Child(child_command(), self.protocol_version)
                    self.child_error = None
                except (OSError, RuntimeError) as e:
                    self.child, self.child_error = None, str(e)
            return self.child

    def call_tool(self, rid, params):
        child = self.ensure_child()
        try:
            if child is None:
                raise RuntimeError(self.child_error)
            result = child.request("tools/call", params)
        except RuntimeError as e:
            result = {
                "content": [{"type": "text", "text": f"trader 伺服器無法啟動：{e}"}],
                "isError": True,
            }
        self.write({"jsonrpc": "2.0", "id": rid, "result": result})

    def handle(self, msg):
        method, rid = msg.get("method"), msg.get("id")
        if method is None or rid is None:
            return
        if method == "initialize":
            self.protocol_version = msg.get("params", {}).get(
                "protocolVersion", self.protocol_version
            )
            threading.Thread(target=self.ensure_child, daemon=True).start()
            result = {
                "protocolVersion": self.protocol_version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": self.manifest["serverInfo"],
                "instructions": self.manifest["instructions"],
            }
        elif method == "tools/list":
            result = {"tools": self.manifest["tools"]}
        elif method == "ping":
            result = {}
        elif method == "tools/call" and msg.get("params", {}).get("name") in LOCAL:
            text = LOCAL[msg["params"]["name"]]()
            result = {
                "content": [{"type": "text", "text": text}],
                "structuredContent": {"result": text},
                "isError": False,
            }
        elif method == "tools/call":
            threading.Thread(
                target=self.call_tool, args=(rid, msg.get("params", {})), daemon=True
            ).start()
            return
        else:
            self.write(
                {
                    "jsonrpc": "2.0",
                    "id": rid,
                    "error": {"code": -32601, "message": f"method not found: {method}"},
                }
            )
            return
        self.write({"jsonrpc": "2.0", "id": rid, "result": result})

    def serve(self):
        for line in sys.stdin:
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if isinstance(msg, dict):
                self.handle(msg)
        if self.child is not None:
            self.child.proc.stdin.close()


if __name__ == "__main__":
    Front().serve()
