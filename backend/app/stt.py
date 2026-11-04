"""Speech-to-text on the server ("better ears"): the app records WAV, Gemini transcribes it.
Works in every browser, in the desktop app (Electron has no browser speech service) and on phones."""
import base64

import httpx

from . import config

TRANSPORT = None  # tests inject an httpx.MockTransport

PROMPT = ("Transcribe this voice message exactly, word for word, in the language it is spoken in "
          "(Uzbek in Latin script with oʻ and gʻ, Russian in Cyrillic, or English). "
          "Return only the transcript text, nothing else. If there is no speech, return an empty string.")


def available() -> bool:
    return bool(config.OPENAI_API_KEY and "generativelanguage.googleapis.com" in config.OPENAI_BASE_URL)


async def transcribe(audio: bytes, mime: str = "audio/wav") -> str:
    models = [config.STT_MODEL or config.OPENAI_MODEL_FAST] + [m for m in config.OPENAI_MODEL_FALLBACKS if m]
    last = "no model"
    async with httpx.AsyncClient(timeout=45, transport=TRANSPORT) as c:
        for model in dict.fromkeys(models):
            r = await c.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                             headers={"x-goog-api-key": config.OPENAI_API_KEY},
                             json={"contents": [{"parts": [{"text": PROMPT},
                                                           {"inline_data": {"mime_type": mime, "data": base64.b64encode(audio).decode()}}]}],
                                   "generationConfig": {"temperature": 0}})
            if r.status_code in (429, 500, 502, 503, 504):
                last = f"{model}: HTTP {r.status_code}"
                continue
            if r.status_code >= 400:
                raise RuntimeError(f"{model}: HTTP {r.status_code}: {r.text[:200]}")
            parts = ((r.json().get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
            return " ".join(p.get("text", "") for p in parts).strip().strip('"')
    raise RuntimeError(last)
