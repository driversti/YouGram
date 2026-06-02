"""One-time interactive login to create the user-client .session file.

Run locally (or `docker compose run` with a TTY) once:
    uv run python scripts/login.py
Telegram will SMS a code; enter it when prompted. This writes <session>.session,
which is the key to your account — keep it secret (it is gitignored).
"""

import asyncio

from telethon import TelegramClient

from yougram.config import Settings


async def main() -> None:
    s = Settings()
    client = TelegramClient(s.session_name, s.api_id, s.api_hash)
    await client.start()  # prompts for phone + code on first run
    me = await client.get_me()
    print(f"Logged in as {me.username or me.first_name} (id={me.id}).")
    print(f"Set YOUGRAM_ALLOWED_USER_ID={me.id} in your .env.")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
