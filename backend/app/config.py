"""Settings read from environment variables (.env)."""
import json
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DATA_DIR = Path(os.getenv("BIT_DATA_DIR", "/data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Which brain: "anthropic" (Claude, paid) or "openai" (any OpenAI-compatible API: Gemini, Groq, OpenRouter, Ollama)
LLM_PROVIDER = os.getenv("BIT_LLM_PROVIDER", "anthropic").strip().lower()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL_FAST = os.getenv("OPENAI_MODEL_FAST", "gemini-2.5-flash")
OPENAI_MODEL_SMART = os.getenv("OPENAI_MODEL_SMART", "")


def llm_configured() -> bool:
    if LLM_PROVIDER == "anthropic":
        return bool(ANTHROPIC_API_KEY)
    return bool(OPENAI_BASE_URL and (OPENAI_API_KEY or "localhost" in OPENAI_BASE_URL or "127.0.0.1" in OPENAI_BASE_URL))
MODEL_FAST = os.getenv("BIT_MODEL_FAST", "claude-haiku-5-5")
MODEL_SMART = os.getenv("BIT_MODEL_SMART", "claude-sonnet-5-5")
MAX_TOOL_ROUNDS = int(os.getenv("BIT_MAX_TOOL_ROUNDS", "6"))

# Bearer token the app must send. Generate: python -c "import secrets;print(secrets.token_urlsafe(32))"
API_TOKEN = os.getenv("BIT_API_TOKEN", "")

# 0 = confirm every action, 1 = confirm only risky actions (default), 2 = run whitelisted actions without asking
AUTONOMY_LEVEL = int(os.getenv("BIT_AUTONOMY", "1"))

TELEGRAM_API_ID = int(os.getenv("TELEGRAM_API_ID", "0") or 0)
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH", "")
TELEGRAM_SESSION = os.getenv("TELEGRAM_SESSION", "")  # StringSession from scripts/telegram_login.py
TELEGRAM_MAX_PER_HOUR = int(os.getenv("TELEGRAM_MAX_PER_HOUR", "20"))

CONTACTS_FILE = DATA_DIR / "contacts.json"


def load_contacts() -> dict:
    """Whitelist: {"ali": "@ali_username", "onam": "+998901234567"}. Keys are lowercased."""
    try:
        raw = json.loads(CONTACTS_FILE.read_text(encoding="utf-8"))
        return {str(k).strip().lower(): str(v).strip() for k, v in raw.items()}
    except FileNotFoundError:
        return {}
