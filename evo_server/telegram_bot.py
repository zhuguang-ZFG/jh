"""Telegram Bot — webhook-based, async httpx client, single-owner auth."""
import httpx
import json
import os
import time
import logging
from typing import Optional, List
from . import config

logger = logging.getLogger("evo.telegram")

_client = None  # type: Optional[httpx.AsyncClient]
_preferred_backend = None  # type: Optional[str]  # user-selected LLM backend name


async def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(base_url=config.TELEGRAM_API_BASE, timeout=30)
    return _client


async def send_message(chat_id, text, reply_to=None):
    # type: (int, str, Optional[int]) -> dict
    """Send message, auto-splitting if > 4000 chars."""
    client = await get_client()
    # Telegram limit is 4096; split at 4000 to be safe
    chunks = _split_message(text, 4000)
    last_result = None
    for chunk in chunks:
        payload = {
            "chat_id": chat_id,
            "text": chunk,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }
        if reply_to and chunk == chunks[0]:
            payload["reply_to_message_id"] = reply_to
        r = await client.post(
            f"/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
            json=payload,
        )
        last_result = r.json()
    return last_result or {}


def _split_message(text, max_len=4000):
    """Split long message into chunks at line boundaries."""
    if len(text) <= max_len:
        return [text]
    chunks = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        # Find last newline before max_len
        cut = text.rfind("\n", 0, max_len)
        if cut == 0:
            cut = max_len
        chunks.append(text[:cut])
        text = text[cut:].lstrip("\n")
    return chunks


async def send_voice(chat_id: int, audio_bytes: bytes, caption: str = "") -> dict:
    """Send a voice message via Telegram."""
    client = await get_client()
    files = {"voice": ("voice.ogg", audio_bytes, "audio/ogg")}
    data = {"chat_id": chat_id}
    if caption:
        data["caption"] = caption
    r = await client.post(
        f"/bot{config.TELEGRAM_BOT_TOKEN}/sendVoice",
        files=files,
        data=data,
    )
    return r.json()


async def send_inline_keyboard(chat_id, text, buttons):
    # type: (int, str, List[List[dict]]) -> dict
    """Send message with inline keyboard. buttons = [[{text, data}, ...], ...]"""
    client = await get_client()
    keyboard = {"inline_keyboard": buttons}
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
        "reply_markup": keyboard,
    }
    r = await client.post(
        f"/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
        json=payload,
    )
    return r.json()


async def send_notification(text: str):
    """Fire-and-forget notification to owner."""
    if not config.TELEGRAM_OWNER_ID or not config.TELEGRAM_BOT_TOKEN:
        return
    try:
        await send_message(config.TELEGRAM_OWNER_ID, text)
    except Exception as e:
        logger.warning(f"Notification failed: {e}")


def _auto_claim_owner(user_id: int):
    """If no owner set, claim the first user as owner."""
    if config.TELEGRAM_OWNER_ID == 0:
        config.TELEGRAM_OWNER_ID = user_id
        import subprocess, sys
        subprocess.run(
            ["sed", "-i", f"s/TELEGRAM_OWNER_ID=.*/TELEGRAM_OWNER_ID={user_id}/", "/opt/evo-server/.env"],
            capture_output=True,
        )


