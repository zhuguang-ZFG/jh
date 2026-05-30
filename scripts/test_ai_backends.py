#!/usr/bin/env python3
"""Test all AI Router backends — checks key validity, response quality, speed."""
import json, time, urllib.request, urllib.error, os, sys

# Load env — look in script dir first, then parent (project root)
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
for d in [script_dir, project_root]:
    env_path = os.path.join(d, ".env.ai_router")
    if os.path.exists(env_path):
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    if v and k not in os.environ:
                        os.environ[k.strip()] = v.strip()
        break

PROXY = os.environ.get("HTTP_PROXY", "http://127.0.0.1:7890")
TEST_MSG = [{"role": "user", "content": "Say 'hello' in one word."}]

# All backends to test
TESTS = [
    # (backend_name, url, key_env, model_name, use_proxy, account_env)
    ("groq",        "https://api.groq.com/openai/v1/chat/completions",                              "GROQ_KEY",       "llama-3.3-70b-versatile", True),
    ("cerebras",    "https://api.cerebras.ai/v1/chat/completions",                                   "CEREBRAS_KEY",   "qwen-2.5-coder-32b-instruct", True),
    ("google_ai",   "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",      "GOOGLE_AI_KEY",  "gemini-2.0-flash-lite", True),
    ("mistral",     "https://api.mistral.ai/v1/chat/completions",                                    "MISTRAL_KEY",    "mistral-small-latest", True),
    ("siliconflow", "https://api.siliconflow.cn/v1/chat/completions",                                "SILICONFLOW_KEY","THUDM/glm-4-9b-chat", False),
    ("zhipu",       "https://open.bigmodel.cn/api/paas/v4/chat/completions",                         "ZHIPU_KEY",      "glm-4-flash", False),
    ("baidu",       "https://qianfan.baidubce.com/v2/chat/completions",                              "BAIDU_KEY",      "ernie-speed-128k", False),
    ("tencent",     "https://api.hunyuan.cloud.tencent.com/v1/chat/completions",                     "TENCENT_KEY",    "hunyuan-lite", False),
    ("volcano",     "https://ark.cn-beijing.volces.com/api/v3/chat/completions",                     "VOLCANO_KEY",    "doubao-1.5-pro-32k", False),
    ("aliyun",      "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",            "ALIYUN_KEY",     "qwen-turbo", False),
    ("nagaai",      "https://api.nagaai.com/v1/chat/completions",                                    "NAGAAI_KEY",     "gpt-4.1-mini:free", True),
    ("freetheai",   "https://api.freetheai.xyz/v1/chat/completions",                                 "FREETHEAI_KEY",  "bbl/gpt-4.1", True),
    ("featherless", "https://api.featherless.ai/v1/chat/completions",                                "FEATHERLESS_KEY","meta-llama/Llama-3.3-70B-Instruct", True),
    ("cf_workers",  "https://api.cloudflare.com/client/v4/accounts/{account}/ai/v1/chat/completions", "CF_AI_TOKEN",   "@cf/meta/llama-3.3-70b-instruct-fp8-fast", True),
    ("pollinations","https://text.pollinations.ai/openai",                                           "",               "openai", False),
    ("llm7",        "https://api.llm7.io/v1/chat/completions",                                      "",               "deepseek-r1", False),
]


def test_backend(name, url, key_env, model, use_proxy, account_env=None):
    key = os.environ.get(key_env, "") if key_env else ""
    if key_env and not key:
        return {"status": "SKIP", "reason": "no key", "time": 0}

    if account_env and "{account}" in url:
        account = os.environ.get(account_env, "")
        if not account:
            return {"status": "SKIP", "reason": "no account ID", "time": 0}
        url = url.format(account=account)

    body = json.dumps({"model": model, "messages": TEST_MSG, "max_tokens": 32}).encode()
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"

    proxy_handler = urllib.request.ProxyHandler({"https": PROXY, "http": PROXY} if use_proxy else {})
    opener = urllib.request.build_opener(proxy_handler)
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")

    t0 = time.time()
    try:
        with opener.open(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
            elapsed = time.time() - t0
            # Extract response
            reply = ""
            if "choices" in data:
                reply = data["choices"][0]["message"]["content"][:80]
            elif "candidates" in data:
                reply = data["candidates"][0]["content"]["parts"][0]["text"][:80]
            elif "result" in data:
                reply = str(data["result"])[:80]
            return {"status": "OK", "time": round(elapsed, 1), "reply": reply}
    except urllib.error.HTTPError as e:
        elapsed = time.time() - t0
        body_text = ""
        try:
            body_text = e.read().decode()[:200]
        except:
            pass
        return {"status": f"ERR {e.code}", "time": round(elapsed, 1), "reason": body_text}
    except Exception as e:
        elapsed = time.time() - t0
        return {"status": "ERR", "time": round(elapsed, 1), "reason": str(e)[:200]}


def main():
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(f"{'Backend':<16} {'Model':<35} {'Status':<10} {'Time':>5}  {'Detail'}")
    print("-" * 110)

    ok, fail, skip = 0, 0, 0
    for name, url, key_env, model, use_proxy in TESTS:
        account_env = "CF_ACCOUNT" if "cloudflare" in url else None
        result = test_backend(name, url, key_env, model, use_proxy, account_env)

        if result["status"] == "OK":
            ok += 1
            print(f"{name:<16} {model:<35} {'OK':<10} {result['time']:>4.1f}s  {result.get('reply', '')[:50]}")
        elif result["status"] == "SKIP":
            skip += 1
            print(f"{name:<16} {model:<35} {'SKIP':<10} {'-':>5}   {result.get('reason', '')}")
        else:
            fail += 1
            print(f"{name:<16} {model:<35} {'FAIL':<10} {result['time']:>4.1f}s  {result.get('reason', '')[:60]}")

    print("-" * 110)
    print(f"Total: {ok} OK, {fail} FAIL, {skip} SKIP (no key)")


if __name__ == "__main__":
    main()
