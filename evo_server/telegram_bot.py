"""Telegram Bot — webhook-based, async httpx client, single-owner auth."""
import httpx
import json
import time
import logging
from . import config

logger = logging.getLogger("evo.telegram")

_client: httpx.AsyncClient | None = None


async def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(base_url=config.TELEGRAM_API_BASE, timeout=30)
    return _client


async def send_message(chat_id: int, text: str, reply_to: int | None = None) -> dict:
    client = await get_client()
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }
    if reply_to:
        payload["reply_to_message_id"] = reply_to
    r = await client.post(
        f"/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
        json=payload,
    )
    return r.json()


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


async def send_inline_keyboard(chat_id: int, text: str, buttons: list[list[dict]]) -> dict:
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


async def handle_update(update: dict, db_conn):
    """Process a Telegram update (message or callback_query)."""
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
            db_conn.execute(
                "UPDATE evolutions SET status='approved', resolved_at=? WHERE id=?",
                (time.time(), evo_id),
            )
            db_conn.commit()
            await send_message(user_id, f"✅ Evolution #{evo_id} approved")
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

    if not text.startswith("/"):
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

    elif cmd == "/approve" and arg:
        try:
            evo_id = int(arg)
            db_conn.execute(
                "UPDATE evolutions SET status='approved', resolved_at=? WHERE id=? AND status='proposed'",
                (time.time(), evo_id),
            )
            db_conn.commit()
            await send_message(chat_id, f"✅ Evolution #{evo_id} approved")
        except ValueError:
            await send_message(chat_id, "Usage: /approve <id>")

    elif cmd == "/reject" and arg:
        try:
            evo_id = int(arg)
            db_conn.execute(
                "UPDATE evolutions SET status='rejected', resolved_at=? WHERE id=? AND status='proposed'",
                (time.time(), evo_id),
            )
            db_conn.commit()
            await send_message(chat_id, f"❌ Evolution #{evo_id} rejected")
        except ValueError:
            await send_message(chat_id, "Usage: /reject <id>")

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
            "/say <text> — Text to speech (v2.5)\n"
            "/voice [model] <text> — Voice with model choice",
        )

    else:
        await send_message(chat_id, f"Unknown command: {cmd}\nTry /help")
