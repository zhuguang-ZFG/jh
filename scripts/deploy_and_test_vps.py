#!/usr/bin/env python3
"""Deploy ai_router_mcp.py + .env to VPS and run backend tests there."""
import paramiko, os, sys, time

VPS_HOST = "119.45.204.198"
VPS_USER = "root"
VPS_PASS = "zhuguang110!"
REMOTE_DIR = "/opt/ai-router"

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def ssh_exec(client, cmd, timeout=60):
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    return code, out, err

def main():
    # Connect
    print(f"Connecting to {VPS_HOST}...")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(VPS_HOST, username=VPS_USER, password=VPS_PASS, timeout=15)
    print("Connected!")

    # Create remote dir
    ssh_exec(client, f"mkdir -p {REMOTE_DIR}")

    # Upload files
    sftp = client.open_sftp()
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    for fname in ["ai_router_mcp.py", ".env.ai_router"]:
        local = os.path.join(project_root, fname)
        remote = f"{REMOTE_DIR}/{fname}"
        print(f"  Upload {fname} -> {remote}")
        sftp.put(local, remote)
    sftp.close()

    # Run test on VPS
    print("\nRunning backend tests on VPS...")
    test_script = '''
import json, time, urllib.request, urllib.error, os, sys
sys.path.insert(0, "/opt/ai-router")
os.chdir("/opt/ai-router")

# Load env
with open("/opt/ai-router/.env.ai_router", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            if v and k not in os.environ:
                os.environ[k.strip()] = v.strip()

PROXY = "http://127.0.0.1:7890"
TEST_MSG = [{"role": "user", "content": "Say hello in one word."}]

TESTS = [
    ("groq",        "https://api.groq.com/openai/v1/chat/completions",                              "GROQ_KEY",       "llama-3.3-70b-versatile", True),
    ("cerebras",    "https://api.cerebras.ai/v1/chat/completions",                                   "CEREBRAS_KEY",   "qwen-2.5-coder-32b-instruct", True),
    ("google_ai",   "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",      "GOOGLE_AI_KEY",  "gemini-2.0-flash-lite", True),
    ("mistral",     "https://api.mistral.ai/v1/chat/completions",                                    "MISTRAL_KEY",    "mistral-small-latest", True),
    ("siliconflow", "https://api.siliconflow.cn/v1/chat/completions",                                "SILICONFLOW_KEY","Qwen/Qwen2.5-7B-Instruct", False),
    ("zhipu",       "https://open.bigmodel.cn/api/paas/v4/chat/completions",                         "ZHIPU_KEY",      "glm-4-flash", False),
    ("baidu",       "https://qianfan.baidubce.com/v2/chat/completions",                              "BAIDU_KEY",      "ernie_speed", False),
    ("tencent",     "https://api.hunyuan.cloud.tencent.com/v1/chat/completions",                     "TENCENT_KEY",    "hunyuan-lite", False),
    ("volcano",     "https://ark.cn-beijing.volces.com/api/v3/chat/completions",                     "VOLCANO_KEY",    "doubao-1.5-pro-32k", False),
    ("aliyun",      "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",            "ALIYUN_KEY",     "qwen-turbo", False),
    ("nagaai",      "https://api.nagaai.com/v1/chat/completions",                                    "NAGAAI_KEY",     "gpt-4.1-mini:free", True),
    ("freetheai",   "https://api.freetheai.xyz/v1/chat/completions",                                 "FREETHEAI_KEY",  "bbl/gpt-4.1", True),
    ("featherless", "https://api.featherless.ai/v1/chat/completions",                                "FEATHERLESS_KEY","meta-llama/Llama-3.3-70B-Instruct", True),
    ("cf_workers",  "https://api.cloudflare.com/client/v4/accounts/3e8dfc378deaf1a6f39fda85ceaca32b/ai/v1/chat/completions", "CF_AI_TOKEN", "@cf/meta/llama-3.3-70b-instruct-fp8-fast", True),
]

print(f"{'Backend':<16} {'Model':<35} {'Status':<8} {'Time':>5}  Detail")
print("-" * 100)
ok = fail = skip = 0
for name, url, key_env, model, use_proxy in TESTS:
    key = os.environ.get(key_env, "") if key_env else ""
    if key_env and not key:
        skip += 1
        print(f"{name:<16} {model:<35} {'SKIP':<8} {'-':>5}  no key")
        continue

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
            reply = ""
            if "choices" in data:
                reply = data["choices"][0]["message"]["content"][:60]
            elif "candidates" in data:
                reply = data["candidates"][0]["content"]["parts"][0]["text"][:60]
            ok += 1
            print(f"{name:<16} {model:<35} {'OK':<8} {elapsed:>4.1f}s  {reply}")
    except urllib.error.HTTPError as e:
        elapsed = time.time() - t0
        body_text = ""
        try: body_text = e.read().decode()[:120]
        except: pass
        fail += 1
        print(f"{name:<16} {model:<35} {'H'+str(e.code):<8} {elapsed:>4.1f}s  {body_text}")
    except Exception as e:
        elapsed = time.time() - t0
        fail += 1
        print(f"{name:<16} {model:<35} {'ERR':<8} {elapsed:>4.1f}s  {str(e)[:100]}")

print("-" * 100)
print(f"Result: {ok} OK, {fail} FAIL, {skip} SKIP")
'''

    code, out, err = ssh_exec(client, f'python3 -c """{test_script}"""', timeout=120)
    print(out)
    if err:
        print("STDERR:", err[:500])

    # Also check what AI backends are already running on VPS
    print("\n--- Existing AI services on VPS ---")
    code, out, err = ssh_exec(client, "ps aux | grep -E 'python.*ai|node.*ai|ollama' | grep -v grep | head -10")
    print(out)

    code, out, err = ssh_exec(client, "ss -tlnp | grep -E '8769|8080|11434' | head -5")
    print(out)

    client.close()
    print("Done!")

if __name__ == "__main__":
    main()
