"""Server-side speech: natural Uzbek/Russian/English neural voices via edge-tts (no API key).
Works in every browser (Brave blocks browser voices) and on phones. Falls back to browser TTS in the app if this fails."""
from collections import OrderedDict

from . import config

_cache: "OrderedDict[tuple, bytes]" = OrderedDict()


def voice_for(lang: str) -> str:
    return {"uz": config.TTS_VOICE_UZ, "ru": config.TTS_VOICE_RU}.get(lang, config.TTS_VOICE_EN)


async def synthesize(text: str, lang: str) -> bytes:
    text = " ".join(text.split())[:600]
    key = (text, lang, config.TTS_RATE, config.TTS_PITCH)
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key]
    import edge_tts
    comm = edge_tts.Communicate(text, voice_for(lang), rate=config.TTS_RATE, pitch=config.TTS_PITCH,
                                connect_timeout=10, receive_timeout=30)
    audio = bytearray()
    async for chunk in comm.stream():
        if chunk.get("type") == "audio":
            audio += chunk["data"]
    if not audio:
        raise RuntimeError("no audio returned")
    _cache[key] = bytes(audio)
    while len(_cache) > 64:  # keep repeated short phrases (greetings, giggles) instant
        _cache.popitem(last=False)
    return _cache[key]
