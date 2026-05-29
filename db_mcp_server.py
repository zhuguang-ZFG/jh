import json, sys, os
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
import subprocess, re

class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    pass

# DB connections config
DBS = {
    "mysql": {"host": "47.112.162.80", "port": 3306, "user": "root", "password": "Zhuguang119", "type": "mysql", "ssh": True},
    "pgsql": {"host": "127.0.0.1", "port": 5432, "user": "postgres", "password": "Zhuguang119", "type": "postgres"},
}

def run_sql(db_name, sql):
    """Execute SQL via mysql/psql CLI"""
    db = DBS.get(db_name)
    if not db:
        return f"Unknown database: {db_name}. Use: {list(DBS.keys())}"

    if db["type"] == "mysql":
        if db.get("ssh"):
            cmd = f"ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new root@47.112.162.80 'mysql -u root -pZhuguang119 -e \"{sql}\"'" + " 2>&1"
    else:
        cmd = f"PGPASSWORD={db['password']} psql -h {db['host']} -p {db['port']} -U {db['user']} -c \"{sql}\" 2>&1"

    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10, env={**os.environ, "PGPASSWORD": db.get("password", "")})
    out = (r.stdout + r.stderr).strip()
    if len(out) > 6000:
        out = out[:6000] + f"\n... ({len(out)} total chars, truncated)"
    return out or "Query executed (no output)"

def list_tables(db_name):
    """List all tables in database"""
    db = DBS.get(db_name)
    if db["type"] == "mysql":
        return run_sql(db_name, "SHOW TABLES;")
    else:
        return run_sql(db_name, "\\dt")

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        b = json.loads(self.rfile.read(n)) if n else {}
        m = b.get("method", "")
        p = b.get("params", {})
        r = None

        if m == "initialize":
            r = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "vps-database", "version": "1.0.0"}}
        elif m == "tools/list":
            r = {"tools": [
                {"name": "db_query", "description": "Execute SQL query on MySQL or PostgreSQL. Use db='mysql' or 'pgsql'.", "inputSchema": {"properties": {"db": {"type": "string"}, "sql": {"type": "string"}}}},
                {"name": "db_list_tables", "description": "List all tables in a database.", "inputSchema": {"properties": {"db": {"type": "string"}}}},
                {"name": "db_describe", "description": "Show table schema.", "inputSchema": {"properties": {"db": {"type": "string"}, "table": {"type": "string"}}}},
                {"name": "db_list_databases", "description": "List all databases on MySQL.", "inputSchema": {"properties": {"db": {"type": "string", "default": "mysql"}}}}
            ]}

        elif m == "tools/call":
            a = p.get("arguments", {})
            nm = p.get("name", "")

            if nm == "db_query":
                txt = run_sql(a.get("db", "mysql"), a.get("sql", "SELECT 1"))
            elif nm == "db_list_tables":
                txt = list_tables(a.get("db", "mysql"))
            elif nm == "db_describe":
                dbn = a.get("db", "mysql")
                tbl = a.get("table", "")
                if DBS[dbn]["type"] == "mysql":
                    txt = run_sql(dbn, f"DESCRIBE {tbl};")
                else:
                    txt = run_sql(dbn, f"\\d {tbl}")
            elif nm == "db_list_databases":
                txt = run_sql(a.get("db", "mysql"), "SHOW DATABASES;")
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
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8768
    print(f"DB MCP on port {port}")
    ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever()
