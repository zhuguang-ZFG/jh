"""MiMo TTS client — convert text to voice for Telegram."""
import base64
import logging
from typing import Optional
import httpx
from . import config

logger = logging.getLogger("evo.tts")

API_BASE = "https://token-plan-cn.xiaomimimo.com"
DEFAULT_MODEL = "mimo-v2.5-tts"


async def tts(text, model=DEFAULT_MODEL):
    # type: (str, str) -> Optional[bytes]
    """Convert text to WAV audio bytes. Returns None on failure."""
    api_key = config.MIMO_API_KEY
    if not api_key:
        return None
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": model,
        "messages": [
            {"role": "user", "content": "Read this aloud"},
            {"role": "assistant", "content": text},
        ],
        "stream": False,
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{API_BASE}/v1/chat/completions", headers=headers, json=body,
            )
            if resp.status_code != 200:
                logger.warning(f"MiMo TTS {resp.status_code}: {resp.text[:100]}")
                return None
            data = resp.json()
            audio = data["choices"][0]["message"].get("audio", {})
            raw = audio.get("data", "")
            if not raw:
                return None
            return base64.b64decode(raw)
    except Exception as e:
        logger.error(f"MiMo TTS error: {e}")
        return None
