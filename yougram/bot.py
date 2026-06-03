from telethon import events

from .agent import ask
from .chunking import split_message
from .forwards import extract_forward_source


async def handle_question(event, agent, reader, context, allowed_user_id: int) -> None:
    """Owner-only handler. A forward sets the current chat; any other message is
    answered, with the current chat (if any) injected as context."""
    if event.sender_id != allowed_user_id:
        return

    source = extract_forward_source(event.message)
    if source is not None:
        await _handle_forward(event, reader, context, allowed_user_id, source)
        return

    question = event.raw_text
    current = context.get_chat(allowed_user_id)
    if current is not None:
        question = (
            f"[Current chat context: '{current.name}' (id={current.id}). "
            f"Apply the question to this chat unless another is named.]\n{question}"
        )

    try:
        answer = await ask(agent, reader, question,
                           context=context, user_id=allowed_user_id)
    except Exception as exc:  # noqa: BLE001 — surface any failure to the owner
        await event.reply(f"⚠️ Error: {exc}")
        return
    for chunk in split_message(answer):  # Telegram caps a message at 4096 chars
        await event.reply(chunk)


async def _handle_forward(event, reader, context, allowed_user_id, source) -> None:
    if not source.resolvable:
        await event.reply(
            "Походження форварду приховане приватністю 🔒 "
            "Назви канал приблизно — я пошукаю."
        )
        return
    try:
        chat = await reader.resolve_chat(source.chat_id)
    except Exception as exc:  # noqa: BLE001
        await event.reply(f"⚠️ Не вдалося відкрити канал: {exc}")
        return
    context.set_chat(allowed_user_id, chat)
    await event.reply(f"Контекст: {chat.name}. Тепер питай про нього 🙂")


def register_bot(bot_client, agent, reader, context, allowed_user_id: int) -> None:
    """Wire `handle_question` to the bot-client's incoming-message events."""

    @bot_client.on(events.NewMessage(incoming=True))
    async def _handler(event):
        await handle_question(event, agent, reader, context, allowed_user_id)