def _apply_evolution(conn, evo: dict, now: float) -> str:
    """Auto-apply an approved evolution. Returns description of what was done."""
    category = evo.get("category", "")
    summary = evo.get("summary", "")

    if category == "skill":
        # Promote lesson to skill
        import hashlib
        skill_key = hashlib.sha256(summary.encode()).hexdigest()[:16]
        existing = conn.execute("SELECT id FROM skills WHERE skill_key=?", (skill_key,)).fetchone()
        if not existing:
            domain = "general"
            lower = summary.lower()
            if any(k in lower for k in ("python", "django", "flask", "fastapi")):
                domain = "python"
            elif any(k in lower for k in ("rust", "cargo")):
                domain = "rust"
            elif any(k in lower for k in ("go ", "golang")):
                domain = "go"
            elif any(k in lower for k in ("react", "typescript", "javascript")):
                domain = "frontend"
            conn.execute(
                """INSERT INTO skills (skill_key, name, domain, pattern, weight,
                                       use_count, success_count, created_at, last_used, source)
                   VALUES (?, ?, ?, ?, 0.8, 1, 1, ?, ?, 'evo_approved')""",
                (skill_key, summary[:60], domain, summary, now, now),
            )
            return f"Created skill: {summary[:50]}"
        else:
            conn.execute(
                "UPDATE skills SET weight=MIN(weight+0.1, 1.0), last_used=? WHERE skill_key=?",
                (now, skill_key),
            )
            return f"Boosted existing skill weight"

    elif category == "pattern":
        import hashlib
        pattern_key = hashlib.sha256(summary.encode()).hexdigest()[:16]
        existing = conn.execute("SELECT id FROM patterns WHERE pattern_key=?", (pattern_key,)).fetchone()
        if not existing:
            conn.execute(
                """INSERT INTO patterns (pattern_key, name, domain, description,
                                         confidence, created_at, last_used)
                   VALUES (?, ?, 'general', ?, 0.7, ?, ?)""",
                (pattern_key, summary[:60], summary, now, now),
            )
            return f"Created pattern: {summary[:50]}"

    elif category == "strategy":
        # Store as meta_rule
        conn.execute(
            """INSERT INTO meta_rules (rule_key, rule_value, category, created_at)
               VALUES (?, ?, 'evolution', ?)""",
            (f"evo_{int(now)}", summary, now),
        )
        return f"Stored strategy rule"

    return ""


