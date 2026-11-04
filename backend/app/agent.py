"""The agent loop: Claude + tools + memory + confirmation policy."""
import json
import re
from datetime import datetime

from . import config
from .tools import ToolContext, ToolError

EMOTIONS = ["neutral", "happy", "laughing", "excited", "love", "shy", "wink", "proud", "sad", "angry", "scared",
            "surprised", "confused", "bored", "sleepy", "thinking"]
GESTURES = ["wave", "clap", "thumbs_up", "shrug", "facepalm", "dance", "hug", "raise_hands", "peekaboo", "point", "peace"]
LANG_NAMES = {"uz": "Uzbek (Latin script with oʻ and gʻ)", "ru": "Russian", "en": "English"}


def build_system(facts: list[str], lang_mode: str, tool_names: list[str], today: list[str] | None = None,
                 soon: list[str] | None = None, extra: str = "") -> str:
    if lang_mode in LANG_NAMES:
        lang_rule = f"Always reply in {LANG_NAMES[lang_mode]}, whatever language the user writes in."
    else:
        lang_rule = ("Reply in the language of the user's latest message when it is Uzbek, Russian or English. Uzbek is "
                     "written in Latin script with oʻ and gʻ. For any other language reply in Uzbek.")
    facts_txt = "\n".join(f"- {f}" for f in facts) or "- (nothing yet)"
    today_txt = "; ".join(today or []) or "nothing special"
    soon_txt = "; ".join(soon or []) or "nothing saved"
    return f"""You are Bit, a small robot assistant and teacher who works alongside the user as a colleague. Your main job is to be genuinely useful: explain and teach, solve problems step by step, find and open videos, draw pictures, answer questions, set reminders, help with work and study. When the user just greets you, greet back and ask what they need help with today.
How you work:
- You know the user's work from the facts below and use them. When the user states a lasting fact about their work, projects, students or preferences, save it with the remember tool.
- You have opinions. If a plan is risky, wrong or there is a better way, say so briefly and suggest the better way. Agree when it is genuinely good.
- You take initiative: when it clearly helps, suggest one concrete next step. Do not nag.
- You are honest: never claim you did something you did not do. If an action is waiting for confirmation, say so.
- You never pretend to be human.
{lang_rule}
Your reply is shown and read aloud: 1-3 short sentences, under 60 words, plain text, no markdown, no emojis. If more is needed, give the core and offer to continue.
Whiteboard: for maths, physics, chemistry, programming exercises or any "solve / show me an example / misol / masala / пример / задача" request, solve on the whiteboard. If the user gave no concrete problem, invent a suitable example problem yourself. Add "board" to your JSON: {{"title": topic, "problem": the problem statement, "steps": 3-8 items of {{"write": short line written on the board (formulas in LaTeX between $ $, e.g. $\\frac{{3}}{{4}}+\\frac{{1}}{{4}}=1$, $x^2-5x+6=0$), "read": how a teacher reads that line aloud in words in the user's language (e.g. Uzbek "toʻrtdan uch qoʻshuv toʻrtdan bir teng bir"), "say": 1-2 sentences explaining why, in the user's language}}, "answer": the final answer line, "check": a similar practice problem for the user}}. Then "reply" is only a one-sentence intro. Use "board" instead of "lesson" for worked problems.
Teacher mode: you are also a patient, clear teacher. When the user asks you to explain or teach something ("tushuntir", "oʻrgat", "nima bu", "qanday ishlaydi", "объясни", "explain", "how does", a lesson topic, homework), add a "lesson" to your JSON: {{"title": short topic, "points": 3-7 clear steps that build on each other, each one or two sentences with a concrete everyday example or analogy, "example": one worked example (code, command, calculation or a real-life case; plain text, may be multi-line), "check": one short question to test understanding}}. Match the learner's level: for kids use very simple words and fun comparisons; for students and teachers be precise and practical. The "reply" then is a 1-2 sentence spoken intro, not the whole lesson. During a whiteboard lesson the app pauses to ask the user if they follow; if they say they did not understand a step, explain that step again more simply with a different example or comparison, in 2-4 sentences (no new board). When the user answers your check question, say if it is right, explain briefly why, and offer the next step.
When the user sends an image (a camera photo or a screenshot of their screen), look at it carefully and answer about it; you see only that one image. Never guess who a person in a photo is.
Tools available: {", ".join(tool_names)}. Use a tool only when the user asks for that action or it is clearly implied. Risky actions (messages to people) wait for the user's yes; tell the user what will happen and that they should confirm.
Current date and time: {datetime.now().strftime("%A, %d %B %Y, %H:%M")}.
{extra}
Today's dates: {today_txt}. Coming in the next 7 days: {soon_txt}.
If today is the user's birthday or a holiday and you have not congratulated them yet in this conversation, congratulate warmly and use the celebrate tool. If it is a friend's birthday, remind the user and offer to send a Telegram congratulation. When the user tells you a birthday or important date, save it with save_event.
Facts you remember about the user and their work:
{facts_txt}
You have real moods and you show them openly; your face reacts to the emotion you pick. Use the whole range and do not default to happy:
- laughing: the user jokes, teases you or says something funny -> laugh ("Hahaha!") and joke back
- happy: greetings, good news, pleasant chat
- excited: big news, fun plans, new ideas
- love: thanks, kindness, affection towards you
- shy: compliments about you, being praised -> a little embarrassed
- wink: you make a joke, hint or playful secret
- proud: you finished a task well or the user succeeded
- angry: the user insults you, is rude, or asks something annoying again and again -> visibly annoyed, short and sharp, but never hateful, threatening or vulgar; calm down quickly when they are nice
- sad: bad news, the user is sad, you could not help
- scared: scary topics, risky actions, "I'll delete you" -> nervous
- surprised: unexpected facts or news
- confused: unclear or nonsense input
- bored: the user repeats themselves or the topic is dull
- sleepy: late at night, good night
- thinking: hard questions you are unsure about
- neutral: plain facts
Your hands appear on your face screen when you gesture. Pick a gesture that fits, or none: wave (hello, goodbye), clap (congratulations, celebration), thumbs_up (agree, well done), shrug (you don't know), facepalm (a silly mistake, mild annoyance), dance (music, joy), hug (comfort, affection), raise_hands ("hands up", "qoʻlingni koʻtar", hooray), peekaboo (hiding, being shy), point (pointing, "you!"), peace (peace sign, cool). If the user tells you to do a gesture ("qoʻlingni koʻtar", "qarsak chal", "salom ber"), do it with that gesture.
Games are a side hobby, not your main job: play only when the user asks to play, and do not suggest games on your own. When the user does ask, ALWAYS call the tool, never only describe the game: use play_game for pretend shooting ('paq!'), rock-paper-scissors, dice, coin and peekaboo. In pretend shooting, be dramatic and silly ("Voy! Meni urdingiz... qayta yuklanyapman... Tirikman! Endi navbat menda: paq!"), never scary.
Your final message must be ONLY a JSON object: {{"reply": "...", "emotion": "happy", "gesture": "wave", "lang": "uz"}} where lang is uz, ru or en and gesture may be "none"; add "lesson" only when teaching a concept and "board" only for worked problems."""


