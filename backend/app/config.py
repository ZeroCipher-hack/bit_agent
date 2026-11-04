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
OPENAI_MODEL_FAST = os.getenv("OPENAI_MODEL_FAST", "gemini-3.5-flash-lite")
OPENAI_MODEL_SMART = os.getenv("OPENAI_MODEL_SMART", "")
# Comma-separated backups tried in order when a model is overloaded (503), rate-limited (429) or times out
OPENAI_MODEL_FALLBACKS = [m.strip() for m in os.getenv("OPENAI_MODEL_FALLBACKS", "").split(",") if m.strip()]
# Optional: "none" / "low" / "medium" / "high" — limits slow "thinking" on reasoning models (sent only if set)
OPENAI_REASONING_EFFORT = os.getenv("OPENAI_REASONING_EFFORT", "").strip()
LLM_TIMEOUT = float(os.getenv("BIT_LLM_TIMEOUT", "60"))


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

# Speech: "edge" = neural voices from the server (recommended), "browser" = the browser's own voices
TTS_MODE = os.getenv("BIT_TTS", "edge").strip().lower()
TTS_VOICE_UZ = os.getenv("BIT_TTS_VOICE_UZ", "uz-UZ-SardorNeural")   # or uz-UZ-MadinaNeural
TTS_VOICE_RU = os.getenv("BIT_TTS_VOICE_RU", "ru-RU-DmitryNeural")   # or ru-RU-SvetlanaNeural
TTS_VOICE_EN = os.getenv("BIT_TTS_VOICE_EN", "en-US-GuyNeural")      # or en-US-AriaNeural
TTS_RATE = os.getenv("BIT_TTS_RATE", "+5%")
TTS_PITCH = os.getenv("BIT_TTS_PITCH", "+25Hz")  # a bit higher = more robot-like

TELEGRAM_API_ID = int(os.getenv("TELEGRAM_API_ID", "0") or 0)
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH", "")
TELEGRAM_SESSION = os.getenv("TELEGRAM_SESSION", "")  # StringSession from scripts/telegram_login.py
TELEGRAM_MAX_PER_HOUR = int(os.getenv("TELEGRAM_MAX_PER_HOUR", "20"))

CONTACTS_FILE = DATA_DIR / "contacts.json"
DEVICES_FILE = DATA_DIR / "devices.json"

# Speech-to-text on the server (Gemini). Empty = the fast chat model
STT_MODEL = os.getenv("BIT_STT_MODEL", "")

# Image generation: auto = Gemini image model when Gemini is the brain, else Pollinations (free, no key)
IMAGE_PROVIDER = os.getenv("BIT_IMAGE_PROVIDER", "auto").strip().lower()   # auto | gemini | pollinations
IMAGE_MODEL = os.getenv("BIT_IMAGE_MODEL", "gemini-2.5-flash-image")

# Weather (Open-Meteo, free, no key): default city when the user does not name one
HOME_CITY = os.getenv("BIT_HOME_CITY", "Tashkent")
# Reminders: also send them to your Telegram "Saved Messages" so they arrive when the app is closed
REMIND_TELEGRAM = os.getenv("BIT_REMIND_TELEGRAM", "1") == "1"
# Smart home through Home Assistant (REST API + long-lived access token)
HA_URL = os.getenv("HA_URL", "").rstrip("/")
HA_TOKEN = os.getenv("HA_TOKEN", "")


def load_contacts() -> dict:
    """Whitelist: {"ali": "@ali_username", "onam": "+998901234567"}. Keys are lowercased."""
    try:
        raw = json.loads(CONTACTS_FILE.read_text(encoding="utf-8"))
        return {str(k).strip().lower(): str(v).strip() for k, v in raw.items()}
    except FileNotFoundError:
        return {}
