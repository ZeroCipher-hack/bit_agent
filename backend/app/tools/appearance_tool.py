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


THEMES = {"classic": (None, None), "purple": ("#7B4DFF", "#C89BFF"), "green": ("#43C24A", "#C6FF3D"),
          "yellow": ("#F5B400", "#FFE45C"), "ice": ("#EAF4FF", "#5CC8FF"), "pink": ("#FF8DC7", "#FFD1EA"),
          "night": ("#2A2833", "#7CF5D6")}
STYLES = ("neon", "classic")


def merge(memory, eye=None, body=None, neon=None, style=None) -> dict:
    cur = memory.kv_get("appearance") or {}
    if style:
        if style not in STYLES:
            raise ToolError(f"style must be one of {STYLES}")
        cur["style"] = style
    for key, val in (("eye", eye), ("body", body), ("neon", neon)):
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
                   "'default' restores the original. Ready sets: theme purple/green/yellow/ice/pink/night/classic ('binafsha boʻl', 'yashil kiyin'). "
                   "Angry and love keep their own colours. Returns the new look.")
    input_schema = {"type": "object", "properties": {
        "eye_color": {"type": "string", "description": "#RRGGBB or 'default'"},
        "body_color": {"type": "string", "description": "#RRGGBB or 'default'"},
        "accent_color": {"type": "string", "description": "neon rings and foot lights, #RRGGBB or 'default'"},
        "theme": {"type": "string", "enum": list(THEMES), "description": "ready colour set: purple, green, yellow, ice, pink, night or classic"},
        "face_style": {"type": "string", "enum": list(STYLES), "description": "neon = glowing line face (default), classic = block eyes"}}}
    side_effect = False

    def validate(self, args):
        if not any(args.get(k) for k in ("eye_color", "body_color", "accent_color", "theme", "face_style")):
            raise ToolError("give a colour, a theme or a face_style")
        if args.get("theme") and args["theme"] not in THEMES:
            raise ToolError(f"theme must be one of {list(THEMES)}")
        clean(args.get("eye_color")); clean(args.get("body_color")); clean(args.get("accent_color"))

    async def run(self, args, ctx: ToolContext):
        body, neon = clean(args.get("body_color")), clean(args.get("accent_color"))
        if args.get("theme"):
            tb, tn = THEMES[args["theme"]]
            body, neon = body or tb or "default", neon or tn or "default"
        look = merge(ctx.memory, clean(args.get("eye_color")), body, neon, args.get("face_style"))
        ctx.client_actions.append({"type": "appearance", **look, "replace": True})
        return look
