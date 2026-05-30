#!/usr/bin/env python3
"""MCP bridge — exposes VPS AI Router tools (Zhihu search, AI stats) via stdio."""
import json, sys, urllib.request, urllib.error

VPS_URL = "http://119.45.204.198:8769"

def call_router(method, params=None):
    body = json.dumps({"jsonrpc": "2.0", "method": method, "params": params or {}, "id": 1}).encode()
    req = urllib.request.Request(VPS_URL, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode()).get("result", {})

def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except:
            continue

        method = msg.get("method", "")
        params = msg.get("params", {})
        msg_id = msg.get("id", 0)
        result = {}

        if method == "initialize":
            result = {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "ai-router-bridge", "version": "1.0.0"}
            }
        elif method == "tools/list":
            # Get tools from VPS router
            try:
                remote = call_router("tools/list")
                result = {"tools": remote.get("tools", [])}
            except:
                result = {"tools": []}
        elif method == "tools/call":
            try:
                result = call_router("tools/call", params)
            except Exception as e:
                result = {"content": [{"type": "text", "text": f"Bridge error: {str(e)}"}]}
        elif method == "notifications/initialized":
            continue
        else:
            continue

        response = json.dumps({"jsonrpc": "2.0", "result": result, "id": msg_id})
        sys.stdout.write(response + "\n")
        sys.stdout.flush()

if __name__ == "__main__":
    main()
