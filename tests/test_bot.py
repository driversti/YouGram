from types import SimpleNamespace
from unittest.mock import AsyncMock

import yougram.bot as bot_module
from yougram.bot import handle_question
from yougram.context import ConversationContext
from yougram.models import Dialog


class FakeEvent:
    def __init__(self, sender_id, text, message=None):
        self.sender_id = sender_id
        self.raw_text = text
        self.message = message  # None => not a forward
        self.reply = AsyncMock()


class FakeReader:
    def __init__(self, chat=None):
        self._chat = chat

    async def resolve_chat(self, ref):
        return self._chat


def _forward_message(channel_id):
    fwd = SimpleNamespace(from_id=SimpleNamespace(channel_id=channel_id), from_name=None)
    return SimpleNamespace(fwd_from=fwd)


async def test_ignores_non_whitelisted_user(monkeypatch):
    spy = AsyncMock(return_value="nope")
    monkeypatch.setattr(bot_module, "ask", spy)
    event = FakeEvent(sender_id=999, text="hi")

    await handle_question(event, agent=object(), reader=FakeReader(),
                          context=ConversationContext(), allowed_user_id=777)

    spy.assert_not_awaited()
    event.reply.assert_not_awaited()


async def test_answers_whitelisted_user(monkeypatch):
    spy = AsyncMock(return_value="here is your answer")
    monkeypatch.setattr(bot_module, "ask", spy)
    event = FakeEvent(sender_id=777, text="what did X say?")

    await handle_question(event, agent=object(), reader=FakeReader(),
                          context=ConversationContext(), allowed_user_id=777)

    spy.assert_awaited_once()
    event.reply.assert_awaited_once_with("here is your answer")


async def test_replies_with_error_when_ask_fails(monkeypatch):
    spy = AsyncMock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr(bot_module, "ask", spy)
    event = FakeEvent(sender_id=777, text="anything")

    await handle_question(event, agent=object(), reader=FakeReader(),
                          context=ConversationContext(), allowed_user_id=777)

    event.reply.assert_awaited_once()
    (sent,), _ = event.reply.call_args
    assert "boom" in sent


async def test_forward_sets_context_and_acknowledges(monkeypatch):
    spy = AsyncMock(return_value="should not run")
    monkeypatch.setattr(bot_module, "ask", spy)
    context = ConversationContext()
    reader = FakeReader(chat=Dialog(id=555, name="Crypto", kind="channel"))
    event = FakeEvent(sender_id=777, text="", message=_forward_message(555))

    await handle_question(event, agent=object(), reader=reader,
                          context=context, allowed_user_id=777)

    spy.assert_not_awaited()  # a forward is not a question
    assert context.get_chat(777).name == "Crypto"
    (sent,), _ = event.reply.call_args
    assert "Crypto" in sent


async def test_question_injects_current_chat_context(monkeypatch):
    spy = AsyncMock(return_value="ok")
    monkeypatch.setattr(bot_module, "ask", spy)
    context = ConversationContext()
    context.set_chat(777, Dialog(id=5, name="Crypto", kind="channel"))
    event = FakeEvent(sender_id=777, text="what's new over 3 days?")

    await handle_question(event, agent=object(), reader=FakeReader(),
                          context=context, allowed_user_id=777)

    spy.assert_awaited_once()
    (_, _, question), _ = spy.call_args  # ask(agent, reader, question)
    assert "Crypto" in question
    assert "id=5" in question
    assert "what's new over 3 days?" in question


async def test_ask_receives_context_and_user_id(monkeypatch):
    spy = AsyncMock(return_value="ok")
    monkeypatch.setattr(bot_module, "ask", spy)
    context = ConversationContext()
    event = FakeEvent(sender_id=777, text="hello")

    await handle_question(event, agent=object(), reader=FakeReader(),
                          context=context, allowed_user_id=777)

    spy.assert_awaited_once()
    _, kwargs = spy.call_args
    assert kwargs["context"] is context
    assert kwargs["user_id"] == 777


async def test_forward_inaccessible_chat_replies_with_error(monkeypatch):
    monkeypatch.setattr(bot_module, "ask", AsyncMock())
    context = ConversationContext()

    class FailReader:
        async def resolve_chat(self, ref):
            raise ValueError("no access")

    event = FakeEvent(sender_id=777, text="", message=_forward_message(555))

    await handle_question(event, agent=object(), reader=FailReader(),
                          context=context, allowed_user_id=777)

    event.reply.assert_awaited_once()
    (sent,), _ = event.reply.call_args
    assert "відкрити" in sent or "Error" in sent
    assert context.get_chat(777) is None  # context NOT set on failure
