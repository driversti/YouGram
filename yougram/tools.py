from dataclasses import dataclass
from datetime import datetime

from pydantic_ai import RunContext

from .context import ConversationContext
from .models import Dialog, Folder, Message
from .telegram_reader import ChatNotResolved, TelegramReader


@dataclass
class Deps:
    """Dependencies injected into every tool call for one agent run.

    `context` + `user_id` let the read tools record the active chat (the single
    chat they just resolved) so follow-up questions like "his last post" work.
    Both are optional so `ask`/tests can run without conversation memory.
    """

    reader: TelegramReader
    context: ConversationContext | None = None
    user_id: int | None = None


async def _remember_chat(ctx: RunContext[Deps], chat: str) -> None:
    """Record `chat` as the active chat, if memory is available and it resolves.

    Telethon already cached the entity during the read, so this resolve is cheap.
    Any failure is ignored — remembering the chat is best-effort.
    """
    deps = ctx.deps
    if deps.context is None or deps.user_id is None:
        return
    try:
        dialog = await deps.reader.resolve_chat(chat)
    except Exception:  # noqa: BLE001 — best-effort; never break the read on this
        return
    deps.context.set_chat(deps.user_id, dialog)


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
        messages = await ctx.deps.reader.fetch_messages(chat, since=since, limit=limit)
    except ChatNotResolved:
        return (
            f"Could not find a chat matching '{chat}'. Resolve it first with "
            f"list_dialogs/chats_in_folder, or ask the user to name a folder or channel."
        )
    await _remember_chat(ctx, chat)  # single chat resolved -> make it the active chat
    return messages


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
    results = await ctx.deps.reader.search_messages(query, chats, since=since, limit=limit)
    if len(chats) == 1:  # only an unambiguous single-chat search sets context
        await _remember_chat(ctx, chats[0])
    return results


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
