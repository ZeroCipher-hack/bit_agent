"""Little games for kids (and grown-ups). Randomness is decided here, on the server, so Bit can't 'cheat'."""
import secrets

from .base import Tool, ToolContext, ToolError

BEATS = {"rock": "scissors", "paper": "rock", "scissors": "paper"}


class PlayGame(Tool):
    name = "play_game"
    description = ("Play a game on your face. games: "
                   "'shot' — the user pretends to shoot you ('paq!', 'seni otdim', 'bang', 'пиу'): a bullet hits your screen, "
                   "it cracks, you get knocked out with X eyes and stars, then you reboot and point back — play along dramatically and funny; "
                   "'rps' — rock-paper-scissors (tosh-qaychi-qogʻoz / камень-ножницы-бумага), pass the user's choice; "
                   "'dice' — roll a die; 'coin' — flip a coin; 'peekaboo' — hide your eyes with your hands and pop out. "
                   "Returns the result so you can comment on it.")
    input_schema = {"type": "object", "properties": {
        "game": {"type": "string", "enum": ["shot", "rps", "dice", "coin", "peekaboo"]},
        "user_choice": {"type": "string", "enum": ["rock", "paper", "scissors"], "description": "rps only"}},
        "required": ["game"]}
    side_effect = False

    def validate(self, args):
        if args.get("game") not in ("shot", "rps", "dice", "coin", "peekaboo"):
            raise ToolError("unknown game")
        if args.get("game") == "rps" and args.get("user_choice") not in BEATS:
            raise ToolError("rps needs user_choice: rock, paper or scissors (ask the user first)")

    async def run(self, args, ctx: ToolContext):
        game = args["game"]
        res = {"game": game}
        if game == "rps":
            user, bit = args["user_choice"], secrets.choice(list(BEATS))
            res.update(user=user, bit=bit, winner="draw" if user == bit else ("bit" if BEATS[bit] == user else "user"))
        elif game == "dice":
            res["value"] = secrets.randbelow(6) + 1
        elif game == "coin":
            res["side"] = secrets.choice(["heads", "tails"])
        ctx.client_actions.append({"type": "game", **res})
        return res
