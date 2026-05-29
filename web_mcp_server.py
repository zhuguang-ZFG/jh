import json, sys, re, subprocess, traceback
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import quote_plus

class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    pass

def curl_get(url, timeout=15):
    cmd = ["curl", "-s", "-L", "-k", "--proxy", "http://127.0.0.1:7890",
           "-H", "User-Agent: Mozilla/5.0", "--max-time", str(timeout), url]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout+5)
    return r.stdout

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
            self._send(rid, {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "vps-web-search", "version": "1.0.0"}})
            return

        if m == "tools/list":
            self._send(rid, {"tools": [
                {"name": "web_search", "description": "Search the web and return results with URLs and snippets.", "inputSchema": {"properties": {"query": {"type": "string"}, "limit": {"type": "integer", "default": 5}}}},
                {"name": "fetch_url", "description": "Fetch and extract readable text from any URL.", "inputSchema": {"properties": {"url": {"type": "string"}}}},
                {"name": "translate", "description": "Translate text (auto-detect to Chinese or English).", "inputSchema": {"properties": {"text": {"type": "string"}, "target": {"type": "string", "default": "zh"}}}}
            ]})
            return

        if m == "tools/call":
            a = p.get("arguments", {})
            nm = p.get("name", "")
            try:
                if nm == "web_search":
                    q = a.get("query", "")
                    limit = a.get("limit", 5)
                    html = curl_get(f"https://www.bing.com/search?q={quote_plus(q)}&count={limit}")
                    results = []
                    items = re.findall(r'<li class="b_algo"[^>]*>(.*?)</li>', html, re.DOTALL)
                    for i, item in enumerate(items[:limit]):
                        link = re.search(r'<a[^>]*href="([^"]+)"[^>]*>', item)
                        title = re.search(r'<h2[^>]*>(.*?)</h2>', item, re.DOTALL)
                        snippet = re.search(r'<p[^>]*>(.*?)</p>', item, re.DOTALL) or re.search(r'<div class="b_caption"[^>]*>.*?<p[^>]*>(.*?)</p>', item, re.DOTALL)
                        url = link.group(1) if link else "?"
                        t = re.sub(r'<.*?>', '', title.group(1)).strip() if title else "No title"
                        s = re.sub(r'<.*?>', '', snippet.group(1)).strip() if snippet else "N/A"
                        results.append(f"{i+1}. {t}\n   URL: {url}\n   {s}")
                    txt = "\n\n".join(results) or f"No results for: {q}"
                    self._send(rid, {"content": [{"type": "text", "text": txt}]})

                elif nm == "fetch_url":
                    url = a.get("url", "")
                    html = curl_get(url, timeout=20)
                    text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL|re.IGNORECASE)
                    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL|re.IGNORECASE)
                    text = re.sub(r'<[^>]+>', ' ', text)
                    text = re.sub(r'\s+', ' ', text).strip()
                    txt = text[:8000] if text else "No readable content"
                    self._send(rid, {"content": [{"type": "text", "text": txt}]})

                elif nm == "translate":
                    text = a.get("text", "")
                    target = a.get("target", "zh")
                    tl = target
                    turl = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl={tl}&dt=t&q={quote_plus(text[:1000])}"
                    data = curl_get(turl)
                    parts = [s[0] for s in json.loads(data)[0] if s[0]]
                    txt = "".join(parts)
                    self._send(rid, {"content": [{"type": "text", "text": txt}]})
                else:
                    self._error(rid, f"Unknown tool: {nm}")
            except Exception as e:
                self._error(rid, f"{e}\n{traceback.format_exc()[-300:]}")
            return

        self._error(rid, f"Unknown method: {m}")

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8767
    print(f"Web MCP on {port}")
    ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever()
