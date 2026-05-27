#!/usr/bin/env python3
"""Claude Code quality hook — analyze code before/after changes.

PreToolUse (Write/Edit): snapshot file hashes + quality metrics
PostToolUse (Write/Edit): re-analyze, compare, report to evo-server

Runs locally on Windows. Posts results to VPS evo-server.
"""
import sys
import os
import json
import time
import tempfile
import urllib.request
from typing import Dict, Any

# Add learning/ to path for quality_analyzer
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "learning"))
from quality_analyzer import analyze_file, analyze_snapshot, compare_snapshots, format_report

SERVER = os.getenv("EVO_SERVER", "http://119.45.204.198")
SNAPSHOT_DIR = os.path.join(tempfile.gettempdir(), "evo_quality")


def api(method, path, data=None):
    url = f"{SERVER}{path}"
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(
        url, data=body, method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception:
        return {"ok": False}


def ensure_snapshot_dir():
    os.makedirs(SNAPSHOT_DIR, exist_ok=True)


def save_snapshot(session_id, phase, snapshot, delta=None):
    ensure_snapshot_dir()
    path = os.path.join(SNAPSHOT_DIR, f"{session_id}_{phase}.json")
    data = {"snapshot": snapshot, "delta": delta, "timestamp": time.time()}
    with open(path, "w") as f:
        json.dump(data, f)


def load_snapshot(session_id, phase):
    path = os.path.join(SNAPSHOT_DIR, f"{session_id}_{phase}.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return None


def get_changed_file():
    """Get the file being written/edited from stdin JSON."""
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, OSError):
        return None, {}

    # Claude Code passes tool input in different formats
    file_path = (
        data.get("file_path")
        or data.get("input", {}).get("file_path")
        or data.get("command", "").split('"')[1] if '"' in data.get("command", "") else None
    )
    return file_path, data


def handle_pre_tool_use():
    """Snapshot before Claude makes changes."""
    file_path, data = get_changed_file()
    if not file_path or not file_path.endswith(".py"):
        return

    session_id = data.get("session_id", "unknown")

    # Also snapshot nearby .py files for context
    dir_path = os.path.dirname(file_path)
    py_files = []
    if os.path.isdir(dir_path):
        for f in os.listdir(dir_path):
            if f.endswith(".py"):
                py_files.append(os.path.join(dir_path, f))

    if file_path not in py_files:
        py_files.append(file_path)

    snapshot = analyze_snapshot(py_files)
    save_snapshot(session_id, "before", snapshot)


def handle_post_tool_use():
    """Analyze after Claude's changes, compare, report."""
    file_path, data = get_changed_file()
    if not file_path or not file_path.endswith(".py"):
        return

    session_id = data.get("session_id", "unknown")

    # Load before snapshot
    before_data = load_snapshot(session_id, "before")
    if not before_data:
        return

    # Snapshot after
    dir_path = os.path.dirname(file_path)
    py_files = []
    if os.path.isdir(dir_path):
        for f in os.listdir(dir_path):
            if f.endswith(".py"):
                py_files.append(os.path.join(dir_path, f))
    if file_path not in py_files:
        py_files.append(file_path)

    after_snapshot = analyze_snapshot(py_files)
    before_snapshot = before_data["snapshot"]

    # Compare
    delta = compare_snapshots(before_snapshot, after_snapshot)

    # Save after snapshot
    save_snapshot(session_id, "after", after_snapshot, delta)

    # Report to VPS
    report_text = format_report(delta)
    quality_score = delta["summary"]["quality_score"]

    # POST snapshot
    api("POST", "/quality/snapshot", {
        "session_id": session_id,
        "phase": "after",
        "snapshot": {fp: {k: v for k, v in m.items() if k != "analyzed_at"} for fp, m in after_snapshot.items()},
        "delta": delta,
    })

    # POST report
    api("POST", "/quality/report", {
        "session_id": session_id,
        "delta": delta,
        "report": report_text,
    })

    # Print report to stderr (visible in Claude Code output)
    if quality_score < 80:
        print(f"[quality] Score: {quality_score}/100 — {report_text}", file=sys.stderr)
    else:
        print(f"[quality] Score: {quality_score}/100", file=sys.stderr)

    # Clean up before snapshot
    before_path = os.path.join(SNAPSHOT_DIR, f"{session_id}_before.json")
    if os.path.exists(before_path):
        os.remove(before_path)


def main():
    hook_type = os.environ.get("CLAUDE_HOOK_TYPE", "")

    if hook_type == "PreToolUse" or "--pre" in sys.argv:
        handle_pre_tool_use()
    elif hook_type == "PostToolUse" or "--post" in sys.argv:
        handle_post_tool_use()


if __name__ == "__main__":
    main()
