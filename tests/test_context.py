from yougram.context import HISTORY_TURNS, ConversationContext
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


def test_history_append_and_get():
    ctx = ConversationContext()
    assert ctx.get_history(1) == []

    ctx.append_turn(1, ["q1", "a1"])
    assert ctx.get_history(1) == ["q1", "a1"]

    ctx.append_turn(1, ["q2", "a2"])
    assert ctx.get_history(1) == ["q1", "a1", "q2", "a2"]


def test_history_keeps_only_last_two_turns():
    ctx = ConversationContext()
    ctx.append_turn(1, ["q1", "a1"])
    ctx.append_turn(1, ["q2", "a2"])
    ctx.append_turn(1, ["q3", "a3"])  # third turn evicts the first
    assert ctx.get_history(1) == ["q2", "a2", "q3", "a3"]


def test_history_is_per_user():
    ctx = ConversationContext()
    ctx.append_turn(1, ["a"])
    ctx.append_turn(2, ["b"])
    assert ctx.get_history(1) == ["a"]
    assert ctx.get_history(2) == ["b"]


def test_clear_wipes_history_too():
    ctx = ConversationContext()
    ctx.append_turn(1, ["q", "a"])
    ctx.set_chat(1, Dialog(id=5, name="C", kind="channel"))
    ctx.clear(1)
    assert ctx.get_history(1) == []
    assert ctx.get_chat(1) is None


def test_empty_turn_is_ignored():
    ctx = ConversationContext()
    ctx.append_turn(1, [])  # trimming produced nothing — don't store an empty turn
    assert ctx.get_history(1) == []


def test_turn_count_starts_at_zero():
    ctx = ConversationContext()
    assert ctx.turn_count(777) == 0


def test_turn_count_counts_turns_not_messages():
    ctx = ConversationContext()
    ctx.append_turn(1, ["q1", "a1"])  # one turn = two messages
    assert ctx.turn_count(1) == 1
    ctx.append_turn(1, ["q2", "a2"])
    assert ctx.turn_count(1) == 2


def test_turn_count_caps_at_history_turns():
    ctx = ConversationContext()
    for i in range(5):
        ctx.append_turn(1, [f"q{i}", f"a{i}"])  # evicts older than HISTORY_TURNS
    assert ctx.turn_count(1) == HISTORY_TURNS
