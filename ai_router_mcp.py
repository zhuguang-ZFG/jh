import json, sys, os, time, hashlib, random, urllib.request, urllib.error, urllib.parse
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from concurrent.futures import ThreadPoolExecutor, as_completed

class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True

# --- Load .env file if present ---
def load_env(path):
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                if v and k not in os.environ:
                    os.environ[k.strip()] = v.strip()

load_env(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env.ai_router"))

# --- Proxy config (VPS mihomo) ---
PROXY = os.environ.get("HTTP_PROXY", "http://127.0.0.1:7890")

# --- Backends ---
BACKENDS = {
"openrouter": {
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "key_env": "OR_KEY",
        "models": {
            "or-glm":      {"name": "z-ai/glm-4.5-air:free", "desc": "GLM-4.5 Air — 思考模型"},
            "or-nemo":     {"name": "nvidia/nemotron-3-super-120b-a12b:free", "desc": "Nemotron 120B"},
            "or-gptoss":   {"name": "openai/gpt-oss-120b:free", "desc": "GPT-OSS 120B"},
        }
    },
    "zhipu": {
        "url": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        "key_env": "ZHIPU_KEY",
        "models": {
            "glm-flash": {"name": "glm-4-flash", "desc": "GLM-4 Flash — 200K 上下文"},
            "glm-air":   {"name": "glm-4-air", "desc": "GLM-4 Air — 快速"},
        }
    },
    "aliyun": {
        "url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        "key_env": "ALIYUN_KEY",
        "models": {
            "ali-qwen":  {"name": "qwen-plus", "desc": "通义千问 Plus"},
            "ali-turbo": {"name": "qwen-turbo", "desc": "通义千问 Turbo — 快"},
        }
    },
    "nvidia_nim": {
        "url": "https://integrate.api.nvidia.com/v1/chat/completions",
        "key_env": "NVIDIA_NIM_KEY",
        "models": {
            "nv-llama70b":  {"name": "meta/llama-3.3-70b-instruct", "desc": "NIM Llama 3.3 70B"},
            "nv-llama8b":   {"name": "meta/llama-3.1-8b-instruct", "desc": "NIM Llama 8B — 快"},
            "nv-qwen72b":   {"name": "qwen/qwen2.5-72b-instruct", "desc": "NIM Qwen 72B"},
        }
    },
    "sambanova": {
        "url": "https://api.sambanova.ai/v1/chat/completions",
        "key_env": "SAMBANOVA_KEY",
        "models": {
            "sn-dsv31":     {"name": "DeepSeek-V3.1", "desc": "SambaNova DeepSeek V3.1 — 131K ctx"},
            "sn-dsv32":     {"name": "DeepSeek-V3.2", "desc": "SambaNova DeepSeek V3.2"},
            "sn-llama4":    {"name": "Llama-4-Maverick-17B-128E-Instruct", "desc": "Llama 4 Maverick — 131K ctx"},
            "sn-llama70b":  {"name": "Meta-Llama-3.3-70B-Instruct", "desc": "SambaNova Llama 3.3 70B"},
            "sn-gptoss":    {"name": "gpt-oss-120b", "desc": "GPT-OSS 120B"},
            "sn-gemma":     {"name": "gemma-4-31B-it", "desc": "Gemma 4 31B"},
        }
    },
    "zhida": {
        "url": "https://developer.zhihu.com/v1/chat/completions",
        "key_env": "ZHIHU_KEY",
        "extra_headers": {"X-Request-Timestamp": "__unix_ts__"},
        "models": {
            "zd-fast":     {"name": "zhida-fast-1p5", "desc": "知乎直答 快速 — 0.4s"},
            "zd-thinking": {"name": "zhida-thinking-1p5", "desc": "知乎直答 深度思考 — 带推理链"},
            "zd-agent":    {"name": "zhida-agent", "desc": "知乎直答 智能 — 可搜索"},
        }
    },
    "mimo": {
        "url": "https://token-plan-sgp.xiaomimimo.com/v1/chat/completions",
        "key_env": "MIMO_KEY",
        "models": {
            "mi-pro":      {"name": "mimo-v2.5-pro", "desc": "MIMO v2.5 Pro — 小米最强"},
            "mi-chat":     {"name": "mimo-v2.5", "desc": "MIMO v2.5 — 通用"},
            "mi-tts":      {"name": "mimo-v2.5-tts", "desc": "MIMO v2.5 TTS — 语音合成"},
            "mi-v2pro":    {"name": "mimo-v2-pro", "desc": "MIMO v2 Pro"},
            "mi-omni":     {"name": "mimo-v2-omni", "desc": "MIMO v2 Omni — 多模态"},
        }
    },
    "mimo-cn": {
        "url": "https://token-plan-cn.xiaomimimo.com/v1/chat/completions",
        "key_env": "MIMO_CN_KEY",
        "models": {
            "mc-pro":      {"name": "mimo-v2.5-pro", "desc": "MIMO CN v2.5 Pro — 国内节点"},
            "mc-chat":     {"name": "mimo-v2.5", "desc": "MIMO CN v2.5 — 国内节点"},
        }
    },
    "stepfun": {
        "url": "https://api.stepfun.com/v1/chat/completions",
        "key_env": "STEPFUN_KEY",
        "models": {
            "st-flash":    {"name": "step-3.7-flash", "desc": "Step 3.7 Flash — 阶跃星辰最新"},
            "st-2-16k":    {"name": "step-2-16k", "desc": "Step 2 16K — 阶跃通用"},
            "st-1-8k":     {"name": "step-1-8k", "desc": "Step 1 8K — 阶跃轻量"},
            "st-1v-32k":   {"name": "step-1v-32k", "desc": "Step 1V 32K — 阶跃多模态"},
        }
    },
}

# --- Zero-key backends ---
ZERO_KEY_BACKENDS = {
    "pollinations": {
        "url": "https://text.pollinations.ai/openai",
        "models": {
            "zk-openai":   {"name": "openai", "desc": "Pollinations OpenAI — 零Key"},
            "zk-deepseek": {"name": "deepseek", "desc": "Pollinations DeepSeek — 零Key"},
        }
    },
    "llm7": {
        "url": "https://api.llm7.io/v1/chat/completions",
        "models": {
            "l7-deepseek": {"name": "deepseek-r1", "desc": "LLM7 DeepSeek R1 — 零Key"},
            "l7-gpt4mini": {"name": "gpt-4o-mini", "desc": "LLM7 GPT-4o Mini — 零Key"},
        }
    },
}
for name, cfg in ZERO_KEY_BACKENDS.items():
    cfg.setdefault("key_env", "")
    BACKENDS[name] = cfg

ZERO_KEY_BACKEND_NAMES = set(ZERO_KEY_BACKENDS.keys())

# --- CF KV Integration ---
KV_URL = os.environ.get("CF_KV_URL", "https://kv.zhuguang.ccwu.cc")
KV_TOKEN = os.environ.get("CF_KV_TOKEN", "ai-router-kv-2026")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

_stats = {"total_calls": 0, "total_errors": 0, "models": {}, "started": int(time.time()),
          "cache_hits": 0, "cache_misses": 0}
_model_health = {}

def _kv_put(key, value):
    def _do():
        try:
            url = f"{KV_URL}/?key={key}&token={KV_TOKEN}"
            data = value.encode() if isinstance(value, str) else json.dumps(value, ensure_ascii=False).encode()
            req = urllib.request.Request(url, data=data, method="PUT")
            req.add_header("User-Agent", "ai-router/2.1")
            urllib.request.urlopen(req, timeout=10)
        except:
            pass
    threading.Thread(target=_do, daemon=True).start()

def _kv_get(key):
    try:
        url = f"{KV_URL}/?key={key}&token={KV_TOKEN}"
        req = urllib.request.Request(url, method="GET")
        req.add_header("User-Agent", "ai-router/2.1")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.read().decode()
    except:
        return None

# --- Stats & Health ---
def _log_call(mid, success, latency, error=""):
    _stats["total_calls"] += 1
    if not success:
        _stats["total_errors"] += 1
    if mid not in _stats["models"]:
        _stats["models"][mid] = {"calls": 0, "errors": 0, "total_latency": 0}
    _stats["models"][mid]["calls"] += 1
    _stats["models"][mid]["total_latency"] += latency
    if not success:
        _stats["models"][mid]["errors"] += 1
    if mid not in _model_health:
        _model_health[mid] = {"failures": 0, "unhealthy_until": 0, "consecutive_ok": 0}
    if success:
        _model_health[mid]["failures"] = 0
        _model_health[mid]["consecutive_ok"] = _model_health[mid].get("consecutive_ok", 0) + 1
        _model_health[mid]["unhealthy_until"] = 0
    else:
        _model_health[mid]["failures"] += 1
        _model_health[mid]["consecutive_ok"] = 0
        if _model_health[mid]["failures"] >= 3:
            _model_health[mid]["unhealthy_until"] = time.time() + 300
    if _stats["total_calls"] % 10 == 0:
        _kv_put("ai_router_stats", json.dumps(_stats, ensure_ascii=False))
        _kv_put("ai_router_health", json.dumps(_model_health, ensure_ascii=False))

def _is_healthy(mid):
    h = _model_health.get(mid, {})
    return time.time() > h.get("unhealthy_until", 0)

def _model_available(mid):
    for bn, bcfg in BACKENDS.items():
        if mid in bcfg["models"]:
            key_env = bcfg.get("key_env", "")
            return bool(os.environ.get(key_env, "")) if key_env else True
    return False

def _pick_key(key_env):
    """Pick a random key from comma-separated pool, or return single key."""
    raw = os.environ.get(key_env, "")
    if not raw:
        return ""
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    return random.choice(keys) if keys else ""

# --- Cache (F4) ---
_cache = {}
_cache_lock = threading.Lock()

def _cache_key(mid, messages, max_tokens):
    h = hashlib.md5(json.dumps({"m": mid, "msgs": messages, "mt": max_tokens}, sort_keys=True).encode()).hexdigest()
    return h

def _cache_get(mid, messages, max_tokens):
    key = _cache_key(mid, messages, max_tokens)
    with _cache_lock:
        if key in _cache:
            entry = _cache[key]
            ttl = 900 if mid.split("-")[0] in ("zk", "l7") else 300  # 15min zero-key, 5min others
            if time.time() - entry["ts"] < ttl:
                _stats["cache_hits"] += 1
                return entry["result"]
            del _cache[key]
    _stats["cache_misses"] += 1
    return None

def _cache_set(mid, messages, max_tokens, result):
    key = _cache_key(mid, messages, max_tokens)
    with _cache_lock:
        # Evict oldest if cache grows too large
        if len(_cache) > 500:
            oldest = min(_cache, key=lambda k: _cache[k]["ts"])
            del _cache[oldest]
        _cache[key] = {"result": result, "ts": time.time()}

# --- Core: call_model ---
def _do_http(url, body_bytes, headers, use_proxy, timeout=60):
    """Execute HTTP request with proxy handling. Returns (data_dict, raw_response)."""
    proxy_handler = urllib.request.ProxyHandler({"https": PROXY, "http": PROXY} if use_proxy else {})
    opener = urllib.request.build_opener(proxy_handler)
    req = urllib.request.Request(url, data=body_bytes, headers=headers, method="POST")
    with opener.open(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())

def _get_backend_for_model(mid):
    for bname, bcfg in BACKENDS.items():
        if mid in bcfg["models"]:
            return bname, bcfg
    return None, None

def _should_use_proxy(url):
    return not any(d in url for d in [
        "siliconflow.cn", "bigmodel.cn", "baidubce.com",
        "hunyuan.cloud.tencent.com", "volces.com", "dashscope.aliyuncs.com", "llm7.io"
    ])

def call_model(mid, messages, max_tokens=2048, use_cache=True):
    """Call a model by its short ID. Returns response text."""
    # Cache check
    if use_cache:
        cached = _cache_get(mid, messages, max_tokens)
        if cached is not None:
            return cached

    t0 = time.time()
    bname, bcfg = _get_backend_for_model(mid)
    if not bcfg:
        avail = []
        for bn, bc in BACKENDS.items():
            for mn in bc["models"]:
                avail.append(mn)
        return f"Unknown model: {mid}\nAvailable: {', '.join(sorted(avail))}"

    if not _is_healthy(mid):
        return f"Model {mid} is temporarily unavailable (cooldown). Try another model."

    if "url_template" in bcfg:
        account = os.environ.get(bcfg.get("account_env", ""), "")
        url = bcfg["url_template"].format(account=account)
    else:
        url = bcfg["url"]

    key = _pick_key(bcfg.get("key_env", ""))
    model_info = bcfg["models"][mid]

    body = json.dumps({
        "model": model_info["name"],
        "messages": messages,
        "max_tokens": max_tokens,
    }).encode()

    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    for hk, hv in bcfg.get("extra_headers", {}).items():
        if hv == "__unix_ts__":
            hv = str(int(time.time()))
        headers[hk] = hv

    use_proxy = _should_use_proxy(url)

    for attempt in range(3):
        try:
            data = _do_http(url, body, headers, use_proxy)
            latency = round(time.time() - t0, 2)
            if "choices" in data:
                _log_call(mid, True, latency)
                msg = data["choices"][0]["message"]
                result = msg.get("content") or ""
                # Handle reasoning/thinking models (e.g. MIMO, StepFun)
                reasoning = msg.get("reasoning_content") or msg.get("reasoning") or ""
                if not result and reasoning:
                    result = reasoning
                elif result and reasoning:
                    result = f"[思考过程]\n{reasoning}\n\n[回答]\n{result}"
                if use_cache:
                    _cache_set(mid, messages, max_tokens, result)
                return result
            if "candidates" in data:
                _log_call(mid, True, latency)
                result = data["candidates"][0]["content"]["parts"][0]["text"]
                if use_cache:
                    _cache_set(mid, messages, max_tokens, result)
                return result
            err = data.get("error", {}).get("message", json.dumps(data)[:300])
            _log_call(mid, False, latency, err)
            return f"API error [{mid}]: {err}"
        except urllib.error.HTTPError as e:
            body_text = e.read().decode()[:500] if hasattr(e, 'read') else ""
            if e.code == 429 and attempt < 2:
                key = _pick_key(bcfg.get("key_env", ""))  # try different key
                if key:
                    headers["Authorization"] = f"Bearer {key}"
                time.sleep(2 * (attempt + 1))
                continue
            latency = round(time.time() - t0, 2)
            _log_call(mid, False, latency, f"HTTP {e.code}")
            return f"HTTP {e.code} [{mid}]: {body_text}"
        except Exception as e:
            if attempt < 2:
                time.sleep(1)
                continue
            latency = round(time.time() - t0, 2)
            _log_call(mid, False, latency, str(e)[:100])
            return f"Error [{mid}]: {str(e)[:300]}"
    latency = round(time.time() - t0, 2)
    _log_call(mid, False, latency, "retries exhausted")
    return "All retries exhausted"

# --- Helper functions ---
def list_models():
    lines = []
    for bn, bcfg in BACKENDS.items():
        for mn, mi in bcfg["models"].items():
            key_env = bcfg.get("key_env", "")
            has_key = bool(os.environ.get(key_env, "")) if key_env else True
            healthy = _is_healthy(mn)
            if not has_key:
                status = "❌ no key"
            elif not healthy:
                status = "🔴 cooldown"
            else:
                status = "✅"
            lines.append(f"  {mn:20s} {mi['desc']:30s} [{bn}] {status}")
    return "\n".join(lines)

def _all_model_ids():
    mids = []
    for bn, bc in BACKENDS.items():
        for mn in bc["models"]:
            mids.append(mn)
    return mids

def smart_route(prompt):
    """Pick best model based on prompt characteristics (fixed for current backends)."""
    low = prompt.lower()[:500]
    available = [m for m in _all_model_ids() if _model_available(m) and _is_healthy(m)]
    if any(w in low for w in ["code", "function", "class", "def ", "import ", "bug", "refactor", "代码", "函数"]):
        pref = ["glm-flash", "ali-turbo", "sn-llama4", "nv-llama70b", "ds-chat"]
    elif any(w in low for w in ["design", "architecture", "analyze", "explain", "why", "how does", "设计", "分析", "解释"]):
        pref = ["ds-reason", "glm-flash", "ali-qwen", "sn-dsv31", "or-nemo"]
    else:
        pref = ["glm-flash", "ali-turbo", "ali-qwen", "nv-llama70b", "sn-dsv31"]
    return [m for m in pref if m in available] or available[:5]

# --- Search functions ---
def zhihu_search(query, count=5):
    key = os.environ.get("ZHIHU_KEY", "")
    if not key:
        return "Error: ZHIHU_KEY not configured"
    url = "https://developer.zhihu.com/api/v1/content/zhihu_search"
    params = urllib.parse.urlencode({"Query": query, "Count": min(count, 10)})
    full_url = f"{url}?{params}"
    req = urllib.request.Request(full_url, method="GET")
    req.add_header("Authorization", f"Bearer {key}")
    req.add_header("X-Request-Timestamp", str(int(time.time())))
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            if data.get("Code") != 0:
                return f"Zhihu API error: {data.get('Message', 'unknown')}"
            items = data.get("Data", {}).get("Items", [])
            if not items:
                return f"No results for: {query}"
            lines = []
            for i, item in enumerate(items, 1):
                title = item.get("Title", "")
                text = item.get("ContentText", "")[:150]
                item_url = item.get("Url", "").split("?")[0]
                author = item.get("AuthorName", "")
                votes = item.get("VoteUpCount", 0)
                comments = item.get("CommentCount", 0)
                lines.append(f"{i}. [{title}]({item_url})\n   {author} | {votes}赞同 {comments}评论\n   {text}")
            return "\n\n".join(lines)
    except Exception as e:
        return f"Zhihu search error: {str(e)[:200]}"

def global_search(query, count=5, filter_expr="", search_db="all"):
    key = os.environ.get("ZHIHU_KEY", "")
    if not key:
        return "Error: ZHIHU_KEY not configured"
    url = "https://developer.zhihu.com/api/v1/content/global_search"
    p = {"Query": query, "Count": min(count, 20), "SearchDB": search_db}
    if filter_expr:
        p["Filter"] = filter_expr
    full_url = f"{url}?{urllib.parse.urlencode(p)}"
    req = urllib.request.Request(full_url, method="GET")
    req.add_header("Authorization", f"Bearer {key}")
    req.add_header("X-Request-Timestamp", str(int(time.time())))
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            if data.get("Code") != 0:
                return f"Global search error: {data.get('Message', 'unknown')}"
            items = data.get("Data", {}).get("Items", [])
            if not items:
                return f"No results for: {query}"
            lines = []
            for i, item in enumerate(items, 1):
                title = item.get("Title", "")
                text = item.get("ContentText", "")[:200].replace("<em>", "**").replace("</em>", "**")
                item_url = item.get("Url", "").split("?")[0]
                author = item.get("AuthorName", "")
                votes = item.get("VoteUpCount", 0)
                comments = item.get("CommentCount", 0)
                lines.append(f"{i}. [{title}]({item_url})\n   {author} | {votes}赞同 {comments}评论\n   {text}")
            return "\n\n".join(lines)
    except Exception as e:
        return f"Global search error: {str(e)[:200]}"

# --- F2: Health probe ---
_health_probe_results = {}  # mid -> {"ok": bool, "latency": float, "last_check": ts}

def _health_probe():
    """Background thread: probe all models every 5 minutes."""
    while True:
        time.sleep(300)
        for mid in _all_model_ids():
            if not _model_available(mid):
                continue
            try:
                t0 = time.time()
                call_model(mid, [{"role": "user", "content": "hi"}], max_tokens=1, use_cache=False)
                latency = round(time.time() - t0, 2)
                _health_probe_results[mid] = {"ok": True, "latency": latency, "last_check": int(time.time())}
            except Exception as e:
                _health_probe_results[mid] = {"ok": False, "latency": 0, "last_check": int(time.time()),
                                               "error": str(e)[:100]}

# --- F3: ai_compare ---
def ai_compare(prompt, model_ids):
    """Compare responses from multiple models in parallel."""
    model_ids = model_ids[:4]  # max 4
    msgs = [{"role": "user", "content": prompt}]
    results = {}

    def _call(mid):
        t0 = time.time()
        r = call_model(mid, msgs, 2048, use_cache=False)
        return mid, r, round(time.time() - t0, 2)

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(_call, mid): mid for mid in model_ids}
        for fut in as_completed(futures):
            mid, result, lat = fut.result()
            results[mid] = {"result": result, "latency": lat}

    lines = [f"# AI Compare: {prompt[:80]}...\n"]
    for mid in model_ids:
        if mid in results:
            r = results[mid]
            lines.append(f"## [{mid}] ({r['latency']}s)\n{r['result']}\n")
        else:
            lines.append(f"## [{mid}] — failed\n")
    return "\n---\n".join(lines)

