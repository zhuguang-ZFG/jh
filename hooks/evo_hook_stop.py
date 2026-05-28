#!/usr/bin/env python3
"""Claude Code Stop hook — log session to evo-server when agent finishes.

Reads JSON from stdin: {session_id, transcript_path, relevant_output, ...}
Parses transcript JSONL to extract: tool usage, file edits, bash commands,
errors, and generates real skills.
"""
import sys
import json
import os
import tempfile
from datetime import datetime

import subprocess

from evo_hook_common import (
    api, parse_transcript, infer_domain, extract_skills, extract_memories,
    extract_corrections, extract_successes,
    read_changed_files, flush_injections, generate_quality_snapshot, TRACKER_FILE,
)


def _capture_git_diff(changed_files):
    """Capture git diff for changed files (max 8KB)."""
    if not changed_files:
        return ""
    try:
        # Get diff for specific files, or full diff if too many
        if len(changed_files) <= 20:
            cmd = ["git", "diff", "HEAD~1", "--"] + changed_files
        else:
            cmd = ["git", "diff", "HEAD~1"]
        result = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8",
            timeout=10, errors="replace",
        )
        if result.returncode == 0 and result.stdout:
            return result.stdout[:8192]  # cap at 8KB
    except Exception:
        pass
    return ""


