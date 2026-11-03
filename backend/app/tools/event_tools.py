from .. import events as ev
from .base import Tool, ToolContext, ToolError

KINDS = ["birthday", "holiday", "anniversary", "other"]


class SaveEvent(Tool):
    name = "save_event"
    description = ("Remember a date to celebrate or remind about: the user's birthday, a friend's or relative's birthday, "
                   "a holiday (e.g. Ramazon hayiti with its full date), an anniversary, an exam. Use when the user tells "
                   "you such a date. Returns {ok}.")
    input_schema = {"type": "object", "properties": {
        "name": {"type": "string", "description": "short title in the user's language, e.g. 'Mening tugʻilgan kunim', 'Alining tugʻilgan kuni'"},
        "date": {"type": "string", "description": "MM-DD for yearly dates, or YYYY-MM-DD (birth year, or a one-time date)"},
        "kind": {"type": "string", "enum": KINDS},
        "person": {"type": "string", "description": "whose date it is: 'user' for the user, or the person's name"}},
        "required": ["name", "date", "kind"]}
    side_effect = False

    def validate(self, args):
        if not str(args.get("name", "")).strip():
            raise ToolError("name is empty")
        if args.get("kind") not in KINDS:
            raise ToolError(f"kind must be one of {KINDS}")
        try:
            ev.parse_date(args.get("date", ""))
        except (ValueError, TypeError) as e:
            raise ToolError(f"bad date: {e}")

    async def run(self, args, ctx: ToolContext):
        y, m, d = ev.parse_date(args["date"])
        ctx.memory.add_event(args["kind"], str(args["name"]), m, d, y, str(args.get("person", "")))
        return {"ok": True, "month": m, "day": d, "year": y}


class ListEvents(Tool):
    name = "list_events"
    description = "List birthdays and holidays coming in the next N days (default 30), including national holidays. Returns a list."
    input_schema = {"type": "object", "properties": {"days": {"type": "integer", "description": "1..366"}}}
    side_effect = False

    async def run(self, args, ctx: ToolContext):
        days = max(1, min(int(args.get("days") or 30), 366))
        return [{"date": e["date"], "in_days": e["in_days"], "what": ev.describe(e)} for e in ev.upcoming(ctx.memory, days=days)]


class DeleteEvent(Tool):
    name = "delete_event"
    description = "Delete saved dates whose title or person contains the given text, when the user asks. Returns {deleted}."
    input_schema = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}
    side_effect = False

    def validate(self, args):
        if not str(args.get("text", "")).strip():
            raise ToolError("text is empty")

    async def run(self, args, ctx: ToolContext):
        return {"deleted": ctx.memory.delete_events(str(args["text"]))}


class Celebrate(Tool):
    name = "celebrate"
    description = ("Fire a celebration on your face: fireworks, confetti or hearts, with a party hat. Use for birthdays, "
                   "holidays, passed exams, finished projects and other good news worth celebrating. Returns {ok}.")
    input_schema = {"type": "object", "properties": {"style": {"type": "string", "enum": ["fireworks", "confetti", "hearts"]}}}
    side_effect = False

    async def run(self, args, ctx: ToolContext):
        style = args.get("style") if args.get("style") in ("fireworks", "confetti", "hearts") else "fireworks"
        ctx.client_actions.append({"type": "celebrate", "style": style})
        return {"ok": True}
