"""Cloudflare KV helper — via KV Gateway Worker (no API token needed)."""
import json, urllib.request, urllib.error, os, sys

# Auto-load .env.ai_router
_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env.ai_router")
if not os.path.exists(_env_path):
    _env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env.ai_router")
if os.path.exists(_env_path):
    with open(_env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                if v and k not in os.environ:
                    os.environ[k.strip()] = v.strip()

# KV Gateway config
GW_URL = os.environ.get("CF_KV_URL", "https://kv.zhuguang.ccwu.cc")
GW_TOKEN = os.environ.get("CF_KV_TOKEN", "ai-router-kv-2026")


def _make_req(url, method="GET", data=None):
    """Create request with proper headers."""
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("User-Agent", "ai-router/2.0")
    req.add_header("Content-Type", "text/plain")
    return req


def kv_get(key):
    """Read a value from KV. Returns None if not found."""
    url = f"{GW_URL}/?key={key}&token={GW_TOKEN}"
    try:
        with urllib.request.urlopen(_make_req(url), timeout=10) as resp:
            return resp.read().decode()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def kv_get_json(key):
    """Read a JSON value from KV."""
    val = kv_get(key)
    return json.loads(val) if val else None


def kv_put(key, value):
    """Write a value to KV."""
    url = f"{GW_URL}/?key={key}&token={GW_TOKEN}"
    data = value.encode() if isinstance(value, str) else json.dumps(value, ensure_ascii=False).encode()
    with urllib.request.urlopen(_make_req(url, "PUT", data), timeout=10) as resp:
        return json.loads(resp.read().decode())


def kv_put_json(key, obj):
    """Write a JSON object to KV."""
    return kv_put(key, json.dumps(obj, ensure_ascii=False))


def kv_list(prefix=""):
    """List keys."""
    url = f"{GW_URL}/?prefix={prefix}&token={GW_TOKEN}"
    with urllib.request.urlopen(_make_req(url), timeout=10) as resp:
        return json.loads(resp.read().decode())


def kv_delete(key):
    """Delete a key from KV."""
    url = f"{GW_URL}/?key={key}&token={GW_TOKEN}"
    with urllib.request.urlopen(_make_req(url, "DELETE"), timeout=10) as resp:
        return json.loads(resp.read().decode())


# --- CLI ---
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python cf_kv.py <get|put|list|delete> [key] [value]")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "get" and len(sys.argv) >= 3:
        val = kv_get(sys.argv[2])
        print(val if val else "Key not found")
    elif cmd == "put" and len(sys.argv) >= 4:
        result = kv_put(sys.argv[2], sys.argv[3])
        print("OK" if result.get("success") else result)
    elif cmd == "list":
        prefix = sys.argv[2] if len(sys.argv) >= 3 else ""
        keys = kv_list(prefix)
        for k in keys:
            print(k)
        print(f"\n{len(keys)} keys")
    elif cmd == "delete" and len(sys.argv) >= 3:
        result = kv_delete(sys.argv[2])
        print("OK" if result.get("success") else result)
    else:
        print("Usage: python cf_kv.py <get|put|list|delete> [key] [value]")