def main():
    # Read stdin — Claude Code passes JSON
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, OSError):
        data = {}

    session_id = data.get("session_id", "unknown")
    interaction_type = data.get("interaction_type", "chat")
    relevant_output = data.get("relevant_output", "")
    transcript_path = data.get("transcript_path", "")

    # Read tracked changed files
    changed_files = read_changed_files()
    if os.path.exists(TRACKER_FILE):
        try:
            os.remove(TRACKER_FILE)
        except Exception:
            pass

    # Capture git diff for skill extraction (Phase 2)
    git_diff = _capture_git_diff(changed_files)

    # Parse transcript for rich data
    transcript_data = parse_transcript(transcript_path)

    # If no transcript, fall back to relevant_output
    if not transcript_data and relevant_output:
        transcript_data = {
            "tool_counts": {},
            "files_edited": changed_files,
            "files_written": [],
            "bash_commands": [],
            "bash_patterns": [],
            "edit_details": [],
            "write_details": [],
            "read_files": [],
            "errors_encountered": [],
            "user_messages": [relevant_output[:200]],
            "total_tool_calls": 0,
        }

    # Determine outcome
    outcome = "success"
    all_text = (relevant_output + " ".join(
        transcript_data.get("user_messages", []) if transcript_data else []
    )).lower() if relevant_output or transcript_data else ""
    if any(k in all_text for k in ("error", "failed", "exception", "traceback")):
        outcome = "failure"
    elif any(k in all_text for k in ("partial", "incomplete")):
        outcome = "partial"

    domain = infer_domain(changed_files)

    # Build rich goal summary from transcript
    if transcript_data and transcript_data.get("user_messages"):
        first_msg = transcript_data["user_messages"][0][:100]
        goal = first_msg
    else:
        goal = f"Claude Code {interaction_type} on {domain}"

    # Build lessons from transcript summary
    lessons_parts = []
    if transcript_data:
        fe = len(set(transcript_data.get("files_edited", [])))
        fw = len(transcript_data.get("files_written", []))
        bc = len(transcript_data.get("bash_patterns", []))
        ed = len(transcript_data.get("edit_details", []))
        lessons_parts.append(f"{fe} files touched, {fw} new, {ed} edits, {bc} commands")
        frameworks = set()
        for bp in transcript_data.get("bash_patterns", []):
            for fw_name in ("fastapi", "pytest", "uvicorn", "docker", "nginx"):
                if fw_name in bp.get("full", "").lower():
                    frameworks.add(fw_name)
        if frameworks:
            lessons_parts.append(f"Frameworks: {', '.join(sorted(frameworks))}")
    if changed_files:
        basenames = [os.path.basename(f) for f in changed_files[:5]]
        lessons_parts.append(f"Modified: {', '.join(basenames)}")
    lessons = "; ".join(lessons_parts)

    # Log session
    result = api("POST", "/session/log", {
        "session_id": session_id,
        "tool": "claude_code",
        "goal": goal,
        "outcome": outcome,
        "lessons": lessons,
        "changed_files": changed_files,
        "duration_sec": 0,
        "git_diff": git_diff,
    })

    # Extract and save skills
    skills = extract_skills(transcript_data, changed_files, outcome)
    skills_saved = 0
    if skills:
        # Build user task for gatekeep context
        user_task = ""
        if transcript_data and transcript_data.get("user_messages"):
            user_task = transcript_data["user_messages"][0][:200]

        # Gatekeep: filter out noise skills via LLM (or heuristic fallback)
        try:
            gate_result = api("POST", "/skills/gatekeep", {
                "skills": [{
                    "name": s["name"],
                    "domain": s["domain"],
                    "pattern": s["pattern"],
                    "weight": s["weight"],
                } for s in skills],
                "user_task": user_task,
            })
        except Exception:
            gate_result = None

        gated_skills = []
        if gate_result and gate_result.get("ok"):
            gd = gate_result.get("data", {})
            verdicts = {r["name"]: r for r in gd.get("results", [])}
            for s in skills:
                v = verdicts.get(s["name"], {})
                if v.get("verdict") == "discard":
                    s["weight"] = 0.05  # near-eviction
                gated_skills.append(s)
            kept = gd.get("summary", {}).get("kept", len(skills))
            discarded = gd.get("summary", {}).get("discarded", 0)
            gate_source = (gd.get("results", [{}])[0].get("source", "none")
                          if gd.get("results") else "none")
        else:
            gated_skills = skills

        # Save skills (gatekept)
        batch_result = api("POST", "/skills/batch", {
            "skills": [{
                "name": s["name"],
                "domain": s["domain"],
                "pattern": s["pattern"],
                "weight": s["weight"],
                "source": "session",
            } for s in gated_skills],
        })
        if batch_result and batch_result.get("ok"):
            bd = batch_result.get("data", {})
            skills_saved = bd.get("created", 0) + bd.get("updated", 0)

        if gate_result and gate_result.get("ok"):
            print(f"[evo] gatekeep: {kept} kept, {discarded} discarded "
                  f"({gate_source})", file=sys.stderr)

    # Extract and ingest user corrections (highest-quality signal)
    corrections = extract_corrections(transcript_data)
    corrections_saved = 0
    if corrections:
        try:
            corr_result = api("POST", "/lima/corrections", {
                "corrections": corrections,
                "session_id": session_id,
            })
            if corr_result and corr_result.get("ok"):
                corrections_saved = corr_result.get("data", {}).get("saved", 0)
        except Exception:
            pass
        if corrections_saved:
            print(f"[evo] {corrections_saved} corrections saved", file=sys.stderr)

    # Extract and ingest positive patterns (what worked well)
    successes = extract_successes(transcript_data, outcome)
    if successes:
        for suc in successes:
            try:
                api("POST", "/lima/successes", {
                    "signals": suc["signals"],
                    "files": suc["files"],
                    "confidence": suc["confidence"],
                    "session_id": session_id,
                })
            except Exception:
                pass

    # Flush accumulated injection data with real session_id
    injections_flushed = flush_injections(session_id)

    # Generate and send quality snapshot (closes quality_snapshots gap)
    snapshot, delta = generate_quality_snapshot(
        transcript_data, changed_files, git_diff, outcome, session_id
    )
    quality_saved = False
    if snapshot and delta:
        quality_result = api("POST", "/quality/snapshot", {
            "session_id": session_id,
            "phase": "after",
            "snapshot": snapshot,
            "delta": delta,
        })
        quality_saved = quality_result.get("ok", False)

    if result.get("ok"):
        msg = (
            f"[evo] Session {session_id[:12]} logged "
            f"({outcome}, {len(changed_files)} files, "
            f"{skills_saved} skills, {injections_flushed} injection"
            f"{', quality snapshot' if quality_saved else ''})"
        )
        print(msg, file=sys.stderr)

    # Extract memories (LLM-enhanced with local fallback)
    memories_saved = 0
    llm_used = False

    if transcript_data:
        transcript_summary = {
            "user_messages": transcript_data.get("user_messages", [])[:10],
            "files_edited": list(set(
                transcript_data.get("files_edited", []) +
                transcript_data.get("files_written", []) +
                changed_files
            ))[:20],
            "bash_commands": [bp.get("full", bp.get("root", ""))
                             for bp in transcript_data.get("bash_patterns", [])][:15],
            "errors_encountered": transcript_data.get("errors_encountered", [])[:5],
            "outcome": outcome,
        }

        llm_result = api("POST", "/memories/extract", {
            "session_id": session_id,
            "transcript_summary": transcript_summary,
            "domain": domain,
            "max_memories": 5,
        })

        if llm_result and llm_result.get("ok"):
            llm_data = llm_result.get("data", {})
            memories_saved = llm_data.get("saved", 0)
            llm_used = True

    if not llm_used:
        memories = extract_memories(transcript_data, changed_files, outcome, domain)
        for mem in memories:
            mem_result = api("POST", "/memories/", {
                "session_id": session_id,
                "category": mem["category"],
                "content": mem["content"],
                "domain": mem["domain"],
                "confidence": mem["confidence"],
            })
            if mem_result.get("ok"):
                memories_saved += 1

    if memories_saved:
        mode = "LLM" if llm_used else "local"
        print(f"[evo] {memories_saved} memories saved ({mode})", file=sys.stderr)

    # Log prompt outcome for auto-tuning
    prompt_type = domain
    strategy = ""
    if transcript_data:
        tool_counts = transcript_data.get("tool_counts", {})
        if tool_counts.get("Bash", 0) > 5:
            strategy = "bash_heavy"
        elif tool_counts.get("Edit", 0) > 3:
            strategy = "iterative_edit"
        elif tool_counts.get("Write", 0) > 2:
            strategy = "new_files"
        else:
            strategy = "mixed"

    api("POST", "/prompts/log", {
        "session_id": session_id,
        "prompt_type": prompt_type,
        "prompt_text": goal[:200] if goal else "",
        "strategy": strategy,
        "outcome": outcome,
        "duration_sec": 0,
    })


if __name__ == "__main__":
    main()
