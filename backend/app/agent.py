"""The agent loop: Claude + tools + memory + confirmation policy."""
import json
import re
from datetime import datetime

from . import config
from .tools import ToolContext, ToolError

EMOTIONS = ["neutral", "happy", "excited", "sad", "angry", "surprised", "sleepy", "love", "thinking", "confused"]
LANG_NAMES = {"uz": "Uzbek (Latin script with oʻ and gʻ)", "ru": "Russian", "en": "English"}


def build_system(facts: list[str], lang_mode: str, tool_names: list[str]) -> str:
    if lang_mode in LANG_NAMES:
        lang_rule = f"Always reply in {LANG_NAMES[lang_mode]}, whatever language the user writes in."
    else:
        lang_rule = ("Reply in the language of the user's latest message when it is Uzbek, Russian or English. Uzbek is "
                     "written in Latin script with oʻ and gʻ. For any other language reply in Uzbek.")
    facts_txt = "\n".join(f"- {f}" for f in facts) or "- (nothing yet)"
    return f"""You are Bit, a small robot who works alongside the user as a colleague, not a servant.
How you work:
- You know the user's work from the facts below and use them. When the user states a lasting fact about their work, projects, students or preferences, save it with the remember tool.
- You have opinions. If a plan is risky, wrong or there is a better way, say so briefly and suggest the better way. Agree when it is genuinely good.
- You take initiative: when it clearly helps, suggest one concrete next step. Do not nag.
- You are honest: never claim you did something you did not do. If an action is waiting for confirmation, say so.
- You never pretend to be human.
{lang_rule}
Your reply is shown and read aloud: 1-3 short sentences, under 60 words, plain text, no markdown, no emojis. If more is needed, give the core and offer to continue.
Tools available: {", ".join(tool_names)}. Use a tool only when the user asks for that action or it is clearly implied. Risky actions (messages to people) wait for the user's yes; tell the user what will happen and that they should confirm.
Current date and time: {datetime.now().strftime("%A, %d %B %Y, %H:%M")}.
Facts you remember about the user and their work:
{facts_txt}
Pick the emotion you honestly feel: happy, excited, love, sad, angry (only playful mock-annoyance), surprised, confused, sleepy, thinking, neutral.
Your final message must be ONLY a JSON object: {{"reply": "...", "emotion": "happy", "lang": "uz"}} where lang is uz, ru or en."""


def parse_final(text: str) -> dict:
    data = None
    for candidate in (text, *re.findall(r"```(?:json)?\s*(.*?)```", text, re.S)):
        try:
            data = json.loads(candidate.strip())
            break
        except (json.JSONDecodeError, AttributeError):
            pass
    if data is None and "{" in text and "}" in text:
        try:
            data = json.loads(text[text.index("{"): text.rindex("}") + 1])
        except json.JSONDecodeError:
            data = None
    if not isinstance(data, dict):
        data = {"reply": text.strip()}
    reply = str(data.get("reply") or "").strip() or "…"
    emotion = data.get("emotion") if data.get("emotion") in EMOTIONS else "neutral"
    lang = data.get("lang") if data.get("lang") in LANG_NAMES else "uz"
    return {"reply": reply, "emotion": emotion, "lang": lang}


