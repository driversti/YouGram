from types import SimpleNamespace
from unittest.mock import AsyncMock

import yougram.bot as bot_module
from yougram.bot import handle_question


class FakeEvent:
    def __init__(self, sender_id, text):
        self.sender_id = sender_id
        self.raw_text = text
        self.reply = AsyncMock()


async def test_ignores_non_whitelisted_user(monkeypatch):
    spy = AsyncMock(return_value="should not be called")
    monkeypatch.setattr(bot_module, "ask", spy)
    event = FakeEvent(sender_id=999, text="hi")

    await handle_question(event, agent=object(), reader=object(), allowed_user_id=777)

    spy.assert_not_awaited()
    event.reply.assert_not_awaited()


async def test_answers_whitelisted_user(monkeypatch):
    spy = AsyncMock(return_value="here is your answer")
    monkeypatch.setattr(bot_module, "ask", spy)
    event = FakeEvent(sender_id=777, text="what did X say?")

    await handle_question(event, agent=object(), reader=object(), allowed_user_id=777)

    spy.assert_awaited_once()
    event.reply.assert_awaited_once_with("here is your answer")


async def test_replies_with_error_when_ask_fails(monkeypatch):
    spy = AsyncMock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr(bot_module, "ask", spy)
    event = FakeEvent(sender_id=777, text="anything")

    await handle_question(event, agent=object(), reader=object(), allowed_user_id=777)

    event.reply.assert_awaited_once()
    (sent,), _ = event.reply.call_args
    assert "boom" in sent
