from .base import Tool, ToolContext, ToolError


class Remember(Tool):
    name = "remember"
    description = ("Save a durable fact about the user's work, projects, people or preferences so you can use it in "
                   "future conversations. Use when the user asks you to remember something, or states a lasting fact "
                   "about their work. Returns {ok}.")
    input_schema = {"type": "object", "properties": {"fact": {"type": "string", "description": "short fact, in the user's language"}}, "required": ["fact"]}
    side_effect = False

    def validate(self, args):
        if not str(args.get("fact", "")).strip():
            raise ToolError("fact is empty")

    async def run(self, args, ctx: ToolContext):
        ctx.memory.remember(str(args["fact"]))
        return {"ok": True}


class Forget(Tool):
    name = "forget"
    description = "Delete remembered facts containing the given text, or all facts when text is '*'. Use only when the user asks you to forget. Returns {deleted}."
    input_schema = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}
    side_effect = False

    async def run(self, args, ctx: ToolContext):
        return {"deleted": ctx.memory.forget(str(args.get("text", "")))}
