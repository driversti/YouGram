from datetime import datetime, timezone

from yougram.models import Dialog, Message


def test_message_holds_core_fields():
    m = Message(
        id=1,
        date=datetime(2026, 6, 2, tzinfo=timezone.utc),
        sender="alice",
        text="hello",
    )
    assert m.id == 1
    assert m.sender == "alice"
    assert m.text == "hello"


def test_dialog_holds_core_fields():
    d = Dialog(id=42, name="My Channel", kind="channel")
    assert d.id == 42
    assert d.name == "My Channel"
    assert d.kind == "channel"
