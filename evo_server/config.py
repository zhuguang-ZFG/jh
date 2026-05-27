"""Evo-server configuration — env-driven, zero hardcoded secrets."""
import os


def _int(env_key: str, default: int) -> int:
    val = os.getenv(env_key, "").strip()
    return int(val) if val else default


def _float(env_key: str, default: float) -> float:
    val = os.getenv(env_key, "").strip()
    return float(val) if val else default


# VPS
HOST = os.getenv("EVO_HOST", "0.0.0.0")
PORT = _int("EVO_PORT", 8090)

# Database
DB_PATH = os.getenv("EVO_DB_PATH", "/opt/evo-server/data/evo.db")

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
TELEGRAM_OWNER_ID = _int("TELEGRAM_OWNER_ID", 0)
TELEGRAM_API_BASE = os.getenv(
    "TELEGRAM_API_BASE", "https://api.telegram.org"
)  # CF Worker proxy override

# MiMo TTS
MIMO_API_KEY = os.getenv("MIMO_API_KEY", "")

# Auth
API_KEY = os.getenv("EVO_API_KEY", "")  # CLI → server auth

# GitHub (for learning engine)
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
_raw_langs = os.getenv("EVO_LEARN_LANGUAGES", "").strip()
GITHUB_LEARN_LANGUAGES = _raw_langs.split(",") if _raw_langs else ["python", "rust", "go", "typescript"]

# Evolution
EMA_SUCCESS_FACTOR = _float("EVO_EMA_SUCCESS", 1.05)
EMA_FAILURE_FACTOR = _float("EVO_EMA_FAILURE", 0.9)
EVIDENCE_MIN = _int("EVO_EVIDENCE_MIN", 3)
PASS_RATE_MIN = _float("EVO_PASS_RATE_MIN", 0.8)

# LiMa cross-server sync
LIMA_SYNC_ENABLED = os.getenv("LIMA_SYNC_ENABLED", "true").lower() == "true"
LIMA_SYNC_INTERVAL_HOURS = _int("LIMA_SYNC_INTERVAL_HOURS", 24)
