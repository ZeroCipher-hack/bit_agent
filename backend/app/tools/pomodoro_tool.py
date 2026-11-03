from .base import Tool, ToolContext, ToolError


class Pomodoro(Tool):
    name = "pomodoro"
    description = ("Start a Pomodoro focus session in the app: work minutes, then a short break, repeated. Bit stays "
                   "quiet and focused during work and cheers at breaks. Defaults 25/5 x4. Returns {ok}.")
    input_schema = {"type": "object", "properties": {
        "work_min": {"type": "integer"}, "break_min": {"type": "integer"}, "cycles": {"type": "integer"}}}
    side_effect = False

    async def run(self, args, ctx: ToolContext):
        w, b, n = int(args.get("work_min") or 25), int(args.get("break_min") or 5), int(args.get("cycles") or 4)
        if not (1 <= w <= 180 and 1 <= b <= 60 and 1 <= n <= 12):
            raise ToolError("work 1..180 min, break 1..60 min, cycles 1..12")
        ctx.client_actions.append({"type": "pomodoro", "work_min": w, "break_min": b, "cycles": n})
        return {"ok": True}


class StopFocus(Tool):
    name = "stop_pomodoro"
    description = "Stop the running Pomodoro session or timer in the app. Returns {ok}."
    side_effect = False

    async def run(self, args, ctx: ToolContext):
        ctx.client_actions.append({"type": "pomodoro_stop"})
        return {"ok": True}
