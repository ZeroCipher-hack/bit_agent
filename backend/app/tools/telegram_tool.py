"""Send a Telegram message from the user's own account (Telethon), only to whitelisted contacts, always after a yes."""
import time

from .. import config
from .base import Tool, ToolContext, ToolError


def resolve_contact(name: str) -> tuple[str, str]:
    contacts = config.load_contacts()
    key = name.strip().lower().lstrip("@")
    if key in contacts:
        return key, contacts[key]
    for k, v in contacts.items():  # allow the raw @username / phone if it is whitelisted
        if v.lower().lstrip("@") == key or v == name.strip():
            return k, v
    known = ", ".join(sorted(contacts)) or "none yet (edit data/contacts.json)"
    raise ToolError(f"'{name}' is not in the contacts whitelist. Allowed: {known}")


class SendTelegram(Tool):
    name = "send_telegram"
    description = ("Send a Telegram message from the user's own account to a contact in their whitelist (by the name the "
                   "user uses, e.g. 'ali', 'onam'). The user must confirm before it is sent. Write the text exactly as the user "
                   "wants it sent. Returns {status}.")
    input_schema = {"type": "object", "properties": {
        "recipient": {"type": "string", "description": "contact name from the whitelist"},
        "text": {"type": "string", "description": "message text, max 1000 chars"}}, "required": ["recipient", "text"]}
    risky = True

    def validate(self, args):
        text = str(args.get("text", "")).strip()
        if not text or len(text) > 1000:
            raise ToolError("text must be 1..1000 characters")
        resolve_contact(str(args.get("recipient", "")))
        if not (config.TELEGRAM_API_ID and config.TELEGRAM_API_HASH and config.TELEGRAM_SESSION):
            raise ToolError("Telegram is not set up on the server (TELEGRAM_API_ID / HASH / SESSION missing)")

    def summary(self, args):
        key, target = resolve_contact(str(args["recipient"]))
        return f"Telegram → {key} ({target}): «{str(args['text']).strip()}»"

    async def run(self, args, ctx: ToolContext):
        self.validate(args)
        sent = ctx.memory.count_audit_since(self.name, "ok", time.time() - 3600)
        if sent >= config.TELEGRAM_MAX_PER_HOUR:
            raise ToolError(f"hourly limit reached ({config.TELEGRAM_MAX_PER_HOUR} messages)")
        from telethon import TelegramClient
        from telethon.sessions import StringSession

        _, target = resolve_contact(str(args["recipient"]))
        client = TelegramClient(StringSession(config.TELEGRAM_SESSION), config.TELEGRAM_API_ID, config.TELEGRAM_API_HASH)
        await client.connect()
        try:
            if not await client.is_user_authorized():
                raise ToolError("Telegram session is not authorized; run scripts/telegram_login.py again")
            await client.send_message(target, str(args["text"]).strip())
        finally:
            await client.disconnect()
        return {"status": "sent"}
