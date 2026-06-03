from dataclasses import dataclass
from datetime import datetime

from pydantic_ai import RunContext

from .models import Dialog, Folder, Message
from .telegram_reader import ChatNotResolved, TelegramReader


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
) -> list[Message] | str:
    """Fetch recent messages from a single chat (newest first).

    `chat` is a chat title, @username, or numeric id. Pass `since` (UTC) to stop
    at messages older than that time, e.g. for "today". Each message includes a
    `link` you can show the user. If the chat can't be resolved, returns a short
    explanation string instead of raising.
    """
    try:
        return await ctx.deps.reader.fetch_messages(chat, since=since, limit=limit)
    except ChatNotResolved:
        return (
            f"Could not find a chat matching '{chat}'. Resolve it first with "
            f"list_dialogs/chats_in_folder, or ask the user to name a folder or channel."
        )


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


async def list_folders(ctx: RunContext[Deps]) -> list[Folder]:
    """List the user's Telegram chat folders by name.

    Call this when the user refers to a "folder" so you can then read the chats
    inside the one they mean.
    """
    return await ctx.deps.reader.list_folders()


async def chats_in_folder(ctx: RunContext[Deps], name: str) -> list[Dialog]:
    """List the channels/chats inside the folder whose name best matches `name`.

    Then read each with `fetch_messages` (e.g. to summarize a folder "today").
    """
    return await ctx.deps.reader.chats_in_folder(name)
