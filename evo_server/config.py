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

# LLM integration (multi-backend, free-first)
LLM_SYNC_ENABLED = os.getenv("LLM_SYNC_ENABLED", "true").lower() == "true"
LLM_SYNC_INTERVAL_HOURS = _int("LLM_SYNC_INTERVAL_HOURS", 24)
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
ZHIPU_API_KEY = os.getenv("ZHIPU_API_KEY", "")
ALIBABA_API_KEY = os.getenv("ALIBABA_API_KEY", "")
CF_ACCOUNT_ID = os.getenv("CF_ACCOUNT_ID", "")
CF_API_KEY = os.getenv("CF_API_KEY", "")

# Embedding API (Alibaba text-embedding-v3)
EMBEDDING_API_KEY = os.getenv("ALIBABA_EMBEDDING_API_KEY", "") or os.getenv("ALIBABA_API_KEY", "")
EMBEDDING_DIM = 1024

# EMA for prompt ranking
EMA_PROMPT_LAMBDA = _float("EVO_EMA_LAMBDA", 0.05)
