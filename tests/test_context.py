from yougram.context import ConversationContext
from yougram.models import Dialog


def test_set_get_clear():
    ctx = ConversationContext()
    chat = Dialog(id=5, name="Crypto", kind="channel")

    assert ctx.get_chat(777) is None  # nothing yet

    ctx.set_chat(777, chat)
    assert ctx.get_chat(777) == chat

    ctx.clear(777)
    assert ctx.get_chat(777) is None


def test_clear_unknown_user_is_noop():
    ctx = ConversationContext()
    ctx.clear(999)  # must not raise
    assert ctx.get_chat(999) is None
