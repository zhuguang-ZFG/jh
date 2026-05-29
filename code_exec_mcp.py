import json, sys, os, tempfile, subprocess, traceback
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    pass

MAX_TIMEOUT = 30
MAX_OUTPUT = 50000

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _send(self, rid, result):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps({"jsonrpc": "2.0", "result": result, "id": rid}, ensure_ascii=False).encode())

    def _error(self, rid, msg):
        self._send(rid, {"content": [{"type": "text", "text": f"Error: {msg}"}]})

    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length", 0))
            b = json.loads(self.rfile.read(n)) if n else {}
        except Exception:
            return
        m = b.get("method", "")
        p = b.get("params", {})
        rid = b.get("id", 0)

        if m == "initialize":
            self._send(rid, {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "vps-code-exec", "version": "1.0.0"}})
            return

        if m == "tools/list":
            t1 = {"name": "run_python", "description": "Execute Python code in sandbox", "inputSchema": {"type": "object", "properties": {"code": {"type": "string"}, "timeout": {"type": "integer"}}}}
            t2 = {"name": "run_shell", "description": "Execute a shell command", "inputSchema": {"type": "object", "properties": {"command": {"type": "string"}, "timeout": {"type": "integer"}}}}
            t3 = {"name": "lint", "description": "Run ruff check on Python code", "inputSchema": {"type": "object", "properties": {"code": {"type": "string"}}}}
            t4 = {"name": "format", "description": "Format Python code with ruff", "inputSchema": {"type": "object", "properties": {"code": {"type": "string"}}}}
            self._send(rid, {"tools": [t1, t2, t3, t4]})
            return

        if m == "tools/call":
            a = p.get("arguments", {})
            nm = p.get("name", "")
            try:
                if nm == "run_python":
                    code = a.get("code", "")
                    if not code.strip():
                        self._error(rid, "No code provided")
                        return
                    timeout = min(max(a.get("timeout", 30), 5), MAX_TIMEOUT)
                    with tempfile.NamedTemporaryFile(suffix='.py', mode='w', delete=False) as f:
                        f.write(code)
                        tmp = f.name
                    try:
                        r = subprocess.run(['python3.12', tmp], capture_output=True, text=True, timeout=timeout, cwd="/tmp")
                        out = r.stdout[:MAX_OUTPUT] + r.stderr[:MAX_OUTPUT]
                        if r.returncode != 0:
                            out = f"[exit code: {r.returncode}]\n{out}"
                        self._send(rid, {"content": [{"type": "text", "text": out or "(no output)"}]})
                    except subprocess.TimeoutExpired:
                        self._send(rid, {"content": [{"type": "text", "text": f"Timeout after {timeout}s"}]})
                    finally:
                        os.unlink(tmp)

                elif nm == "run_shell":
                    cmd = a.get("command", "")
                    if not cmd.strip():
                        self._error(rid, "No command provided")
                        return
                    timeout = min(max(a.get("timeout", 30), 5), MAX_TIMEOUT)
                    try:
                        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout, cwd="/tmp", executable="/bin/bash")
                        out = r.stdout[:MAX_OUTPUT] + r.stderr[:MAX_OUTPUT]
                        if r.returncode != 0:
                            out = f"[exit code: {r.returncode}]\n{out}"
                        self._send(rid, {"content": [{"type": "text", "text": out or "(no output)"}]})
                    except subprocess.TimeoutExpired:
                        self._send(rid, {"content": [{"type": "text", "text": f"Timeout after {timeout}s"}]})

                elif nm == "lint":
                    code = a.get("code", "")
                    if not code.strip():
                        self._error(rid, "No code provided")
                        return
                    with tempfile.NamedTemporaryFile(suffix='.py', mode='w', delete=False) as f:
                        f.write(code)
                        tmp = f.name
                    try:
                        r = subprocess.run(['ruff', 'check', tmp], capture_output=True, text=True, timeout=15)
                        self._send(rid, {"content": [{"type": "text", "text": r.stdout or r.stderr or "No issues found"}]})
                    finally:
                        os.unlink(tmp)

                elif nm == "format":
                    code = a.get("code", "")
                    if not code.strip():
                        self._error(rid, "No code provided")
                        return
                    with tempfile.NamedTemporaryFile(suffix='.py', mode='w', delete=False) as f:
                        f.write(code)
                        tmp = f.name
                    try:
                        r = subprocess.run(['ruff', 'format', tmp], capture_output=True, text=True, timeout=15)
                        formatted = open(tmp).read()
                        self._send(rid, {"content": [{"type": "text", "text": formatted}]})
                    finally:
                        os.unlink(tmp)

                else:
                    self._error(rid, f"Unknown tool: {nm}")
            except Exception as e:
                self._error(rid, f"{e}\n{traceback.format_exc()[-500:]}")
            return

        self._error(rid, f"Unknown method: {m}")

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8770
    print(f"Code Exec MCP on port {port}")
    ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever()