# --- F5: Cron scheduler ---
_cron_jobs = {}  # id -> {"cron_expr", "prompt", "model", "notify", "last_run"}
_cron_lock = threading.Lock()

def _parse_cron(expr):
    """Simple cron parser: returns (minute, hour, dom, month, dow) or None."""
    parts = expr.strip().split()
    if len(parts) != 5:
        return None
    return parts

def _cron_match_field(field, value):
    if field == "*":
        return True
    if field.startswith("*/"):
        return value % int(field[2:]) == 0
    return int(field) == value

def _cron_matches(expr, now):
    parts = _parse_cron(expr)
    if not parts:
        return False
    return (_cron_match_field(parts[0], now.tm_min) and
            _cron_match_field(parts[1], now.tm_hour) and
            _cron_match_field(parts[2], now.tm_mday) and
            _cron_match_field(parts[3], now.tm_mon) and
            _cron_match_field(parts[4], now.tm_wday))

def _send_telegram(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        body = json.dumps({"chat_id": TELEGRAM_CHAT_ID, "text": text[:4000], "parse_mode": "Markdown"}).encode()
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        urllib.request.urlopen(req, timeout=10)
    except:
        pass

def _cron_scheduler():
    """Background thread: check cron jobs every 60 seconds."""
    while True:
        time.sleep(60)
        now = time.localtime()
        with _cron_lock:
            for jid, job in _cron_jobs.items():
                if not _cron_matches(job["cron_expr"], now):
                    continue
                last = job.get("last_run", 0)
                if time.time() - last < 120:  # avoid double-fire
                    continue
                job["last_run"] = time.time()
                threading.Thread(target=_run_cron_job, args=(jid, job), daemon=True).start()

def _run_cron_job(jid, job):
    try:
        mid = job.get("model", "glm-flash")
        if not _model_available(mid):
            mid = "glm-flash"
        result = call_model(mid, [{"role": "user", "content": job["prompt"]}], 2048, use_cache=False)
        if job.get("notify"):
            _send_telegram(f"[Cron: {jid}]\n{result[:2000]}")
        _kv_put(f"cron_result_{jid}", json.dumps({"result": result, "ts": int(time.time())}, ensure_ascii=False))
    except Exception as e:
        if job.get("notify"):
            _send_telegram(f"[Cron Error: {jid}] {str(e)[:200]}")

def _save_cron_jobs():
    _kv_put("ai_router_crons", json.dumps(_cron_jobs, ensure_ascii=False))

def _load_cron_jobs():
    global _cron_jobs
    data = _kv_get("ai_router_crons")
    if data:
        try:
            _cron_jobs = json.loads(data)
        except:
            pass

# --- F6: Dashboard HTML ---
DASHBOARD_HTML = """<!DOCTYPE html><html><head><meta charset="utf-8"><title>AI Router v2.1</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:system-ui,-apple-system,sans-serif;background:#0f172a;color:#e2e8f0;padding:20px}
h1{font-size:1.5em;margin-bottom:16px;color:#38bdf8}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px}
.card{background:#1e293b;border-radius:12px;padding:16px;border:1px solid #334155}
.card h2{font-size:1.1em;margin-bottom:12px;color:#94a3b8;text-transform:uppercase;letter-spacing:0.05em;font-weight:600}
.stat{display:flex;justify-content:space-between;padding:4px 0;font-size:0.9em}
.stat .val{color:#38bdf8;font-weight:600}
table{width:100%;border-collapse:collapse;font-size:0.85em}
th{text-align:left;padding:6px 8px;border-bottom:2px solid #334155;color:#94a3b8;font-weight:600}
td{padding:5px 8px;border-bottom:1px solid #1e293b}
.ok{color:#4ade80}.err{color:#f87171}.cool{color:#fbbf24}
.bar{height:6px;border-radius:3px;background:#334155;overflow:hidden;margin-top:2px}
.bar-fill{height:100%;border-radius:3px;background:#38bdf8;transition:width 0.3s}
#refresh{position:fixed;top:12px;right:12px;font-size:0.8em;color:#64748b}
.cron-item{padding:8px 0;border-bottom:1px solid #334155;font-size:0.85em}
</style></head><body>
<h1>AI Router v2.1</h1><div id="refresh">Auto-refresh: 30s</div>
<div class="grid" id="content"></div>
<script>
async function load(){
  try{
    const r=await fetch('/api/stats');const d=await r.json();
    let h='';
    h+='<div class="card"><h2>Overview</h2>';
    h+=`<div class="stat"><span>Uptime</span><span class="val">${d.uptime}</span></div>`;
    h+=`<div class="stat"><span>Total Calls</span><span class="val">${d.total_calls}</span></div>`;
    h+=`<div class="stat"><span>Errors</span><span class="val">${d.total_errors} (${d.error_rate}%)</span></div>`;
    h+=`<div class="stat"><span>Backends</span><span class="val">${d.backends}</span></div>`;
    h+=`<div class="stat"><span>Models</span><span class="val">${d.models_count}</span></div>`;
    h+=`<div class="stat"><span>Cache Hits / Misses</span><span class="val">${d.cache_hits} / ${d.cache_misses}</span></div>`;
    h+=`<div class="stat"><span>Cron Jobs</span><span class="val">${d.cron_count}</span></div>`;
    h+='</div>';
    h+='<div class="card"><h2>Models</h2><table><tr><th>ID</th><th>Backend</th><th>Status</th></tr>';
    for(const m of d.models){
      const cls=m.healthy?(m.has_key?'ok':'err'):'cool';
      const label=m.healthy?(m.has_key?'OK':'No Key'):'Cooldown';
      h+=`<tr><td>${m.id}</td><td>${m.backend}</td><td class="${cls}">${label}</td></tr>`;
    }
    h+='</table></div>';
    h+='<div class="card"><h2>Performance</h2><table><tr><th>Model</th><th>Calls</th><th>Avg Lat</th><th>Err%</th></tr>';
    const perf=Object.entries(d.perf||{}).sort((a,b)=>b[1].calls-a[1].calls).slice(0,20);
    for(const [mid,s] of perf){
      h+=`<tr><td>${mid}</td><td>${s.calls}</td><td>${s.avg_latency}s</td><td>${s.err_rate}%</td></tr>`;
    }
    if(!perf.length)h+='<tr><td colspan=4 style="color:#64748b">No data yet</td></tr>';
    h+='</table></div>';
    h+='<div class="card"><h2>Cron Jobs</h2>';
    if(d.cron_jobs&&d.cron_jobs.length){
      for(const j of d.cron_jobs){
        h+=`<div class="cron-item"><b>${j.id}</b> [${j.cron_expr}] ${j.prompt.slice(0,60)}...</div>`;
      }
    } else { h+='<div style="color:#64748b;font-size:0.9em">No cron jobs configured</div>'; }
    h+='</div>';
    document.getElementById('content').innerHTML=h;
  }catch(e){document.getElementById('content').innerHTML='<div class="card">Loading...</div>';}
}
load();setInterval(load,30000);
</script></body></html>"""

# --- Handler ---
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _send_json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html, code=200):
        body = html.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _get_stats_json(self):
        uptime = int(time.time() - _stats["started"])
        h, m = uptime // 3600, (uptime % 3600) // 60
        perf = {}
        for mid, s in _stats["models"].items():
            avg_lat = round(s["total_latency"] / max(s["calls"], 1), 1)
            err_rate = round(s["errors"] / max(s["calls"], 1) * 100, 1)
            perf[mid] = {"calls": s["calls"], "avg_latency": avg_lat, "err_rate": err_rate}
        models_list = []
        for bn, bcfg in BACKENDS.items():
            for mn, mi in bcfg["models"].items():
                key_env = bcfg.get("key_env", "")
                has_key = bool(os.environ.get(key_env, "")) if key_env else True
                models_list.append({"id": mn, "backend": bn, "desc": mi["desc"],
                                    "has_key": has_key, "healthy": _is_healthy(mn)})
        cron_list = [{"id": jid, "cron_expr": j["cron_expr"], "prompt": j.get("prompt", ""),
                       "model": j.get("model", ""), "notify": j.get("notify", False)}
                      for jid, j in _cron_jobs.items()]
        total = max(_stats["total_calls"], 1)
        return {
            "version": "2.1.0", "uptime": f"{h}h{m}m",
            "total_calls": _stats["total_calls"], "total_errors": _stats["total_errors"],
            "error_rate": round(_stats["total_errors"] / total * 100, 1),
            "backends": len(BACKENDS), "models_count": len(models_list),
            "cache_hits": _stats["cache_hits"], "cache_misses": _stats["cache_misses"],
            "cron_count": len(_cron_jobs), "models": models_list,
            "perf": perf, "cron_jobs": cron_list,
        }

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/":
            self._send_html(DASHBOARD_HTML)
        elif path == "/health":
            health = {}
            for mid in _all_model_ids():
                h = _model_health.get(mid, {})
                unhealthy_until = h.get("unhealthy_until", 0)
                healthy = time.time() > unhealthy_until if unhealthy_until else True
                probe = _health_probe_results.get(mid, {})
                health[mid] = {"healthy": healthy, "failures": h.get("failures", 0),
                               "probe_latency": probe.get("latency", 0)}
            self._send_json({"status": "ok", "models": health, "ts": int(time.time())})
        elif path == "/v1/models":
            models = []
            for bn, bcfg in BACKENDS.items():
                for mn, mi in bcfg["models"].items():
                    models.append({"id": mn, "object": "model", "created": int(_stats["started"]),
                                   "owned_by": bn, "description": mi["desc"]})
            self._send_json({"object": "list", "data": models})
        elif path == "/api/stats":
            self._send_json(self._get_stats_json())
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        path = self.path.split("?")[0]
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length else {}
        except Exception as e:
            self._send_json({"error": str(e)}, 400)
            return

        if path == "/v1/chat/completions":
            self._handle_openai(body)
            return

        method = body.get("method", "")
        params = body.get("params", {})
        result = {}

        if method == "initialize":
            result = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                      "serverInfo": {"name": "ai-router", "version": "2.1.0"}}
        elif method == "tools/list":
            result = {"tools": self._tool_defs()}
        elif method == "tools/call":
            args = params.get("arguments", {})
            name = params.get("name", "")
            try:
                txt = self._dispatch_tool(name, args)
            except Exception as e:
                txt = f"Tool error: {str(e)[:500]}"
            result = {"content": [{"type": "text", "text": txt}]}
        else:
            result = {}

        resp = json.dumps({"jsonrpc": "2.0", "result": result, "id": body.get("id", 0)}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(resp)

    def _tool_defs(self):
        return [
            {"name": "ai_ask", "description": "Ask a specific AI model. Use ai_models to see available models.",
             "inputSchema": {"type": "object", "properties": {
                 "model": {"type": "string", "description": "Model ID (e.g. glm-flash, ds-chat)"},
                 "prompt": {"type": "string", "description": "Your question"},
                 "max_tokens": {"type": "integer", "default": 2048}}, "required": ["model", "prompt"]}},
            {"name": "ai_auto", "description": "Smart routing: auto-picks best model for the task.",
             "inputSchema": {"type": "object", "properties": {
                 "prompt": {"type": "string", "description": "Your question"}}, "required": ["prompt"]}},
            {"name": "ai_compare", "description": "Compare multiple AI models side-by-side with the same prompt.",
             "inputSchema": {"type": "object", "properties": {
                 "prompt": {"type": "string", "description": "Your question"},
                 "models": {"type": "array", "items": {"type": "string"},
                            "description": "Model IDs to compare (max 4)"}}, "required": ["prompt", "models"]}},
            {"name": "ai_models", "description": "List all available models and their status."},
            {"name": "ai_stats", "description": "Show usage statistics, cache stats, and model health."},
            {"name": "ai_cron", "description": "Manage scheduled AI tasks.",
             "inputSchema": {"type": "object", "properties": {
                 "action": {"type": "string", "enum": ["add", "remove", "list", "run"]},
                 "id": {"type": "string"}, "cron": {"type": "string"},
                 "prompt": {"type": "string"}, "model": {"type": "string"},
                 "notify": {"type": "boolean"}}, "required": ["action"]}},
            {"name": "zhihu_search", "description": "Search Zhihu for articles, answers, and discussions.",
             "inputSchema": {"type": "object", "properties": {
                 "query": {"type": "string"}, "count": {"type": "integer", "default": 5}}, "required": ["query"]}},
            {"name": "global_search", "description": "Search across the web via Zhihu.",
             "inputSchema": {"type": "object", "properties": {
                 "query": {"type": "string"}, "count": {"type": "integer", "default": 5},
                 "filter": {"type": "string"}, "search_db": {"type": "string", "default": "all"}}, "required": ["query"]}},
            {"name": "zhihu_zhida", "description": "Ask Zhihu Zhida AI.",
             "inputSchema": {"type": "object", "properties": {
                 "prompt": {"type": "string"},
                 "model": {"type": "string", "default": "zd-thinking"}}, "required": ["prompt"]}},
        ]

    def _dispatch_tool(self, name, args):
        if name == "ai_models":
            return list_models()
        elif name == "ai_stats":
            uptime = int(time.time() - _stats["started"])
            h, m = uptime // 3600, (uptime % 3600) // 60
            cache_total = max(_stats["cache_hits"] + _stats["cache_misses"], 1)
            cache_rate = round(_stats["cache_hits"] / cache_total * 100, 1)
            lines = [f"AI Router v2.1 | Uptime: {h}h{m}m",
                     f"Total calls: {_stats['total_calls']} | Errors: {_stats['total_errors']}",
                     f"Error rate: {round(_stats['total_errors']/max(_stats['total_calls'],1)*100, 1)}%",
                     f"Cache: {_stats['cache_hits']} hits / {_stats['cache_misses']} misses ({cache_rate}% hit rate)",
                     "", "Model Performance:"]
            for mid, s in sorted(_stats["models"].items(), key=lambda x: -x[1]["calls"]):
                avg_lat = round(s["total_latency"] / max(s["calls"], 1), 1)
                err_rate = round(s["errors"] / max(s["calls"], 1) * 100, 1)
                healthy = "✅" if _is_healthy(mid) else "🔴 cooldown"
                lines.append(f"  {mid:20s} {s['calls']:>4} calls  {avg_lat:>5.1f}s avg  {err_rate:>4.0f}% err  {healthy}")
            if not _stats["models"]:
                lines.append("  (no calls yet)")
            if _cron_jobs:
                lines.append(f"\nCron jobs: {len(_cron_jobs)}")
                for jid, j in _cron_jobs.items():
                    lines.append(f"  {jid}: [{j['cron_expr']}] {j.get('prompt','')[:50]}")
            return "\n".join(lines)
        elif name == "ai_auto":
            candidates = smart_route(args.get("prompt", ""))
            msgs = [{"role": "user", "content": args.get("prompt", "")}]
            txt = None
            for mid in candidates:
                r = call_model(mid, msgs, args.get("max_tokens", 2048))
                if not r.startswith(("Unknown model", "HTTP 4", "Error", "All retries")):
                    txt = f"[Auto-routed to: {mid}]\n\n" + r
                    break
            return txt or f"[All candidates failed: {candidates}]"
        elif name == "ai_ask":
            return call_model(args.get("model", "ds-chat"),
                              [{"role": "user", "content": args.get("prompt", "")}],
                              args.get("max_tokens", 2048))
        elif name == "ai_compare":
            return ai_compare(args.get("prompt", ""), args.get("models", []))
        elif name == "ai_cron":
            return self._handle_cron(args)
        elif name == "zhihu_search":
            return zhihu_search(args.get("query", ""), args.get("count", 5))
        elif name == "global_search":
            return global_search(args.get("query", ""), args.get("count", 5),
                                 args.get("filter", ""), args.get("search_db", "all"))
        elif name == "zhihu_zhida":
            return call_model(args.get("model", "zd-thinking"),
                              [{"role": "user", "content": args.get("prompt", "")}], 4096)
        return f"Unknown tool: {name}"

    def _handle_cron(self, args):
        action = args.get("action", "list")
        if action == "list":
            if not _cron_jobs:
                return "No cron jobs configured."
            lines = ["Cron Jobs:"]
            for jid, j in _cron_jobs.items():
                lines.append(f"  {jid}: [{j['cron_expr']}] model={j.get('model','glm-flash')} notify={j.get('notify',False)}")
                lines.append(f"    prompt: {j.get('prompt','')[:100]}")
            return "\n".join(lines)
        elif action == "add":
            jid = args.get("id", f"job-{len(_cron_jobs)+1}")
            cron_expr = args.get("cron", "")
            prompt = args.get("prompt", "")
            if not cron_expr or not prompt:
                return "Error: 'cron' and 'prompt' are required for add"
            if not _parse_cron(cron_expr):
                return f"Error: invalid cron expression '{cron_expr}'. Format: min hour dom month dow"
            with _cron_lock:
                _cron_jobs[jid] = {"cron_expr": cron_expr, "prompt": prompt,
                                    "model": args.get("model", "glm-flash"),
                                    "notify": args.get("notify", False), "last_run": 0}
            _save_cron_jobs()
            return f"Cron job '{jid}' added: [{cron_expr}]"
        elif action == "remove":
            jid = args.get("id", "")
            with _cron_lock:
                if jid in _cron_jobs:
                    del _cron_jobs[jid]
                    _save_cron_jobs()
                    return f"Cron job '{jid}' removed."
                return f"Error: job '{jid}' not found"
        elif action == "run":
            jid = args.get("id", "")
            with _cron_lock:
                job = _cron_jobs.get(jid)
            if not job:
                return f"Error: job '{jid}' not found"
            threading.Thread(target=_run_cron_job, args=(jid, job), daemon=True).start()
            return f"Cron job '{jid}' triggered."
        return f"Unknown cron action: {action}"

    def _handle_openai(self, body):
        model_id = body.get("model", "glm-flash")
        messages = body.get("messages", [{"role": "user", "content": "hello"}])
        max_tokens = body.get("max_tokens", 2048)
        result_text = call_model(model_id, messages, max_tokens)
        response = {
            "id": f"chatcmpl-{int(time.time())}", "object": "chat.completion",
            "created": int(time.time()), "model": model_id,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": result_text},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        }
        self._send_json(response)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8769
    print(f"AI Router v2.1 — {len(BACKENDS)} backends, port {port}")
    for bn, bcfg in BACKENDS.items():
        key_env = bcfg.get("key_env", "")
        has_key = bool(os.environ.get(key_env, "")) if key_env else True
        n = len(bcfg["models"])
        print(f"  {'✅' if has_key else '❌'} {bn}: {n} models")
    threading.Thread(target=_health_probe, daemon=True).start()
    threading.Thread(target=_cron_scheduler, daemon=True).start()
    _load_cron_jobs()
    print("Background: health probe (5min), cron scheduler started")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
