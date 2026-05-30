// KV Gateway Worker — lightweight API for VPS to read/write KV
// Deploy as a separate Worker, protected by a simple key

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const key = url.searchParams.get("key");
    const auth = url.searchParams.get("token");

    // Simple auth
    if (auth !== env.TOKEN) {
      return new Response("Unauthorized", { status: 401 });
    }

    // GET /?key=xxx&token=yyy — read
    if (request.method === "GET" && key) {
      const val = await env.KV.get(key);
      if (val === null) return new Response("Not Found", { status: 404 });
      return new Response(val, { headers: { "Content-Type": "application/json" } });
    }

    // PUT /?key=xxx&token=yyy — write (body = value)
    if (request.method === "PUT" && key) {
      const body = await request.text();
      await env.KV.put(key, body);
      return new Response(JSON.stringify({ success: true }));
    }

    // DELETE /?key=xxx&token=yyy — delete
    if (request.method === "DELETE" && key) {
      await env.KV.delete(key);
      return new Response(JSON.stringify({ success: true }));
    }

    // LIST /?prefix=xxx&token=yyy — list keys
    if (request.method === "GET" && url.searchParams.has("prefix")) {
      const prefix = url.searchParams.get("prefix") || "";
      const list = await env.KV.list({ prefix });
      return new Response(JSON.stringify(list.keys.map(k => k.name)));
    }

    return new Response("Usage: ?key=xxx&token=yyy [GET|PUT|DELETE] or ?prefix=xxx&token=yyy [GET]", { status: 400 });
  }
};