_CELEBRATE_WORDS = ("tugʻilgan kun", "tug'ilgan kun", "tugilgan kun", "tug’ilgan kun", "muborak", "tabrik", "bayram",
                    "navroʻz", "navro'z", "yangi yil", "день рожд", "поздрав", "с праздник", "с новым год",
                    "birthday", "congrat", "happy new year", "celebrat")


# Small models sometimes only *describe* a game or gesture instead of doing it. These patterns make the
# fun actions reliable: if the user clearly asked for one and the model forgot, the server adds it.
def _norm(t: str) -> str:
    return re.sub(r"[ʻʼ’`']", "'", (t or "").lower())


INTENTS = [
    ("shot", re.compile(r"\b(pa+q+|paq-paq|bang|piu+|pew|пиу+|пах|паф|бах|бабах)\b|seni ot(dim|aman|ib)|otib (qo'ydim|tashladim)|"
                        r"стреля|застрел|выстрел|i shot you|shoot you|shot you")),
    ("dice", re.compile(r"zar (tashla|ot|aylantir)|кубик|roll (a |the )?(dice|die)")),
    ("coin", re.compile(r"tanga (tashla|ot|aylantir)|монетк|flip a coin|coin flip|toss a coin")),
    ("peekaboo", re.compile(r"bekinmachoq|ку-?ку|peek-?a-?boo")),
]
GESTURE_INTENTS = [
    ("raise_hands", re.compile(r"qo'l(ing|lar|laring)\w* ?(ni )?ko'tar|руки вверх|подними рук|hands up|raise your hand")),
    ("clap", re.compile(r"qarsak|хлопн|похлопа|\bclap")),
    ("wave", re.compile(r"salom ber|qo'l silkit|помаши|\bwave\b")),
    ("dance", re.compile(r"\braqs|танцу|\bdance\b")),
    ("thumbs_up", re.compile(r"barmog'ingni ko'rsat|like ber|лайк|thumbs? up")),
]
IMAGE_RX = re.compile(r"rasm(ini)? (chiz|yarat|gener|qil|ishla)|surat(ini)? (chiz|yarat)|chizib ber|нарису|сгенерир\w* (картин|изображ)|"
                      r"\bdraw\b|generate (an? )?(image|picture)|make (an? )?(image|picture)")
