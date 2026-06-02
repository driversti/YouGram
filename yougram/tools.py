from dataclasses import dataclass
from datetime import datetime

from pydantic_ai import RunContext

from .models import Dialog, Message
from .telegram_reader import TelegramReader


@dataclass
class Deps:
    """Dependencies injected into every tool call for one agent run."""

    reader: TelegramReader


async def list_dialogs(ctx: RunContext[Deps], query: str) -> list[Dialog]:
    """Find channels, groups, or chats whose title contains `query`.

    Use this first to resolve a human name (e.g. "my girlfriend", "tech news")
    into concrete chats before fetching or searching messages.
    """
    return await ctx.deps.reader.list_dialogs(query)


async def fetch_messages(
    ctx: RunContext[Deps],
    chat: str,
    since: datetime | None = None,
    limit: int = 100,
) -> list[Message]:
    """Fetch recent messages from a single chat (newest first).

    `chat` is a chat title, @username, or numeric id. Pass `since` (UTC) to stop
    at messages older than that time, e.g. for "today".
    """
    return await ctx.deps.reader.fetch_messages(chat, since=since, limit=limit)


async def search_messages(
    ctx: RunContext[Deps],
    query: str,
    chats: list[str],
    since: datetime | None = None,
    limit: int = 50,
) -> list[Message]:
    """Text-search for `query` across one or more `chats`.

    Use to answer "did anyone mention X" across several channels/groups.
    """
    return await ctx.deps.reader.search_messages(query, chats, since=since, limit=limit)
