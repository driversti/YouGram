from telethon import events

from .agent import ask


async def handle_question(event, agent, reader, allowed_user_id: int) -> None:
    """Core handler: ignore anyone but the owner, else answer their question.

    Kept free of Telethon registration so it can be unit-tested with a fake
    event. `event` needs `.sender_id`, `.raw_text`, and an async `.reply()`.
    """
    if event.sender_id != allowed_user_id:
        return
    answer = await ask(agent, reader, event.raw_text)
    await event.reply(answer)


def register_bot(bot_client, agent, reader, allowed_user_id: int) -> None:
    """Wire `handle_question` to the bot-client's incoming-message events."""

    @bot_client.on(events.NewMessage(incoming=True))
    async def _handler(event):
        await handle_question(event, agent, reader, allowed_user_id)
