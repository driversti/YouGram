from types import SimpleNamespace
from unittest.mock import AsyncMock

import yougram.bot as bot_module
from yougram.bot import handle_question
from yougram.context import ConversationContext
from yougram.models import Dialog


class FakeAction:
    """Async context manager standing in for Telethon's client.action(...)."""

    def __init__(self, log, chat_id, kind):
        self.log, self.chat_id, self.kind = log, chat_id, kind

    async def __aenter__(self):
        self.log.append(("typing_on", self.chat_id, self.kind))
        return self

    async def __aexit__(self, *exc):
        self.log.append(("typing_off",))
        return False


class FakeClient:
    def __init__(self, log):
        self._log = log

    def action(self, chat_id, kind):
        return FakeAction(self._log, chat_id, kind)


class FakeEvent:
    def __init__(self, sender_id, text, message=None, chat_id=555):
        self.sender_id = sender_id
        self.raw_text = text
        self.message = message  # None => not a forward
        self.chat_id = chat_id
        self.reply = AsyncMock()
        self.action_log = []
        self.client = FakeClient(self.action_log)


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
    event.reply.assert_awaited_once_with("here is your answer", link_preview=False)


async def test_answer_replies_disable_link_preview(monkeypatch):
    # Post links in answers must not expand into big preview cards.
    spy = AsyncMock(return_value="see https://t.me/chan/42")
    monkeypatch.setattr(bot_module, "ask", spy)
    event = FakeEvent(sender_id=777, text="link?")

    await handle_question(event, agent=object(), reader=FakeReader(),
                          context=ConversationContext(), allowed_user_id=777)

    assert event.reply.await_args.kwargs["link_preview"] is False


async def test_long_answer_is_split_into_multiple_replies(monkeypatch):
    long_answer = "\n".join("word " * 200 for _ in range(20))  # well over 4096
    spy = AsyncMock(return_value=long_answer)
    monkeypatch.setattr(bot_module, "ask", spy)
    event = FakeEvent(sender_id=777, text="tell me everything")

    await handle_question(event, agent=object(), reader=FakeReader(),
                          context=ConversationContext(), allowed_user_id=777)

    assert event.reply.await_count > 1  # split across several messages
    sent = [call.args[0] for call in event.reply.await_args_list]
    assert all(len(s) <= 4000 for s in sent)  # every part fits Telegram's limit


async def test_shows_typing_indicator_while_working(monkeypatch):
    event = FakeEvent(sender_id=777, text="hi")

    async def fake_ask(*args, **kwargs):
        event.action_log.append(("asked",))  # records WHEN ask runs
        return "done"

    monkeypatch.setattr(bot_module, "ask", fake_ask)

    await handle_question(event, agent=object(), reader=FakeReader(),
                          context=ConversationContext(), allowed_user_id=777)

    # Typing turns on before ask, ask runs, typing turns off after.
    assert [e[0] for e in event.action_log] == ["typing_on", "asked", "typing_off"]
    assert event.action_log[0] == ("typing_on", event.chat_id, "typing")


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


async def test_clear_command_wipes_memory(monkeypatch):
    spy = AsyncMock(return_value="should not run")
    monkeypatch.setattr(bot_module, "ask", spy)
    context = ConversationContext()
    context.set_chat(777, Dialog(id=5, name="Crypto", kind="channel"))
    context.append_turn(777, ["q", "a"])
    event = FakeEvent(sender_id=777, text="/clear")

    await handle_question(event, agent=object(), reader=FakeReader(),
                          context=context, allowed_user_id=777)

    spy.assert_not_awaited()  # a command is not a question
    assert context.get_chat(777) is None
    assert context.turn_count(777) == 0
    event.reply.assert_awaited_once()  # a confirmation is sent


async def test_status_command_reports_chat_and_memory(monkeypatch):
    spy = AsyncMock(return_value="should not run")
    monkeypatch.setattr(bot_module, "ask", spy)
    context = ConversationContext()
    context.set_chat(777, Dialog(id=5, name="Crypto", kind="channel"))
    context.append_turn(777, ["q", "a"])
    event = FakeEvent(sender_id=777, text="/status")

    await handle_question(event, agent=object(), reader=FakeReader(),
                          context=context, allowed_user_id=777)

    spy.assert_not_awaited()
    (sent,), _ = event.reply.call_args
    assert "Crypto" in sent  # the active chat name
    assert "1" in sent  # one turn in memory


async def test_status_command_when_empty(monkeypatch):
    monkeypatch.setattr(bot_module, "ask", AsyncMock())
    context = ConversationContext()
    event = FakeEvent(sender_id=777, text="/status")

    await handle_question(event, agent=object(), reader=FakeReader(),
                          context=context, allowed_user_id=777)

    event.reply.assert_awaited_once()  # still replies, even with nothing stored


async def test_command_is_case_insensitive_and_ignores_bot_suffix(monkeypatch):
    monkeypatch.setattr(bot_module, "ask", AsyncMock())
    context = ConversationContext()
    context.append_turn(777, ["q", "a"])
    event = FakeEvent(sender_id=777, text="/Clear@YouGramBot")

    await handle_question(event, agent=object(), reader=FakeReader(),
                          context=context, allowed_user_id=777)

    assert context.turn_count(777) == 0  # matched despite case + @suffix


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
