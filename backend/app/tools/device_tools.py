"""Tools whose effect happens on the user's device: the app receives a client action and performs it."""
from urllib.parse import urlparse

from .base import Tool, ToolContext, ToolError


class SetTimer(Tool):
    name = "set_timer"
    description = "Start a countdown timer in the app; it rings when done. For timers or reminders within 24 hours. Returns {ok, seconds}."
    input_schema = {"type": "object", "properties": {
        "seconds": {"type": "integer", "description": "1..86400"},
        "label": {"type": "string", "description": "short label in the user's language"}}, "required": ["seconds"]}
    side_effect = False

    def validate(self, args):
        try:
            s = int(args.get("seconds", 0))
        except (TypeError, ValueError):
            raise ToolError("seconds must be an integer")
        if not 1 <= s <= 86400:
            raise ToolError("seconds must be between 1 and 86400")

    async def run(self, args, ctx: ToolContext):
        s = int(args["seconds"])
        ctx.client_actions.append({"type": "timer", "seconds": s, "label": str(args.get("label", ""))[:40]})
        return {"ok": True, "seconds": s}


class OpenUrl(Tool):
    name = "open_url"
    description = "Open a web page (http/https) on the user's device, e.g. a news site or a document. Returns {ok}."
    input_schema = {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}

    def validate(self, args):
        u = urlparse(str(args.get("url", "")))
        if u.scheme not in ("http", "https") or not u.netloc:
            raise ToolError("only full http(s) URLs are allowed")

    def summary(self, args):
        return f"Open {args['url']}"

    async def run(self, args, ctx: ToolContext):
        ctx.client_actions.append({"type": "open_url", "url": str(args["url"])})
        return {"ok": True}


class OpenOnComputer(Tool):
    name = "open_on_computer"
    description = ("Open an application or a folder on the user's computer through the local agent, e.g. 'telegram', "
                   "'vscode', 'chrome', 'desktop', 'downloads', 'documents', or a folder name on the desktop. Only works when the app "
                   "runs on that computer with the local agent started; on a phone it fails. Returns {ok}.")
    input_schema = {"type": "object", "properties": {
        "target": {"type": "string", "description": "app or folder alias, lowercase English"}}, "required": ["target"]}

    def validate(self, args):
        t = str(args.get("target", "")).strip()
        if not t or len(t) > 60 or any(c in t for c in "/\\;&|`$<>"):
            raise ToolError("target must be a short app or folder alias")

    def summary(self, args):
        return f"Open on computer: {args['target']}"

    async def run(self, args, ctx: ToolContext):
        ctx.client_actions.append({"type": "local", "action": "open", "target": str(args["target"]).strip().lower()})
        return {"ok": True, "note": "sent to the local agent; it only opens whitelisted targets"}
