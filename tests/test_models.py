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


def test_folder_holds_core_fields():
    from yougram.models import Folder

    f = Folder(id=2, title="AI")
    assert f.id == 2
    assert f.title == "AI"


def test_message_can_hold_link():
    from datetime import datetime, timezone

    from yougram.models import Message

    m = Message(id=1, date=datetime(2026, 6, 2, tzinfo=timezone.utc), sender=None,
                text="x", link="https://t.me/c/1/1")
    assert m.link == "https://t.me/c/1/1"


def test_message_link_defaults_to_none():
    from datetime import datetime, timezone

    from yougram.models import Message

    m = Message(id=1, date=datetime(2026, 6, 2, tzinfo=timezone.utc), sender=None, text="x")
    assert m.link is None
