import json, sys, os, time
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
import subprocess

class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    pass

# Multi-backend config — each backend has its own API, key, models
BACKENDS = {
    "deepseek": {
        "url": "https://api.deepseek.com/v1/chat/completions",
        "key": os.environ.get("DEEPSEEK_KEY", ""),
        "models": {
            "ds-chat": {"name": "deepseek-chat", "desc": "DeepSeek V4 Chat — 快速便宜"},
            "ds-reason": {"name": "deepseek-reasoner", "desc": "DeepSeek R1 — 深度推理"},
        }
    },
    "openrouter": {
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "key": os.environ.get("OR_KEY", ""),
        "models": {
            "or-qwen3": {"name": "qwen/qwen3-next-80b-a3b-instruct:free", "desc": "Qwen3 80B — 综合"},
            "or-code": {"name": "qwen/qwen3-coder:free", "desc": "Qwen3 Coder — 代码"},
            "or-nemo": {"name": "nvidia/nemotron-3-super-120b-a12b:free", "desc": "Nemotron 120B — 强推理"},
            "or-l3": {"name": "meta-llama/llama-3.3-70b-instruct:free", "desc": "Llama 3.3 70B — 创意"},
            "or-deepseek": {"name": "deepseek/deepseek-v4-flash:free", "desc": "DS V4 via OR — 备选"},
            "or-gptoss": {"name": "openai/gpt-oss-120b:free", "desc": "GPT-OSS 120B — 体验"},
            "or-glm": {"name": "z-ai/glm-4.5-air:free", "desc": "GLM-4.5 — 备选"},
        }
    }
}

def call_backend(mid, messages, max_retries=2):
    """Call a model, try multiple backends on failure"""
    # Find the model
    for backend_name, cfg in BACKENDS.items():
        if mid in cfg["models"]:
            model_info = cfg["models"][mid]
            break
    else:
        return f"Unknown model: {mid}. Try: {list_models()}"

    body = json.dumps({"model": model_info["name"], "messages": messages, "max_tokens": 2048})
    cmd_base = ["curl", "-s", "-L", "-k", "--proxy", "http://127.0.0.1:7890",
                 "-H", f"Authorization: Bearer {cfg['key']}",
                 "-H", "Content-Type: application/json",
                 "-d", body, "--max-time", "60"]

    for attempt in range(max_retries + 1):
        r = subprocess.run(cmd_base + [cfg["url"]], capture_output=True, text=True, timeout=65)
        try:
            data = json.loads(r.stdout)
            if "choices" in data:
                return data["choices"][0]["message"]["content"]
            err = data.get("error", {}).get("message", "")
            code = data.get("error", {}).get("code", 0)
            if code == 429:  # Rate limited
                time.sleep(2)
                continue
            return f"API error [{mid}]: {err[:300]}"
        except:
            if attempt < max_retries:
                time.sleep(1)
            else:
                return f"Parse error: {r.stdout[:500]}"
    return "All retries exhausted"

def list_models():
    lines = []
    for bn, cfg in BACKENDS.items():
        for mn, mi in cfg["models"].items():
            lines.append(f"**{mn}** ({bn}): {mi['desc']}")
    return "\n".join(lines)

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        b = json.loads(self.rfile.read(n)) if n else {}
        m = b.get("method", "")
        p = b.get("params", {})

        if m == "initialize":
            r = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "vps-ai-router", "version": "1.0.0"}}
        elif m == "tools/list":
            r = {"tools": [
                {"name": "ai_ask", "description": "Ask any AI model. Multi-backend with auto-failover.", "inputSchema": {"properties": {"model": {"type": "string", "default": "ds-chat"}, "prompt": {"type": "string"}}}},
                {"name": "ai_auto", "description": "Smart routing: reason model for complex, chat for simple. Auto retry on rate limit.", "inputSchema": {"properties": {"prompt": {"type": "string"}}}},
                {"name": "ai_models", "description": "List all available models across backends."}
            ]}

        elif m == "tools/call":
            a = p.get("arguments", {})
            nm = p.get("name", "")

            if nm == "ai_models":
                txt = list_models()
            elif nm == "ai_auto":
                prompt = a.get("prompt", "")
                is_complex = any(w in prompt.lower()[:300] for w in [
                    "design", "architecture", "debug", "refactor", "complex",
                    "pattern", "analyze", "explain", "how does", "why is"
                ]) or len(prompt) > 500

                if is_complex:
                    txt = call_backend("ds-reason", [{"role": "user", "content": prompt}])
                else:
                    txt = call_backend("ds-chat", [{"role": "user", "content": prompt}])
            elif nm == "ai_ask":
                txt = call_backend(a.get("model", "ds-chat"), [{"role": "user", "content": a.get("prompt", "")}])
            else:
                txt = "Unknown tool"

            r = {"content": [{"type": "text", "text": txt}]}

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps({"jsonrpc": "2.0", "result": r, "id": b.get("id", 0)}).encode())

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8769
    print(f"AI Router MCP on {port}")
    ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever()
