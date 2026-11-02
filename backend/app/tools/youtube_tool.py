import asyncio
from urllib.parse import quote_plus

from .base import Tool, ToolContext, ToolError


def _search(query: str) -> dict | None:
    import yt_dlp
    opts = {"quiet": True, "no_warnings": True, "skip_download": True, "extract_flat": "in_playlist", "noplaylist": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"ytsearch1:{query}", download=False)
    entries = (info or {}).get("entries") or []
    return entries[0] if entries else None


class PlayYoutube(Tool):
    name = "play_youtube"
    description = ("Find a song or video on YouTube by a search query (title, artist) and play it on the user's device. "
                   "Returns {title, id} of what is playing.")
    input_schema = {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}
    side_effect = False  # harmless: plays media

    def validate(self, args):
        if not str(args.get("query", "")).strip():
            raise ToolError("query is empty")

    async def run(self, args, ctx: ToolContext):
        q = str(args["query"]).strip()
        hit, err = None, "no result"
        try:
            hit = await asyncio.wait_for(asyncio.to_thread(_search, q), timeout=20)
        except Exception as e:  # network/yt-dlp failure -> show search results instead
            err = str(e)[:120]
        if not hit or not hit.get("id"):
            url = "https://www.youtube.com/results?search_query=" + quote_plus(q)
            ctx.client_actions.append({"type": "open_url", "url": url})
            return {"ok": False, "fallback": "opened YouTube search results instead", "error": err}
        vid, title = hit["id"], hit.get("title") or q
        ctx.client_actions.append({"type": "youtube", "id": vid, "title": title, "url": f"https://youtu.be/{vid}"})
        return {"ok": True, "title": title, "id": vid}
