"""Image generation. Gemini image model when Gemini is the brain (same key), otherwise Pollinations (free, no key).
The picture comes back to the app as a data URL; nothing is stored on the server."""
import base64
from urllib.parse import quote

import httpx

from .. import config
from .base import Tool, ToolContext, ToolError

TRANSPORT = None  # tests inject an httpx.MockTransport
MAX_BYTES = 6_000_000


async def _gemini(prompt: str, c: httpx.AsyncClient) -> tuple[str, bytes]:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{config.IMAGE_MODEL}:generateContent"
    r = await c.post(url, headers={"x-goog-api-key": config.OPENAI_API_KEY},
                     json={"contents": [{"parts": [{"text": prompt}]}],
                           "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]}})
    if r.status_code >= 400:
        raise ToolError(f"gemini image HTTP {r.status_code}")
    for cand in r.json().get("candidates") or []:
        for part in (cand.get("content") or {}).get("parts") or []:
            data = part.get("inlineData") or part.get("inline_data")
            if data and data.get("data"):
                return data.get("mimeType") or data.get("mime_type") or "image/png", base64.b64decode(data["data"])
    raise ToolError("gemini returned no image")


async def _pollinations(prompt: str, c: httpx.AsyncClient) -> tuple[str, bytes]:
    url = "https://image.pollinations.ai/prompt/" + quote(prompt[:400])
    r = await c.get(url, params={"width": 768, "height": 768, "nologo": "true", "safe": "true"}, follow_redirects=True)
    ctype = r.headers.get("content-type", "").split(";")[0]
    if r.status_code >= 400 or not ctype.startswith("image/"):
        raise ToolError(f"image service HTTP {r.status_code}")
    return ctype, r.content


class GenerateImage(Tool):
    name = "generate_image"
    description = ("Draw / generate a picture for the user ('rasm chiz', 'rasm yarat', 'нарисуй', 'draw', 'generate an image'). "
                   "Write the prompt in English, detailed: subject, style, colours, mood. Kid-friendly only: no sexual or "
                   "gory content, no real people's likeness, no copyrighted characters. Returns {ok, provider}.")
    input_schema = {"type": "object", "properties": {"prompt": {"type": "string", "description": "English image description"}},
                    "required": ["prompt"]}
    side_effect = False

    def validate(self, args):
        if not str(args.get("prompt", "")).strip():
            raise ToolError("prompt is empty")

    async def run(self, args, ctx: ToolContext):
        prompt = str(args["prompt"]).strip()[:800]
        use_gemini = config.IMAGE_PROVIDER == "gemini" or (
            config.IMAGE_PROVIDER == "auto" and config.LLM_PROVIDER != "anthropic"
            and "generativelanguage.googleapis.com" in config.OPENAI_BASE_URL and config.OPENAI_API_KEY)
        errors = []
        async with httpx.AsyncClient(timeout=90, transport=TRANSPORT) as c:
            for name, fn in ((("gemini", _gemini),) if use_gemini else ()) + (("pollinations", _pollinations),):
                try:
                    mime, data = await fn(prompt, c)
                    if len(data) > MAX_BYTES:
                        raise ToolError("image too large")
                    ctx.client_actions.append({"type": "image", "prompt": prompt,
                                               "src": f"data:{mime};base64," + base64.b64encode(data).decode()})
                    return {"ok": True, "provider": name}
                except (ToolError, httpx.HTTPError, ValueError) as e:
                    errors.append(f"{name}: {e}")
        raise ToolError("could not draw the picture (" + "; ".join(errors) + ")")
