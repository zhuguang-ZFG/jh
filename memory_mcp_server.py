import json, os, sys, datetime, uuid, sqlite3, struct, traceback
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


DB_PATH = "/opt/memory-mcp/data/memories.db"
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

conn = sqlite3.connect(DB_PATH, check_same_thread=False)
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("""CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY, text TEXT NOT NULL, category TEXT DEFAULT 'general',
    ts TEXT NOT NULL, embedding BLOB
)""")
conn.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    text, category, content=memories, content_rowid=rowid
)""")
conn.execute("CREATE INDEX IF NOT EXISTS idx_ts ON memories(ts)")

conn.execute("""CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, text, category) VALUES (new.rowid, new.text, new.category);
END""")
conn.execute("""CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, text, category) VALUES('delete', old.rowid, old.text, old.category);
END""")
conn.execute("""CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, text, category) VALUES('delete', old.rowid, old.text, old.category);
    INSERT INTO memories_fts(rowid, text, category) VALUES (new.rowid, new.text, new.category);
END""")
conn.commit()

embedder = None
EMBED_MODEL = "BAAI/bge-small-en-v1.5"
EMBED_DIM = 384


def _load_embedder():
    global embedder
    if embedder is not None:
        return True
    try:
        from fastembed import TextEmbedding

        embedder = TextEmbedding(EMBED_MODEL)
        return True
    except Exception:
        embedder = None
        return False


def _embed(texts):
    if not _load_embedder():
        return None
    try:
        return [v.tolist() for v in embedder.embed(texts)]
    except Exception:
        return None


def _cosine_sim(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    return dot / (na * nb + 1e-10)


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, rid, result):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(
            json.dumps(
                {"jsonrpc": "2.0", "result": result, "id": rid}, ensure_ascii=False
            ).encode()
        )

    def _error(self, rid, msg):
        self._send(rid, {"content": [{"type": "text", "text": "Error: " + msg}]})

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
            self._send(
                rid,
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "vps-memory", "version": "2.0.0"},
                },
            )
            return

        if m == "tools/list":
            self._send(
                rid,
                {
                    "tools": [
                        {
                            "name": "add_memory",
                            "description": "Save a memory for future recall",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "text": {"type": "string"},
                                    "category": {"type": "string"},
                                },
                            },
                        },
                        {
                            "name": "search_memories",
                            "description": "Search memories by keyword (FTS5) and/or semantic similarity",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "query": {"type": "string"},
                                    "limit": {"type": "integer", "default": 5},
                                },
                            },
                        },
                        {
                            "name": "get_recent",
                            "description": "Get most recent memories",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "limit": {"type": "integer", "default": 10}
                                },
                            },
                        },
                        {"name": "get_all", "description": "Return all memories"},
                        {
                            "name": "delete_memory",
                            "description": "Delete a memory by ID",
                            "inputSchema": {
                                "type": "object",
                                "properties": {"id": {"type": "string"}},
                            },
                        },
                        {
                            "name": "memory_stats",
                            "description": "Show memory count and embedding status",
                        },
                    ]
                },
            )
            return

        if m == "tools/call":
            a = p.get("arguments", {})
            nm = p.get("name", "")
            try:
                if nm == "add_memory":
                    text = a.get("text", "").strip()
                    if not text:
                        self._error(rid, "No text provided")
                        return
                    cat = a.get("category", "general")
                    ts = datetime.datetime.now().isoformat()
                    mid = str(uuid.uuid4())[:8]
                    vecs = _embed([text])
                    emb = struct.pack("%df" % EMBED_DIM, *vecs[0]) if vecs else None
                    conn.execute(
                        "INSERT INTO memories (id, text, category, ts, embedding) VALUES (?,?,?,?,?)",
                        (mid, text, cat, ts, emb),
                    )
                    conn.commit()
                    status = "with embedding" if emb else "FTS-only"
                    self._send(
                        rid,
                        {
                            "content": [
                                {
                                    "type": "text",
                                    "text": "SAVED [%s] (%s) [%s]: %s"
                                    % (mid, cat, status, text[:150]),
                                }
                            ]
                        },
                    )

                elif nm == "search_memories":
                    q = a.get("query", "").strip()
                    if not q:
                        self._error(rid, "No query provided")
                        return
                    limit = a.get("limit", 5)
                    fts_results = {}
                    try:
                        rows = conn.execute(
                            "SELECT m.id, m.text, m.category, m.ts, rank FROM memories_fts fts "
                            "JOIN memories m ON m.rowid = fts.rowid "
                            "WHERE memories_fts MATCH ? ORDER BY rank LIMIT ?",
                            (q, limit * 3),
                        ).fetchall()
                        for r in rows:
                            fts_results[r[0]] = {
                                "text": r[1],
                                "category": r[2],
                                "ts": r[3],
                                "fts_rank": -r[4],
                            }
                    except Exception:
                        rows = conn.execute(
                            "SELECT id, text, category, ts FROM memories WHERE text LIKE ? LIMIT ?",
                            ("%" + q + "%", limit * 3),
                        ).fetchall()
                        for r in rows:
                            fts_results[r[0]] = {
                                "text": r[1],
                                "category": r[2],
                                "ts": r[3],
                                "fts_rank": 1.0,
                            }

                    q_vecs = _embed([q])
                    vec_results = {}
                    if q_vecs:
                        q_vec = q_vecs[0]
                        all_rows = conn.execute(
                            "SELECT id, text, category, ts, embedding FROM memories WHERE embedding IS NOT NULL"
                        ).fetchall()
                        scored = []
                        for r in all_rows:
                            vec = struct.unpack("%df" % EMBED_DIM, r[4])
                            sim = _cosine_sim(q_vec, vec)
                            scored.append((sim, r))
                        scored.sort(reverse=True)
                        for sim, r in scored[: limit * 3]:
                            vec_results[r[0]] = {
                                "text": r[1],
                                "category": r[2],
                                "ts": r[3],
                                "vec_sim": sim,
                            }

                    if vec_results:
                        all_ids = set(fts_results) | set(vec_results)
                        merged = []
                        for mid in all_ids:
                            fts_s = fts_results.get(mid, {}).get("fts_rank", 0)
                            vec_s = vec_results.get(mid, {}).get("vec_sim", 0)
                            merged.append(
                                (
                                    0.4 * fts_s + 0.6 * vec_s,
                                    fts_results.get(mid) or vec_results.get(mid),
                                )
                            )
                        merged.sort(reverse=True)
                        lines = [
                            "[%s] %s" % (r[1]["category"], r[1]["text"][:200])
                            for r in merged[:limit]
                        ]
                    else:
                        items = sorted(
                            fts_results.values(),
                            key=lambda x: x["fts_rank"],
                            reverse=True,
                        )[:limit]
                        lines = [
                            "[%s] %s" % (r["category"], r["text"][:200]) for r in items
                        ]

                    mode = "hybrid" if vec_results else "FTS-only"
                    self._send(
                        rid,
                        {
                            "content": [
                                {
                                    "type": "text",
                                    "text": "[%s] %s"
                                    % (mode, chr(10).join(lines) or "No matches"),
                                }
                            ]
                        },
                    )

                elif nm == "get_recent":
                    n = a.get("limit", 10)
                    rows = conn.execute(
                        "SELECT category, text FROM memories ORDER BY ts DESC LIMIT ?",
                        (n,),
                    ).fetchall()
                    lines = ["[%s] %s" % (r[0], r[1][:200]) for r in rows]
                    self._send(
                        rid,
                        {
                            "content": [
                                {"type": "text", "text": chr(10).join(lines) or "Empty"}
                            ]
                        },
                    )

                elif nm == "get_all":
                    rows = conn.execute(
                        "SELECT category, text FROM memories WHERE id != 'init' ORDER BY ts DESC"
                    ).fetchall()
                    lines = ["[%s] %s" % (r[0], r[1][:200]) for r in rows]
                    self._send(
                        rid,
                        {
                            "content": [
                                {
                                    "type": "text",
                                    "text": "%d memories:\n%s"
                                    % (len(lines), chr(10).join(lines)),
                                }
                            ]
                        },
                    )

                elif nm == "delete_memory":
                    mid = a.get("id", "").strip()
                    if not mid:
                        self._error(rid, "No id provided")
                        return
                    cur = conn.execute("DELETE FROM memories WHERE id = ?", (mid,))
                    conn.commit()
                    if cur.rowcount:
                        self._send(
                            rid,
                            {
                                "content": [
                                    {"type": "text", "text": "Deleted [%s]" % mid}
                                ]
                            },
                        )
                    else:
                        self._error(rid, "Memory [%s] not found" % mid)

                elif nm == "memory_stats":
                    count = conn.execute(
                        "SELECT COUNT(*) FROM memories WHERE id != 'init'"
                    ).fetchone()[0]
                    with_emb = conn.execute(
                        "SELECT COUNT(*) FROM memories WHERE embedding IS NOT NULL AND id != 'init'"
                    ).fetchone()[0]
                    has_model = _load_embedder()
                    self._send(
                        rid,
                        {
                            "content": [
                                {
                                    "type": "text",
                                    "text": "Total: %d, with embeddings: %d, model loaded: %s"
                                    % (count, with_emb, has_model),
                                }
                            ]
                        },
                    )

                else:
                    self._error(rid, "Unknown tool: " + nm)
            except Exception as e:
                self._error(rid, "%s\n%s" % (e, traceback.format_exc()[-500:]))
            return

        self._error(rid, "Unknown method: " + m)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    print("Memory MCP v2.0 on port %d (SQLite FTS5 + fastembed)" % port)
    _load_embedder()
    ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever()