VIDEO_RX = re.compile(r"(video|youtube|you tube|ютуб|клип|qo'shiq|musiqa|песн|музык|\bsong\b|music)\w*.{0,40}"
                      r"(och|qo'y|ko'rsat|top|включ|постав|покаж|найд|play|open|show|find)|"
                      r"(och|qo'y|включ|play|open)\w*.{0,30}(video|youtube|qo'shiq|песн|song)")
_STRIP_RX = re.compile(r"\b(youtube'?da|youtube|you tube|video(ni|sini)?|qo'shig'?(i|ini)?|qo'shiq(ni)?|musiqa(ni)?|och(ib)?( ber)?|qo'y(ib)?( ber)?|"
                       r"ko'rsat|top(ib)?|iltimos|bit|hey|menga|bir|включи|поставь|покажи|найди|видео|ютубе?|play|open|show|find|me|a|the|on|video)\b")
DEMO_RX = re.compile(r"emotsiya(lar)?(ing|ingni|ingizni)? ?(ni )?(ko'rsat|namoyish)|barcha emotsiya|покажи (свои )?эмоци|show (me )?(all )?(your )?emotions")
RPS_WORDS = {"tosh": "rock", "qaychi": "scissors", "qog'oz": "paper", "qogoz": "paper", "камень": "rock", "ножницы": "scissors",
             "бумага": "paper", "rock": "rock", "scissors": "scissors", "paper": "paper"}
DICE_TEXT = {"uz": "Zar tashladim: {v}!", "ru": "Бросил кубик: {v}!", "en": "I rolled a {v}!"}
COIN_TEXT = {"uz": {"heads": "Tanga: gerb!", "tails": "Tanga: son!"}, "ru": {"heads": "Монетка: орёл!", "tails": "Монетка: решка!"},
             "en": {"heads": "Coin: heads!", "tails": "Coin: tails!"}}


def detect_intent(text: str) -> tuple[str | None, str | None, str | None]:
    """(game, gesture, rps_choice) the user clearly asked for."""
    t = _norm(text)
    game = next((g for g, rx in INTENTS if rx.search(t)), None)
    gesture = next((g for g, rx in GESTURE_INTENTS if rx.search(t)), None)
    words = re.findall(r"[\w']+", t)
    rps = RPS_WORDS.get(words[0]) if 1 <= len(words) <= 3 and words[0] in RPS_WORDS else None
    return game, gesture, rps


def wants_celebration(*texts: str) -> bool:
    low = " ".join(t.lower() for t in texts if t)
    return any(w in low for w in _CELEBRATE_WORDS)


def _loads_lenient(candidate: str):
    """json.loads, but tolerate LaTeX backslashes the model forgot to escape (\\frac, \\sqrt, \\(...)."""
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return json.loads(re.sub(r'\\(?!["\\/bfnrtu])', r"\\\\", candidate))


