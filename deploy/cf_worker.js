export default {
  async fetch(request) {
    const url = new URL(request.url);
    const init = { method: request.method, body: request.body, redirect: "follow" };
    init.headers = {};
    for (const [k, v] of request.headers) {
      init.headers[k] = v;
    }
    const resp = await fetch("https://api.telegram.org" + url.pathname + url.search, init);
    return new Response(resp.body, { status: resp.status, headers: { "Content-Type": "application/json" } });
  },
};
