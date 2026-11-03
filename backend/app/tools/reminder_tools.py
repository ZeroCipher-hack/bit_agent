import time
from datetime import datetime

from .base import Tool, ToolContext, ToolError


def parse_when(text: str) -> datetime:
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(str(text).strip(), fmt)
        except ValueError:
            pass
    raise ToolError("when must be local time 'YYYY-MM-DD HH:MM'")


class SetReminder(Tool):
    name = "set_reminder"
    description = ("Remind the user at an exact local date and time (e.g. 'tomorrow at 8 remind me about the lesson'). "
                   "Compute the date from the current date in your instructions. The reminder pops up in the app and is also "
                   "sent to the user's Telegram Saved Messages if Telegram is set up. For short countdowns use set_timer. Returns {ok, when}.")
    input_schema = {"type": "object", "properties": {
        "when": {"type": "string", "description": "local time, 'YYYY-MM-DD HH:MM'"},
        "text": {"type": "string", "description": "what to remind, in the user's language"}}, "required": ["when", "text"]}
    side_effect = False

    def validate(self, args):
        if not str(args.get("text", "")).strip():
            raise ToolError("text is empty")
        due = parse_when(args.get("when", "")).timestamp()
        if due < time.time() - 60:
            raise ToolError("that time is already in the past")
        if due > time.time() + 366 * 86400:
            raise ToolError("reminders can be at most one year ahead")

    async def run(self, args, ctx: ToolContext):
        when = parse_when(args["when"])
        rid = ctx.memory.add_reminder(when.timestamp(), str(args["text"]))
        ctx.client_actions.append({"type": "notify_permission"})
        return {"ok": True, "id": rid, "when": when.strftime("%Y-%m-%d %H:%M")}


class ListReminders(Tool):
    name = "list_reminders"
    description = "List upcoming reminders. Returns a list of {when, text}."
    side_effect = False

    async def run(self, args, ctx: ToolContext):
        return [{"when": datetime.fromtimestamp(r["due"]).strftime("%Y-%m-%d %H:%M"), "text": r["text"]}
                for r in ctx.memory.reminders()]


class CancelReminder(Tool):
    name = "cancel_reminder"
    description = "Cancel upcoming reminders whose text contains the given words, or all with '*'. Returns {cancelled}."
    input_schema = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}
    side_effect = False

    async def run(self, args, ctx: ToolContext):
        return {"cancelled": ctx.memory.cancel_reminders(str(args.get("text", "")))}
