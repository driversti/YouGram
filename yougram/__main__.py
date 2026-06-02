import asyncio
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from telethon import TelegramClient

from .agent import build_agent
from .bot import register_bot
from .config import Settings
from .context import ConversationContext
from .telegram_reader import TelegramReader


async def main() -> None:
    # Load .env into the process environment so provider keys (e.g.
    # ANTHROPIC_API_KEY) reach pydantic-ai. Does not override vars already set
    # (so Docker's env_file still wins).
    load_dotenv()
    s = Settings()

    user_client = TelegramClient(s.session_name, s.api_id, s.api_hash)
    bot_client = TelegramClient(f"{s.session_name}-bot", s.api_id, s.api_hash)

    # The user session must already exist (created via scripts/login.py).
    await user_client.start()
    await bot_client.start(bot_token=s.bot_token)

    reader = TelegramReader(user_client, tz=ZoneInfo(s.timezone))
    agent = build_agent(s.llm_model, s.timezone)
    context = ConversationContext()
    register_bot(bot_client, agent, reader, context, s.allowed_user_id)

    print(f"YouGram running. Model={s.llm_model}. Owner={s.allowed_user_id}.")
    try:
        await bot_client.run_until_disconnected()
    except (asyncio.CancelledError, KeyboardInterrupt):
        pass  # Ctrl+C — fall through to a clean disconnect
    finally:
        await user_client.disconnect()
        await bot_client.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nYouGram stopped.")
