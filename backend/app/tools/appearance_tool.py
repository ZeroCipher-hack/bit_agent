"""Change how Bit looks: eye colour and body colour (saved on the server, applied on every device)."""
import re

from .base import Tool, ToolContext, ToolError

HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def clean(value):
    if value is None:
        return None
    v = str(value).strip()
    if v.lower() in ("default", "standart", "reset", ""):
        return "default"
    if not HEX.match(v):
        raise ToolError(f"colour must be #RRGGBB or 'default', got {v!r}")
    return v.upper()


def merge(memory, eye=None, body=None) -> dict:
    cur = memory.kv_get("appearance") or {}
    for key, val in (("eye", eye), ("body", body)):
        if val == "default":
            cur.pop(key, None)
        elif val:
            cur[key] = val
    memory.kv_set("appearance", cur or None)
    return cur


class SetAppearance(Tool):
    name = "set_appearance"
    description = ("Change your own look when the user asks: eye colour and/or body (shell) colour. Convert colour names "
                   "to hex yourself, e.g. koʻk/синий/blue -> #4DA3FF, qizil/красный/red -> #FF5A5F, yashil/зелёный/green -> #4CE08A, "
                   "sariq/жёлтый/yellow -> #FFD15C, pushti/розовый/pink -> #FF7EB6, binafsha/фиолетовый/purple -> #B07CFF, "
                   "oq/белый/white -> #FFFFFF, qora/чёрный/black -> #26242E, toʻq sariq/оранжевый/orange -> #FF9F45. "
                   "'default' restores the original. Angry and love keep their own colours. Returns the new look.")
    input_schema = {"type": "object", "properties": {
        "eye_color": {"type": "string", "description": "#RRGGBB or 'default'"},
        "body_color": {"type": "string", "description": "#RRGGBB or 'default'"}}}
    side_effect = False

    def validate(self, args):
        if not args.get("eye_color") and not args.get("body_color"):
            raise ToolError("give eye_color and/or body_color")
        clean(args.get("eye_color")); clean(args.get("body_color"))

    async def run(self, args, ctx: ToolContext):
        look = merge(ctx.memory, clean(args.get("eye_color")), clean(args.get("body_color")))
        ctx.client_actions.append({"type": "appearance", **look, "replace": True})
        return look
