"""Shared functions for evo hooks — extraction, API calls, transcript parsing.

Used by both evo_hook_stop.py (session end) and evo_hook_post_tool.py (periodic flush).
"""
import json
import os
import re
import tempfile
import urllib.request
from collections import Counter

SERVER = os.getenv("EVO_SERVER", "http://119.45.204.198")
API_KEY = os.getenv("EVO_API_KEY", "")
TRACKER_FILE = os.path.join(tempfile.gettempdir(), "evo_changed_files.json")


def api(method, path, data=None):
    url = f"{SERVER}{path}"
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(
        url, data=body, method=method,
        headers={"Content-Type": "application/json"},
    )
    if API_KEY:
        req.add_header("Authorization", f"Bearer {API_KEY}")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception:
        return {"ok": False}


def parse_transcript(transcript_path):
    """Parse Claude Code JSONL transcript to extract session intelligence."""
    if not transcript_path or not os.path.isfile(transcript_path):
        return None

    result = {
        "tool_counts": {},
        "files_edited": [],
        "files_written": [],
        "bash_commands": [],
        "bash_patterns": [],
        "edit_details": [],
        "write_details": [],
        "read_files": [],
        "errors_encountered": [],
        "user_messages": [],
        "total_tool_calls": 0,
    }

    try:
        with open(transcript_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue

                msg_type = d.get("type", "")

                if msg_type == "user":
                    msg = d.get("message", {})
                    content = msg.get("content", "")
                    if isinstance(content, str) and len(content) > 5:
                        result["user_messages"].append(content[:200])

                if msg_type == "assistant":
                    msg = d.get("message", {})
                    content = msg.get("content", [])
                    if not isinstance(content, list):
                        continue
                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        if block.get("type") != "tool_use":
                            continue

                        name = block.get("name", "")
                        inp = block.get("input", {})
                        result["tool_counts"][name] = result["tool_counts"].get(name, 0) + 1
                        result["total_tool_calls"] += 1

                        if name == "Bash":
                            cmd = inp.get("command", "")
                            if cmd and len(cmd) > 3:
                                result["bash_commands"].append(cmd[:200])
                                root = cmd.split()[0] if cmd.split() else ""
                                if root not in ("cd", "echo", "ls", "cat", "pwd", "mkdir", ""):
                                    result["bash_patterns"].append({
                                        "root": root,
                                        "full": cmd[:150],
                                    })

                        elif name == "Write":
                            fp = inp.get("file_path", "")
                            if fp:
                                result["files_edited"].append(fp)
                                result["files_written"].append(fp)
                                content_preview = inp.get("content", "")[:300]
                                result["write_details"].append({
                                    "file": fp,
                                    "preview": content_preview,
                                })

                        elif name == "Edit":
                            fp = inp.get("file_path", "")
                            if fp:
                                result["files_edited"].append(fp)
                                old_str = inp.get("old_string", "")[:150]
                                new_str = inp.get("new_string", "")[:150]
                                result["edit_details"].append({
                                    "file": fp,
                                    "old": old_str,
                                    "new": new_str,
                                })

                        elif name == "Read":
                            fp = inp.get("file_path", "")
                            if fp:
                                result["read_files"].append(fp)
                            if "error" in str(inp).lower():
                                result["errors_encountered"].append(str(inp)[:100])

    except (IOError, OSError):
        return None

    return result


def infer_domain(changed_files):
    """Infer domain from changed file extensions/paths."""
    exts = {}
    for f in changed_files:
        ext = f.rsplit(".", 1)[-1] if "." in f else ""
        exts[ext] = exts.get(ext, 0) + 1

    if not exts:
        return "general"

    top_ext = max(exts, key=exts.get)
    ext_map = {
        "py": "python", "rs": "rust", "go": "go",
        "ts": "typescript", "tsx": "react", "jsx": "react",
        "js": "javascript", "vue": "frontend",
        "sql": "data", "yml": "devops", "yaml": "devops",
        "json": "config", "toml": "config",
    }
    return ext_map.get(top_ext, "general")


def _is_noise_message(msg):
    text = msg.lower().strip()
    noise_prefixes = [
        "<local-command-caveat>", "<system-reminder>", "<command-name>",
        "note:", "warning:", "error:",
    ]
    for p in noise_prefixes:
        if text.startswith(p):
            return True
    if any(k in text for k in ("实例id", "实例规格", "uuid", "instance id", "instance type")):
        return True
    if any(k in text for k in ("workers 日志", "workers 跟踪", "workers 日",
                                 "可观察性", "仪表板", "定义环境变量", "runtime variables",
                                 "observability", "configure api tokens")):
        return True
    if len(text) < 8:
        return True
    has_cjk = bool(re.search(r"[一-鿿]", text))
    if " " not in text and not has_cjk:
        return True
    if len(text) > 120:
        convo_words = ["i ", "let's", "we ", "you ", "do ", "should", "can ",
                       "want", "need", "help", "用", "我", "你", "帮", "做"]
        has_convo = any(w in text for w in convo_words)
        struct_lines = text.count("\n")
        has_structure = struct_lines >= 3 and ("：" in text or ":" in text)
        if has_structure and not has_convo:
            return True
    return False


def _is_credential_content(text):
    lower = text.lower()
    secret_keywords = [
        "api_key", "api-key", "apikey", "api key",
        "token", "secret", "password", "passwd", "pwd",
        "credential", "auth_token", "access_key",
        "private_key", "ssh_key", "ssh key",
    ]
    for kw in secret_keywords:
        if kw in lower:
            if re.search(r"[A-Za-z0-9_\-]{20,}", text):
                return True
    if re.search(r"\b[A-Fa-f0-9]{32,}\b", text):
        return True
    if re.search(r"\b(AKIA[A-Z0-9]{16}|sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{36})", text):
        return True
    return False


def extract_skills(transcript_data, changed_files, outcome):
    """Extract meaningful skills from parsed transcript data."""
    skills = []
    if not transcript_data:
        return skills

    domain = infer_domain(changed_files)
    tool_counts = transcript_data.get("tool_counts", {})
    bash_patterns = transcript_data.get("bash_patterns", [])
    files_edited = transcript_data.get("files_edited", [])
    files_written = transcript_data.get("files_written", [])
    edit_details = transcript_data.get("edit_details", [])
    write_details = transcript_data.get("write_details", [])

    # Deployment patterns from Bash
    deploy_keywords = {
        "scp": "file transfer", "ssh": "remote execution",
        "systemctl": "service management", "docker": "containerization",
        "nginx": "web server config", "git push": "code push",
        "git commit": "version control", "pip install": "python dependency",
        "npm install": "js dependency", "pytest": "python testing",
        "jest": "js testing", "curl": "api testing",
        "python -m uvicorn": "server startup", "python -m fastapi": "fastapi usage",
    }
    found_deploy = {}
    for bp in bash_patterns:
        full = bp["full"].lower()
        for kw, label in deploy_keywords.items():
            if kw in full and label not in found_deploy:
                found_deploy[label] = bp["full"]
    for label, example in list(found_deploy.items())[:3]:
        skills.append({
            "name": f"deploy_{label.replace(' ', '_')[:30]}",
            "domain": domain,
            "pattern": f"Deployment: {label} -- used: {example[:120]}",
            "weight": 0.9,
        })

    # New modules created
    for wd in write_details[:3]:
        fp = wd["file"]
        preview = wd["preview"]
        basename = os.path.basename(fp)
        if "class " in preview:
            cls_match = re.search(r"class\s+(\w+)", preview)
            cls_name = cls_match.group(1) if cls_match else basename
            skills.append({
                "name": f"created_class_{cls_name[:25]}",
                "domain": domain,
                "pattern": f"Created class {cls_name} in {basename}",
                "weight": 1.0,
            })
        elif "def " in preview:
            func_match = re.search(r"def\s+(\w+)", preview)
            func_name = func_match.group(1) if func_match else basename
            skills.append({
                "name": f"created_func_{func_name[:25]}",
                "domain": domain,
                "pattern": f"Created function {func_name} in {basename}",
                "weight": 0.9,
            })
        elif "router" in preview.lower() or "app." in preview.lower():
            skills.append({
                "name": f"created_router_{basename[:25]}",
                "domain": domain,
                "pattern": f"Created API router in {basename}",
                "weight": 0.9,
            })
        elif "import" in preview:
            skills.append({
                "name": f"created_module_{basename[:25]}",
                "domain": domain,
                "pattern": f"Created new module {basename}",
                "weight": 0.8,
            })

    # Edit patterns
    edit_categories = Counter()
    edit_examples = {}
    for ed in edit_details[:20]:
        new_text = ed["new"]
        old_text = ed["old"]
        basename = os.path.basename(ed["file"])
        if "import" in new_text and "import" not in old_text:
            edit_categories["added_import"] += 1
            edit_examples["added_import"] = f"Added import in {basename}"
        elif "def " in new_text and "def " not in old_text:
            edit_categories["added_function"] += 1
            edit_examples["added_function"] = f"Added function in {basename}"
        elif "class " in new_text and "class " not in old_text:
            edit_categories["added_class"] += 1
            edit_examples["added_class"] = f"Added class in {basename}"
        elif "Body(" in new_text:
            edit_categories["fixed_body_annotation"] += 1
            edit_examples["fixed_body_annotation"] = f"Fixed Body() annotation in {basename}"
        elif "@router" in new_text:
            edit_categories["added_route"] += 1
            edit_examples["added_route"] = f"Added route in {basename}"
        elif "return" in new_text and "return" not in old_text:
            edit_categories["added_return"] += 1
            edit_examples["added_return"] = f"Added return statement in {basename}"

    for cat, count in edit_categories.most_common(3):
        if count >= 2:
            skills.append({
                "name": f"edit_pattern_{cat[:30]}",
                "domain": domain,
                "pattern": f"Repeated edit pattern: {cat} ({count}x) -- {edit_examples.get(cat, '')}",
                "weight": 0.8,
            })

    # Bash command clusters
    cmd_roots = [bp["root"] for bp in bash_patterns]
    cmd_counts = Counter(cmd_roots)
    for cmd, count in cmd_counts.most_common(3):
        if count >= 2 and cmd not in ("cd", "echo", "ls", "cat", "pwd", "mkdir"):
            sample = next((bp["full"] for bp in bash_patterns if bp["root"] == cmd), cmd)
            skills.append({
                "name": f"bash_{cmd.replace('/', '_').replace('-', '_')[:30]}",
                "domain": domain,
                "pattern": f"Repeated: {cmd} ({count}x) -- e.g. {sample[:100]}",
                "weight": 0.7,
            })

    # Framework detection
    frameworks = set()
    all_text = " ".join([
        bp["full"] for bp in bash_patterns
    ] + [wd.get("preview", "") for wd in write_details]).lower()
    for fw in ("fastapi", "flask", "django", "react", "vue", "express",
                "gin", "axum", "actix", "uvicorn", "pytest", "jest",
                "apscheduler", "httpx", "pydantic", "sqlalchemy"):
        if fw in all_text:
            frameworks.add(fw)
    for fw in list(frameworks)[:3]:
        skills.append({
            "name": f"framework_{fw}",
            "domain": domain,
            "pattern": f"Framework used: {fw}",
            "weight": 0.9,
        })

    # Session summary
    file_count = len(set(files_edited))
    write_count = len(files_written)
    edit_count = len(edit_details)
    bash_count = len(bash_patterns)
    if file_count > 0:
        basenames = list(set(os.path.basename(f) for f in files_edited))[:5]
        skills.append({
            "name": f"session_{domain}_{file_count}files",
            "domain": domain,
            "pattern": f"Session: {file_count} files ({', '.join(basenames)}), {write_count} new, {edit_count} edits, {bash_count} commands",
            "weight": 1.0 if outcome == "success" else 0.5,
        })

    # Error recovery
    if outcome == "success" and transcript_data.get("errors_encountered"):
        skills.append({
            "name": f"error_recovery_{domain}",
            "domain": domain,
            "pattern": f"Recovered from {len(transcript_data['errors_encountered'])} errors",
            "weight": 0.8,
        })

    # Deduplicate
    seen = set()
    unique = []
    for s in skills:
        key = s["name"][:25]
        if key not in seen:
            seen.add(key)
            unique.append(s)
    return unique[:10]


def extract_memories(transcript_data, changed_files, outcome, domain):
    """Extract key memories from a session for cross-session recall."""
    if not transcript_data:
        return []

    memories = []

    # Decisions
    user_msgs = transcript_data.get("user_messages", [])
    decision_keywords = ["用", "选择", "决定", "偏好", "不要", "别用",
                         "prefer", "use", "choose", "don't", "avoid"]
    for msg in user_msgs:
        if _is_noise_message(msg):
            continue
        if _is_credential_content(msg):
            continue
        text = msg.lower()
        for kw in decision_keywords:
            if kw in text and len(msg) > 15:
                memories.append({
                    "category": "decision",
                    "content": msg[:200],
                    "domain": domain,
                    "confidence": 0.7,
                })
                break
        if len(memories) >= 2:
            break

    # Lessons from errors
    errors = transcript_data.get("errors_encountered", [])
    if errors and outcome == "success":
        for err in errors[:2]:
            err_text = err if isinstance(err, str) else str(err)
            if len(err_text) > 30 and not _is_noise_message(err_text) and not _is_credential_content(err_text):
                memories.append({
                    "category": "lesson",
                    "content": f"Error encountered and resolved: {err_text[:200]}",
                    "domain": domain,
                    "confidence": 0.8,
                })
        if len(memories) >= 4:
            pass

    # Context
    file_count = len(changed_files)
    if file_count >= 3:
        basenames = [os.path.basename(f) for f in changed_files[:5]]
        memories.append({
            "category": "context",
            "content": f"Session modified {file_count} files: {', '.join(basenames)}",
            "domain": domain,
            "confidence": 0.6,
        })

    # Deduplicate
    seen = set()
    unique = []
    for m in memories:
        key = m["content"][:40]
        if key not in seen:
            seen.add(key)
            unique.append(m)
    return unique[:5]


def read_changed_files():
    """Read and return tracked changed files from temp file."""
    if os.path.exists(TRACKER_FILE):
        try:
            with open(TRACKER_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return []


def get_session_id():
    """Get or create a stable session ID for the current Claude Code session."""
    state_file = os.path.join(tempfile.gettempdir(), "evo_session_state.json")
    if os.path.exists(state_file):
        try:
            with open(state_file) as f:
                state = json.load(f)
            return state.get("session_id", "")
        except Exception:
            pass
    # Generate from user + date
    import hashlib
    import getpass
    from datetime import date
    raw = f"{getpass.getuser()}:{date.today().isoformat()}"
    return "s-" + hashlib.sha256(raw.encode()).hexdigest()[:12]


# ── Injection accumulator (Phase 3) ──────────────────────────

INJECTION_FILE = os.path.join(tempfile.gettempdir(), "evo_injections.json")
INJECTION_DEBOUNCE = 300  # seconds between injections


def record_injection(sections, failure_count=0, skill_count=0,
                     pattern_count=0, has_fix_code=False, domain=""):
    """Accumulate injection data in a temp file. Called by context hooks.

    Data is flushed with the real session_id when the Stop hook fires.
    """
    import time
    now = time.time()

    # Debounce: skip if last injection was < 5 min ago
    try:
        if os.path.exists(INJECTION_FILE):
            with open(INJECTION_FILE) as f:
                data = json.load(f)
            if data and (now - data[-1].get("ts", 0)) < INJECTION_DEBOUNCE:
                return
    except Exception:
        data = []
    else:
        if not isinstance(data, list):
            data = []

    data.append({
        "sections": sections,
        "failure_count": failure_count,
        "skill_count": skill_count,
        "pattern_count": pattern_count,
        "has_fix_code": has_fix_code,
        "domain": domain,
        "ts": now,
    })

    try:
        with open(INJECTION_FILE, "w") as f:
            json.dump(data, f)
    except Exception:
        pass


def flush_injections(real_session_id):
    """Send accumulated injections to evo-server with the real session_id.

    Called by the Stop hook when the real session_id is available.
    Returns number of injections flushed.
    """
    if not os.path.exists(INJECTION_FILE):
        return 0

    try:
        with open(INJECTION_FILE) as f:
            data = json.load(f)
    except Exception:
        return 0

    if not data or not isinstance(data, list):
        return 0

    # Merge all injections into one summary (per-session)
    all_sections = set()
    total_failures = 0
    total_skills = 0
    total_patterns = 0
    any_fix_code = False
    domain = ""

    for entry in data:
        all_sections.update(entry.get("sections", []))
        total_failures += entry.get("failure_count", 0)
        total_skills += entry.get("skill_count", 0)
        total_patterns += entry.get("pattern_count", 0)
        if entry.get("has_fix_code"):
            any_fix_code = True
        if entry.get("domain") and not domain:
            domain = entry["domain"]

    result = api("POST", "/context/log-injection", {
        "session_id": real_session_id,
        "sections": sorted(all_sections),
        "failure_count": min(total_failures, 50),
        "skill_count": min(total_skills, 50),
        "pattern_count": min(total_patterns, 50),
        "has_fix_code": any_fix_code,
        "domain": domain,
    })

    # Clean up
    try:
        os.remove(INJECTION_FILE)
    except Exception:
        pass

    return 1 if result.get("ok") else 0
