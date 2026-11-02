"""One-time Telegram login. Prints a session string to put into .env as TELEGRAM_SESSION.
Run:  docker compose run --rm bit python scripts/telegram_login.py
The session string gives full access to your account: keep it secret, never commit it."""
import asyncio
import os

from telethon import TelegramClient
from telethon.sessions import StringSession


async def main():
    api_id = int(os.getenv("TELEGRAM_API_ID") or input("api_id: "))
    api_hash = os.getenv("TELEGRAM_API_HASH") or input("api_hash: ")
    async with TelegramClient(StringSession(), api_id, api_hash) as client:  # asks phone, code, 2FA password
        me = await client.get_me()
        print(f"\nLogged in as {me.first_name} (@{me.username}).")
        print("\nTELEGRAM_SESSION=" + client.session.save())


asyncio.run(main())
