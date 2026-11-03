"""Quiz mode: Bit asks questions one by one, the model judges answers, these tools keep the score."""
from .base import Tool, ToolContext, ToolError


def state(memory):
    return memory.kv_get("quiz")


class QuizStart(Tool):
    name = "quiz_start"
    description = ("Start a quiz when the user (e.g. a teacher with students) asks for one. Then ask ONE question at a "
                   "time with options A/B/C/D, wait for the answer, call quiz_answer, and continue. Returns the quiz state.")
    input_schema = {"type": "object", "properties": {
        "topic": {"type": "string"}, "total": {"type": "integer", "description": "number of questions, 1..30"},
        "level": {"type": "string", "description": "e.g. kids, school, beginner, advanced"}}, "required": ["topic"]}
    side_effect = False

    async def run(self, args, ctx: ToolContext):
        total = max(1, min(int(args.get("total") or 5), 30))
        st = {"topic": str(args["topic"])[:80], "level": str(args.get("level") or "")[:40], "total": total, "asked": 0, "correct": 0}
        ctx.memory.kv_set("quiz", st)
        return st


class QuizAnswer(Tool):
    name = "quiz_answer"
    description = "Record whether the user's answer to the current quiz question was correct. Returns the updated state and whether the quiz is finished."
    input_schema = {"type": "object", "properties": {"correct": {"type": "boolean"}}, "required": ["correct"]}
    side_effect = False

    async def run(self, args, ctx: ToolContext):
        st = state(ctx.memory)
        if not st:
            raise ToolError("no quiz is running; call quiz_start first")
        st["asked"] += 1
        st["correct"] += 1 if args.get("correct") else 0
        st["finished"] = st["asked"] >= st["total"]
        ctx.memory.kv_set("quiz", st)
        return st


class QuizEnd(Tool):
    name = "quiz_end"
    description = "Finish or stop the quiz and get the final score (celebrate a good result). Returns the final state."
    side_effect = False

    async def run(self, args, ctx: ToolContext):
        st = state(ctx.memory) or {}
        ctx.memory.kv_set("quiz", None)
        return {**st, "ended": True}