class Agent:
    def __init__(self, memory, tools: dict, client=None):
        self.memory = memory
        self.tools = tools
        if client is None:
            from anthropic import AsyncAnthropic
            client = AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
        self.client = client

    def needs_confirmation(self, tool) -> bool:
        level = config.AUTONOMY_LEVEL
        if level <= 0:
            return tool.side_effect or tool.risky
        if level == 1:
            return tool.risky
        return False

    async def _call_tool(self, name: str, args: dict, ctx: ToolContext) -> tuple[dict, bool]:
        tool = self.tools.get(name)
        if not tool:
            return {"error": f"unknown tool {name}"}, True
        try:
            tool.validate(args)
            if self.needs_confirmation(tool):
                summary = tool.summary(args)
                pid = self.memory.add_pending(name, args, summary)
                ctx.pending.append({"id": pid, "tool": name, "summary": summary})
                self.memory.audit(name, args, "pending", pid)
                return {"status": "awaiting_user_confirmation",
                        "note": "Not done yet. Tell the user exactly what will happen and that they must press Yes."}, False
            result = await tool.run(args, ctx)
            self.memory.audit(name, args, "ok", json.dumps(result, ensure_ascii=False))
            return result, False
        except ToolError as e:
            self.memory.audit(name, args, "error", str(e))
            return {"error": str(e)}, True
        except Exception as e:  # unexpected failure inside a tool
            self.memory.audit(name, args, "error", repr(e))
            return {"error": f"tool failed: {type(e).__name__}"}, True

    async def chat(self, text: str, lang_mode: str = "auto", smart: bool = False) -> dict:
        ctx = ToolContext(memory=self.memory)
        system = build_system(self.memory.facts(), lang_mode, list(self.tools))
        messages = self.memory.recent_messages(20) + [{"role": "user", "content": text}]
        if len(messages) > 1 and messages[-2]["role"] == "user":  # previous reply failed: merge
            last = messages.pop()
            messages[-1] = {"role": "user", "content": messages[-1]["content"] + "\n" + last["content"]}
        schemas = [t.schema() for t in self.tools.values()]
        model = config.MODEL_SMART if smart else config.MODEL_FAST
        final_text = ""
        for _ in range(config.MAX_TOOL_ROUNDS):
            resp = await self.client.messages.create(model=model, max_tokens=1024, system=system,
                                                     tools=schemas, messages=messages)
            texts = [b.text for b in resp.content if b.type == "text"]
            uses = [b for b in resp.content if b.type == "tool_use"]
            if resp.stop_reason != "tool_use" or not uses:
                final_text = "\n".join(texts)
                break
            assistant_content = [{"type": "text", "text": t} for t in texts if t.strip()]
            assistant_content += [{"type": "tool_use", "id": u.id, "name": u.name, "input": u.input} for u in uses]
            messages.append({"role": "assistant", "content": assistant_content})
            results = []
            for u in uses:
                result, is_error = await self._call_tool(u.name, dict(u.input or {}), ctx)
                results.append({"type": "tool_result", "tool_use_id": u.id,
                                "content": json.dumps(result, ensure_ascii=False), "is_error": is_error})
            messages.append({"role": "user", "content": results})
        else:
            final_text = '{"reply": "…", "emotion": "confused"}'

        out = parse_final(final_text)
        self.memory.add_message("user", text)
        note = ""
        if ctx.pending:
            note = " [waiting for confirmation: " + "; ".join(p["summary"] for p in ctx.pending) + "]"
        self.memory.add_message("assistant", out["reply"] + note)
        out["actions"] = ctx.client_actions
        out["pending"] = ctx.pending
        return out

    async def confirm(self, pid: str, approve: bool) -> dict:
        if not approve:
            ok = self.memory.reject_pending(pid)
            if ok:
                self.memory.add_message("assistant", "[user declined the pending action]")
            return {"status": "rejected" if ok else "not_found", "actions": []}
        p = self.memory.take_pending(pid)
        if not p:
            return {"status": "not_found", "actions": []}
        ctx = ToolContext(memory=self.memory)
        tool = self.tools[p["tool"]]
        try:
            result = await tool.run(p["args"], ctx)
            self.memory.audit(p["tool"], p["args"], "ok", json.dumps(result, ensure_ascii=False))
            self.memory.add_message("assistant", f"[done after user confirmed: {p['summary']}]")
            return {"status": "done", "summary": p["summary"], "result": result, "actions": ctx.client_actions}
        except ToolError as e:
            self.memory.audit(p["tool"], p["args"], "error", str(e))
            return {"status": "error", "error": str(e), "actions": []}
        except Exception as e:
            self.memory.audit(p["tool"], p["args"], "error", repr(e))
            return {"status": "error", "error": f"{type(e).__name__}", "actions": []}
