from telethon import events

from .agent import ask
from .chunking import split_message
from .context import HISTORY_TURNS
from .forwards import extract_forward_source


async def handle_question(event, agent, reader, context, allowed_user_id: int) -> None:
    """Owner-only handler. A forward sets the current chat, a /command manages
    memory; any other message is answered, with the current chat (if any) injected
    as context."""
    if event.sender_id != allowed_user_id:
        return

    source = extract_forward_source(event.message)
    if source is not None:
        await _handle_forward(event, reader, context, allowed_user_id, source)
        return

    command = _command_name(event.raw_text)
    if command is not None:
        await _handle_command(event, context, allowed_user_id, command)
        return

    question = event.raw_text
    current = context.get_chat(allowed_user_id)
    if current is not None:
        question = (
            f"[Current chat context: '{current.name}' (id={current.id}). "
            f"Apply the question to this chat unless another is named.]\n{question}"
        )

    try:
        # Show "typing…" while the model works; Telethon auto-repeats it until
        # the block exits, so the owner can see the bot is busy.
        async with event.client.action(event.chat_id, "typing"):
            answer = await ask(agent, reader, question,
                               context=context, user_id=allowed_user_id)
    except Exception as exc:  # noqa: BLE001 — surface any failure to the owner
        await event.reply(f"⚠️ Error: {exc}")
        return
    for chunk in split_message(answer):  # Telegram caps a message at 4096 chars
        # link_preview=False: post links shouldn't expand into big preview cards.
        await event.reply(chunk, link_preview=False)


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


def _command_name(text: str | None) -> str | None:
    """Return the normalized command (e.g. '/clear') if `text` is a command.

    Tolerates case and a '@botname' suffix Telegram adds in groups; returns None
    for ordinary messages so they fall through to the question path."""
    if not text:
        return None
    first = text.strip().split(maxsplit=1)[0] if text.strip() else ""
    if not first.startswith("/"):
        return None
    return first.split("@", 1)[0].casefold()


async def _handle_command(event, context, allowed_user_id: int, command: str) -> None:
    if command == "/clear":
        context.clear(allowed_user_id)
        await event.reply("🧹 Памʼять очищено. Починаємо з чистого листа.")
        return
    if command == "/status":
        await event.reply(_status_text(context, allowed_user_id))
        return
    await event.reply("Невідома команда. Доступні: /clear, /status")


def _status_text(context, allowed_user_id: int) -> str:
    chat = context.get_chat(allowed_user_id)
    turns = context.turn_count(allowed_user_id)
    chat_line = f"📍 Активний чат: {chat.name}" if chat else "📍 Активний чат: немає"
    return f"{chat_line}\n💬 Памʼять: {turns} із {HISTORY_TURNS} ходів"


def register_bot(bot_client, agent, reader, context, allowed_user_id: int) -> None:
    """Wire `handle_question` to the bot-client's incoming-message events."""

    @bot_client.on(events.NewMessage(incoming=True))
    async def _handler(event):
        await handle_question(event, agent, reader, context, allowed_user_id)