async def handle_update(update: dict, db_conn):
    """Process a Telegram update (message or callback_query)."""
    global _preferred_backend
    # --- Callback query (inline keyboard) ---
    if "callback_query" in update:
        cq = update["callback_query"]
        data = cq.get("data", "")
        user_id = cq["from"]["id"]
        _auto_claim_owner(user_id)
        if user_id != config.TELEGRAM_OWNER_ID:
            return
        if data.startswith("approve:"):
            evo_id = int(data.split(":")[1])
            now = time.time()
            # Read evolution details before updating
            evo = db_conn.execute(
                "SELECT id, category, summary, evidence_ids FROM evolutions WHERE id=?", (evo_id,)
            ).fetchone()
            db_conn.execute(
                "UPDATE evolutions SET status='approved', resolved_at=? WHERE id=?",
                (now, evo_id),
            )
            # Auto-apply: promote skill or add pattern
            applied = False
            if evo:
                applied = _apply_evolution(db_conn, dict(evo), now)
            db_conn.commit()
            msg = f"✅ Evolution #{evo_id} approved"
            if applied:
                msg += f"\n⚡ Auto-applied: {applied}"
            await send_message(user_id, msg)
        elif data.startswith("reject:"):
            evo_id = int(data.split(":")[1])
            db_conn.execute(
                "UPDATE evolutions SET status='rejected', resolved_at=? WHERE id=?",
                (time.time(), evo_id),
            )
            db_conn.commit()
            await send_message(user_id, f"❌ Evolution #{evo_id} rejected")
        return

    # --- Text message ---
    msg = update.get("message")
    if not msg:
        return
    chat_id = msg["chat"]["id"]
    user_id = msg["from"]["id"]
    text = msg.get("text", "").strip()

    _auto_claim_owner(user_id)
    if user_id != config.TELEGRAM_OWNER_ID:
        await send_message(chat_id, "Unauthorized.")
        return

    # Non-command messages → AI chat
    if not text.startswith("/"):
        from .llm_bridge import chat, BACKENDS
        await send_message(chat_id, "🤔 Thinking...")
        max_backends = 5
        if _preferred_backend:
            idx = next((i for i, b in enumerate(BACKENDS) if b["name"] == _preferred_backend), None)
            if idx is not None:
                max_backends = idx + 1
        response = await chat(text, system="You are a helpful programming assistant. Reply in the same language as the user. Be concise.", max_backends=max_backends)
        await send_message(chat_id, response)
        return

    parts = text.split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""

    if cmd == "/status":
        stats = {
            "skills": db_conn.execute("SELECT COUNT(*) c FROM skills").fetchone()["c"],
            "patterns": db_conn.execute("SELECT COUNT(*) c FROM patterns").fetchone()["c"],
            "sessions": db_conn.execute("SELECT COUNT(*) c FROM sessions").fetchone()["c"],
            "evolutions": db_conn.execute("SELECT COUNT(*) c FROM evolutions WHERE status='proposed'").fetchone()["c"],
        }
        await send_message(
            chat_id,
            f"*Evo-Server Status*\n"
            f"Skills: {stats['skills']}\n"
            f"Patterns: {stats['patterns']}\n"
            f"Sessions: {stats['sessions']}\n"
            f"Pending evolutions: {stats['evolutions']}",
        )

    elif cmd == "/memory" and arg:
        rows = db_conn.execute(
            "SELECT name, domain, pattern, weight FROM skills WHERE name LIKE ? OR pattern LIKE ? ORDER BY weight DESC LIMIT 10",
            (f"%{arg}%", f"%{arg}%"),
        ).fetchall()
        if rows:
            lines = [f"*Memory search: '{arg}'*"]
            for r in rows:
                lines.append(f"• `{r['name']}` [{r['domain']}] w={r['weight']:.2f}\n  {r['pattern'][:80]}")
            await send_message(chat_id, "\n".join(lines))
        else:
            await send_message(chat_id, f"No memories found for '{arg}'")

    elif cmd == "/skills":
        rows = db_conn.execute(
            "SELECT name, domain, weight, use_count FROM skills ORDER BY weight DESC LIMIT 15"
        ).fetchall()
        if rows:
            lines = ["*Top Skills*"]
            for r in rows:
                lines.append(f"• `{r['name']}` [{r['domain']}] w={r['weight']:.2f} used={r['use_count']}")
            await send_message(chat_id, "\n".join(lines))
        else:
            await send_message(chat_id, "No skills yet.")

    elif cmd == "/patterns":
        if arg:
            rows = db_conn.execute(
                "SELECT name, domain, description, source_repo, confidence FROM patterns WHERE domain=? ORDER BY confidence DESC LIMIT 10",
                (arg,),
            ).fetchall()
        else:
            rows = db_conn.execute(
                "SELECT name, domain, description, source_repo, confidence FROM patterns ORDER BY confidence DESC LIMIT 10"
            ).fetchall()
        if rows:
            lines = [f"*Patterns{' (' + arg + ')' if arg else ''}*"]
            for r in rows:
                src = f" from {r['source_repo']}" if r["source_repo"] else ""
                lines.append(f"• `{r['name']}` [{r['domain']}] conf={r['confidence']:.1f}{src}\n  {r['description'][:80]}")
            await send_message(chat_id, "\n".join(lines))
        else:
            await send_message(chat_id, "No patterns yet.")

    elif cmd == "/evo":
        rows = db_conn.execute(
            "SELECT id, category, summary, confidence FROM evolutions WHERE status='proposed' ORDER BY created_at DESC LIMIT 10"
        ).fetchall()
        if rows:
            for r in rows:
                text = (
                    f"*Evolution #{r['id']}* [{r['category']}] conf={r['confidence']:.1f}\n"
                    f"{r['summary'][:200]}"
                )
                buttons = [[
                    {"text": "✅ Approve", "data": f"approve:{r['id']}"},
                    {"text": "❌ Reject", "data": f"reject:{r['id']}"},
                ]]
                await send_inline_keyboard(chat_id, text, buttons)
        else:
            await send_message(chat_id, "No pending evolutions.")

    elif cmd == "/digest":
        from .evolution_engine import analyze_recent_sessions
        analysis = analyze_recent_sessions(days=7)
        if analysis["total"] == 0:
            await send_message(chat_id, "No sessions in the past 7 days.")
            return
        lines = [
            f"*Weekly Digest*",
            f"Sessions: {analysis['total']}",
            f"Success: {analysis['success_count']}  Failure: {analysis['fail_count']}",
            f"Pass rate: {analysis['pass_rate']:.0%}",
        ]
        if analysis["top_domains"]:
            lines.append(f"Domains: {', '.join(f'{d[0]}({d[1]})' for d in analysis['top_domains'][:5])}")
        if analysis["lessons"]:
            lines.append(f"\n*Lessons:*")
            for l in analysis["lessons"][:5]:
                lines.append(f"• {l[:100]}")
        await send_message(chat_id, "\n".join(lines))

    elif cmd == "/run":
        from .evolution_engine import run_weekly_evolution
        result = run_weekly_evolution()
        msg = (
            f"⚡ *Manual Evolution Run*\n"
            f"Sessions: {result['sessions_analyzed']}\n"
            f"Proposals: {len(result['proposal_ids'])}\n"
            f"Pass rate: {result['pass_rate']:.0%}"
        )
        await send_message(chat_id, msg)
        # Notify with proposal details
        if result["proposal_ids"]:
            conn2 = db_conn
            for eid in result["proposal_ids"]:
                row = conn2.execute(
                    "SELECT id, category, summary, confidence FROM evolutions WHERE id=?", (eid,)
                ).fetchone()
                if row:
                    text = (
                        f"*New Proposal #{row['id']}* [{row['category']}] conf={row['confidence']:.1f}\n"
                        f"{row['summary'][:200]}"
                    )
                    buttons = [[
                        {"text": "✅ Approve", "data": f"approve:{row['id']}"},
                        {"text": "❌ Reject", "data": f"reject:{row['id']}"},
                    ]]
                    await send_inline_keyboard(chat_id, text, buttons)

    elif cmd == "/sync":
        await send_message(chat_id, "🔗 Querying LLM for knowledge...")
        from .llm_bridge import chat, export_evo_knowledge
        try:
            knowledge = export_evo_knowledge()
            skills_summary = ", ".join(
                f"{s['name']}[{s['domain']}]"
                for s in knowledge["top_skills"][:5]
            )
            response = await chat(
                f"Given skills: {skills_summary}\nSuggest 3 improvements.",
                system="Return JSON array: [{category, summary, confidence}]. No explanation.",
            )
            import json
            suggestions = []
            try:
                suggestions = json.loads(response)
            except Exception:
                pass
            msg = (
                f"🔗 *LLM Sync Complete*\n"
                f"Knowledge exported: {knowledge['skills_count']} skills, {knowledge['patterns_count']} patterns\n"
                f"Suggestions: {len(suggestions)}"
            )
            await send_message(chat_id, msg)
        except Exception as e:
            await send_message(chat_id, f"❌ Sync failed: {e}")

    elif cmd == "/chat" and arg:
        from .llm_bridge import chat, BACKENDS
        await send_message(chat_id, "🤔 Thinking...")
        max_backends = 5
        if _preferred_backend:
            # Try preferred backend first
            idx = next((i for i, b in enumerate(BACKENDS) if b["name"] == _preferred_backend), None)
            if idx is not None:
                max_backends = idx + 1
        response = await chat(arg, system="You are a helpful programming assistant. Be concise.", max_backends=max_backends)
        await send_message(chat_id, response)

    elif cmd == "/model":
        from .llm_bridge import BACKENDS
        if not arg:
            # Show current and available models
            lines = ["*Available Models*"]
            for i, b in enumerate(BACKENDS):
                marker = " →" if b["name"] == _preferred_backend else ""
                tag = "free" if b["key"] in ("none", "1") else "paid"
                lines.append(f"`{b['name']}` [{tag}]{marker}")
            lines.append(f"\nCurrent: `{_preferred_backend or 'auto (fallback chain)'}`")
            lines.append("Usage: /model <name> or /model auto")
            await send_message(chat_id, "\n".join(lines))
        elif arg == "auto":
            _preferred_backend = None
            await send_message(chat_id, "🔄 Model set to auto (full fallback chain)")
        else:
            match = next((b for b in BACKENDS if b["name"] == arg), None)
            if match:
                _preferred_backend = arg
                await send_message(chat_id, f"✅ Model set to `{arg}`")
            else:
                await send_message(chat_id, f"Unknown model: `{arg}`\nUse /model to see available models.")

    elif cmd == "/lima":
        from .llm_bridge import fetch_llm_stats
        stats = await fetch_llm_stats()
        msg = (
            f"*LLM Status*\n"
            f"Provider: {stats.get('provider', '?')}\n"
            f"Model: {stats.get('model', '?')}\n"
            f"Status: {stats.get('status', '?')}"
        )
        await send_message(chat_id, msg)

    elif cmd in ("/approve", "/reject"):
        rows = db_conn.execute(
            "SELECT id, category, summary, confidence FROM evolutions WHERE status='proposed' ORDER BY created_at DESC LIMIT 10"
        ).fetchall()
        if not rows:
            await send_message(chat_id, "No pending evolutions.")
            return
        for r in rows:
            text = (
                f"*#{r['id']}* [{r['category']}] conf={r['confidence']:.1f}\n"
                f"{r['summary'][:200]}"
            )
            buttons = [[
                {"text": "✅ Approve", "data": f"approve:{r['id']}"},
                {"text": "❌ Reject", "data": f"reject:{r['id']}"},
            ]]
            await send_inline_keyboard(chat_id, text, buttons)

    elif cmd == "/start":
        await send_message(
            chat_id,
            "*Welcome to Evo-Server*\n"
            "Your personal programming evolution platform.\n\n"
            "I learn from GitHub trending repos and improve my coding skills over time.\n\n"
            "Type /help to see available commands.",
        )

    elif cmd == "/say" and arg:
        from .tts import tts
        audio = await tts(arg)
        if audio:
            await send_voice(chat_id, audio, caption=arg[:100])
        else:
            await send_message(chat_id, "TTS failed. Check MIMO_API_KEY config.")

    elif cmd == "/voice" and arg:
        from .tts import tts
        models = {
            "v2": "mimo-v2-tts",
            "v2.5": "mimo-v2.5-tts",
            "clone": "mimo-v2.5-tts-voiceclone",
            "design": "mimo-v2.5-tts-voicedesign",
        }
        model = models.get(arg.split()[0], "mimo-v2.5-tts")
        text = arg.split(maxsplit=1)[1] if len(arg.split()) > 1 else ""
        if not text:
            await send_message(chat_id, f"Usage: /voice [model] <text>\nModels: {', '.join(models.keys())}")
            return
        audio = await tts(text, model=model)
        if audio:
            await send_voice(chat_id, audio, caption=f"[{model}] {text[:80]}")
        else:
            await send_message(chat_id, "TTS failed.")

    elif cmd == "/learn":
        await send_message(chat_id, "🔍 Scanning GitHub trending repos...")
        import subprocess, sys
        try:
            result = subprocess.run(
                [sys.executable, "/opt/evo-server/learning/github_learner.py"],
                capture_output=True, text=True, timeout=300,
                env={**os.environ, "EVO_SERVER": "http://127.0.0.1:8090"},
            )
            output = result.stdout[-500:] if result.stdout else "No output"
            await send_message(chat_id, f"*GitHub Learning Complete*\n```\n{output}\n```")
        except Exception as e:
            await send_message(chat_id, f"❌ Learning failed: {e}")

    elif cmd == "/help":
        await send_message(
            chat_id,
            "*Evo-Server Commands*\n"
            "/status — System stats\n"
            "/memory <query> — Search memories\n"
            "/skills — Top skills\n"
            "/patterns [domain] — Learned patterns\n"
            "/evo — Pending evolutions (with approve/reject buttons)\n"
            "/approve <id> — Approve evolution\n"
            "/reject <id> — Reject evolution\n"
            "/digest — Weekly summary\n"
            "/run — Manually trigger evolution\n"
            "/learn — Scan GitHub trending repos\n"
            "/sync — Query LLM for improvement suggestions\n"
            "/lima — LLM integration status\n"
            "/model [name] — Switch LLM model\n"
            "/chat <msg> — Chat with AI\n"
            "/say <text> — Text to speech (v2.5)\n"
            "/voice [model] <text> — Voice with model choice",
        )

    else:
        await send_message(chat_id, f"Unknown command: {cmd}\nTry /help")