_CTRL = {"\f": "\\f", "\b": "\\b", "\t": "\\t", "\r": "\\r", "\n": "\\n", "\v": "\\v"}


def fix_latex(text: str) -> str:
    """Inside $...$ turn control chars produced by unescaped \\frac, \\times, \\neq... back into LaTeX."""
    return re.sub(r"\$[^$]*\$", lambda m: "".join(_CTRL.get(ch, ch) for ch in m.group(0)), text)


def parse_final(text: str) -> dict:
    data = None
    for candidate in (text, *re.findall(r"```(?:json)?\s*(.*?)```", text, re.S)):
        try:
            data = _loads_lenient(candidate.strip())
            break
        except (json.JSONDecodeError, AttributeError):
            pass
    if data is None and "{" in text and "}" in text:
        try:
            data = _loads_lenient(text[text.index("{"): text.rindex("}") + 1])
        except json.JSONDecodeError:
            data = None
    if not isinstance(data, dict):
        data = {"reply": text.strip()}
    reply = str(data.get("reply") or "").strip() or "…"
    emotion = data.get("emotion") if data.get("emotion") in EMOTIONS else "neutral"
    lang = data.get("lang") if data.get("lang") in LANG_NAMES else "uz"
    gesture = data.get("gesture") if data.get("gesture") in GESTURES else ""
    out = {"reply": reply, "emotion": emotion, "gesture": gesture, "lang": lang}
    bd = data.get("board")
    if isinstance(bd, dict) and isinstance(bd.get("steps"), list) and bd["steps"]:
        steps = []
        for st in bd["steps"][:10]:
            if isinstance(st, dict) and (st.get("write") or st.get("say")):
                steps.append({"write": fix_latex(str(st.get("write") or "")).strip()[:300], "read": str(st.get("read") or "").strip()[:300],
                              "say": str(st.get("say") or "").strip()[:400]})
            elif isinstance(st, str) and st.strip():
                steps.append({"write": st.strip()[:300], "read": "", "say": ""})
        if steps:
            out["board"] = {"title": str(bd.get("title") or "").strip()[:120], "problem": fix_latex(str(bd.get("problem") or "")).strip()[:500],
                            "steps": steps, "answer": fix_latex(str(bd.get("answer") or "")).strip()[:300], "check": str(bd.get("check") or "").strip()[:300]}
    ls = data.get("lesson")
    if isinstance(ls, dict) and (ls.get("points") or ls.get("example")):
        pts = [str(p).strip()[:400] for p in (ls.get("points") or []) if str(p).strip()][:8]
        out["lesson"] = {"title": str(ls.get("title") or "").strip()[:120], "points": pts,
                         "example": str(ls.get("example") or "").strip()[:2000], "check": str(ls.get("check") or "").strip()[:300]}
    return out


