from types import SimpleNamespace

from yougram.forwards import ForwardSource, extract_forward_source


def _message(fwd_from):
    return SimpleNamespace(fwd_from=fwd_from)


def test_non_forward_returns_none():
    assert extract_forward_source(_message(None)) is None


def test_none_message_returns_none():
    assert extract_forward_source(None) is None


def test_visible_channel_forward_is_resolvable():
    fwd = SimpleNamespace(from_id=SimpleNamespace(channel_id=555), from_name=None)
    src = extract_forward_source(_message(fwd))
    assert src == ForwardSource(resolvable=True, chat_id=555)


def test_hidden_origin_forward_is_not_resolvable():
    fwd = SimpleNamespace(from_id=None, from_name="Some Person")
    src = extract_forward_source(_message(fwd))
    assert src.resolvable is False
    assert src.name == "Some Person"
    assert src.chat_id is None