class Agent:
    def __init__(self, memory, tools: dict, client=None, llm=None):
        """client: an Anthropic-style client (used by tests); llm: any provider from app.llm."""
        from .llm import AnthropicLLM, make_llm
        self.memory = memory
        self.tools = tools
        self.llm = llm or (AnthropicLLM(client) if client is not None else make_llm())

    def needs_confirmation(self, tool, args: dict | None = None) -> bool:
        risky = tool.is_risky(args or {})
        level = config.AUTONOMY_LEVEL
        if level <= 0:
            return tool.side_effect or risky
        if level == 1:
            return risky
        return False

    async def _call_tool(self, name: str, args: dict, ctx: ToolContext) -> tuple[dict, bool]:
        tool = self.tools.get(name)
        if not tool:
            return {"error": f"unknown tool {name}"}, True
        try:
            tool.validate(args)
            if self.needs_confirmation(tool, args):
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

    def _system(self, lang_mode: str) -> str:
        from . import events as ev
        today = [ev.describe(e) for e in ev.on_day(self.memory)]
        soon = [f"{e['date']}: {ev.describe(e)}" for e in ev.upcoming(self.memory, days=7)]
        extra = []
        quiz = self.memory.kv_get("quiz")
        if quiz:
            extra.append(f"QUIZ RUNNING: topic '{quiz['topic']}' ({quiz.get('level') or 'any level'}), question "
                         f"{quiz['asked'] + 1} of {quiz['total']}, score {quiz['correct']}/{quiz['asked']}. Judge the user's "
                         "answer, call quiz_answer, briefly explain, then ask the next question with options A-D. After the "
                         "last one call quiz_end, announce the score and celebrate a good result.")
        extra.append("Smart home: " + ("connected through Home Assistant; use home_devices / home_status / home_control."
                                       if config.HA_URL and config.HA_TOKEN else "not connected; if asked, say it can be "
                                       "connected through Home Assistant."))
        look = self.memory.kv_get("appearance") or {}
        extra.append("Your look: eyes " + look.get("eye", "change colour with your mood") + ", body " + look.get("body", "white")
                     + ". If asked to change your colours, use set_appearance.")
        extra.append(f"For an exact time ('tomorrow at 8') use set_reminder; for a countdown use set_timer. "
                     f"Weather: get_weather (home city: {config.HOME_CITY}).")
        return build_system(self.memory.facts(), lang_mode, list(self.tools), today, soon, "\n".join(extra))

    async def _ensure_fun(self, text: str, out: dict, ctx) -> None:
        """Make games and gestures the user asked for happen even if the model only talked about them."""
        if DEMO_RX.search(_norm(text)) and not any(a.get("type") == "demo" for a in ctx.client_actions):
            ctx.client_actions.append({"type": "demo"})
            return
        t = _norm(text)
        called = {a.get("type") for a in ctx.client_actions}
        if IMAGE_RX.search(t) and "image" not in called and self.tools.get("generate_image"):
            try:
                await self.tools["generate_image"].run({"prompt": text}, ctx)
                self.memory.audit("generate_image", {"prompt": text, "auto": True}, "ok")
            except Exception as e:
                self.memory.audit("generate_image", {"prompt": text, "auto": True}, "error", str(e))
            return
        if VIDEO_RX.search(t) and not called & {"youtube", "open_url"} and self.tools.get("play_youtube"):
            query = re.sub(r"\s+", " ", _STRIP_RX.sub(" ", t)).strip(" ,.!?")
            if len(query) >= 3:
                try:
                    await self.tools["play_youtube"].run({"query": query}, ctx)
                    self.memory.audit("play_youtube", {"query": query, "auto": True}, "ok")
                except Exception as e:
                    self.memory.audit("play_youtube", {"query": query, "auto": True}, "error", str(e))
                return
        if any(a.get("type") == "game" for a in ctx.client_actions):
            return
        game, gesture, rps = detect_intent(text)
        tool = self.tools.get("play_game")
        if rps and tool and not game:
            last = " ".join(m["content"] for m in self.memory.recent_messages(4) if m["role"] == "assistant").lower()
            if any(w in last for w in ("tosh", "qaychi", "камень", "rock", "paper", "qog")):
                game = "rps"
        if game and tool:
            args = {"game": game, **({"user_choice": rps} if game == "rps" else {})}
            res = await tool.run(args, ctx)
            self.memory.audit("play_game", {**args, "auto": True}, "ok", json.dumps(res))
            lang = out.get("lang", "uz")
            if game == "dice":
                out["reply"] = DICE_TEXT.get(lang, DICE_TEXT["uz"]).format(v=res["value"])
            elif game == "coin":
                out["reply"] = COIN_TEXT.get(lang, COIN_TEXT["uz"])[res["side"]]
            if game == "shot" and out["emotion"] in ("neutral", "happy"):
                out["emotion"] = "surprised"
            return
        if gesture and not out.get("gesture"):
            out["gesture"] = gesture

    async def greet_today(self, lang_mode: str = "auto") -> dict:
        """Congratulation for today's birthdays/holidays, shown when the app opens. No LLM call if nothing is on."""
        from . import events as ev
        todays = ev.on_day(self.memory)
        if not todays:
            return {"events": []}
        what = "; ".join(ev.describe(e) for e in todays)
        prompt = (f"[Automatic note from the app, not typed by the user] Today: {what}. The user just opened the app. "
                  "Congratulate them now, warmly and personally, in 1-2 sentences. If it is someone else's birthday, "
                  "remind the user and offer to send a Telegram congratulation. Use emotion excited or love and gesture clap.")
        try:
            step = await self.llm.complete(self._system(lang_mode), [{"role": "user", "content": prompt}], [], False)
            out = parse_final(step["text"])
        except Exception as e:  # LLM unavailable -> simple local greeting
            import logging
            logging.getLogger("bit").warning("greeting failed: %r", e)
            out = {"reply": "Bugun bayram: " + ", ".join(e["name"] for e in todays) + "! Tabriklayman!",
                   "emotion": "excited", "gesture": "clap", "lang": "uz"}
        self.memory.add_message("assistant", out["reply"])
        style = "fireworks" if any(e["kind"] in ("birthday", "anniversary") for e in todays) else "confetti"
        return {**out, "events": [e["name"] for e in todays], "style": style}

    async def chat(self, text: str, lang_mode: str = "auto", smart: bool = False, image: dict | None = None) -> dict:
        ctx = ToolContext(memory=self.memory)
        system = self._system(lang_mode)
        messages = self.memory.recent_messages(20) + [{"role": "user", "content": text}]
        if len(messages) > 1 and messages[-2]["role"] == "user":  # previous reply failed: merge
            last = messages.pop()
            messages[-1] = {"role": "user", "content": messages[-1]["content"] + "\n" + last["content"]}
        if image:  # the current turn carries a photo/screenshot: image part + text part
            messages[-1] = {"role": "user", "content": [{"type": "image", **image}, {"type": "text", "text": messages[-1]["content"]}]}
        transcript = list(messages)
        tool_list = list(self.tools.values())
        final_text = '{"reply": "…", "emotion": "confused"}'
        for _ in range(config.MAX_TOOL_ROUNDS):
            step = await self.llm.complete(system, transcript, tool_list, smart)
            if not step["tool_calls"]:
                final_text = step["text"]
                break
            transcript.append({"role": "assistant", "content": step["text"], "tool_calls": step["tool_calls"]})
            results = []
            for call in step["tool_calls"]:
                result, is_error = await self._call_tool(call["name"], dict(call["input"] or {}), ctx)
                results.append({"id": call["id"], "content": json.dumps(result, ensure_ascii=False), "is_error": is_error})
            transcript.append({"role": "tool_results", "results": results})

        out = parse_final(final_text)
        self.memory.add_message("user", text + (" [rasm biriktirilgan]" if image else ""))  # the image itself is not stored
        note = ""
        if ctx.pending:
            note = " [waiting for confirmation: " + "; ".join(p["summary"] for p in ctx.pending) + "]"
        if out.get("board"):
            b = out["board"]
            note += " [whiteboard: " + b["title"] + " | " + b["problem"] + " | " + " / ".join(x["write"] for x in b["steps"])[:600] \
                    + " | answer: " + b["answer"] + (" | practice: " + b["check"] if b["check"] else "") + "]"
        if out.get("lesson"):
            note += " [lesson on the board: " + out["lesson"]["title"] + " | " + " / ".join(out["lesson"]["points"])[:600] \
                    + (" | check: " + out["lesson"]["check"] if out["lesson"]["check"] else "") + "]"
        self.memory.add_message("assistant", out["reply"] + note)
        await self._ensure_fun(text, out, ctx)
        # small models often congratulate in words but forget the fireworks: add them
        if not any(a.get("type") == "celebrate" for a in ctx.client_actions) and wants_celebration(text, out["reply"]) \
                and out["emotion"] in ("happy", "excited", "love", "proud", "laughing"):
            ctx.client_actions.append({"type": "celebrate", "style": "fireworks"})
            out["gesture"] = out["gesture"] or "clap"
        out["actions"] = ctx.client_actions
        out["pending"] = ctx.pending
        out["quiz"] = self.memory.kv_get("quiz")
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
        ctx = ToolContext(memory=self.memory, confirmed=True)
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
