from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from yougram.telegram_reader import TelegramReader


def _msg(id, text, when, username=None):
    sender = SimpleNamespace(username=username, first_name=None) if username else None
    return SimpleNamespace(id=id, message=text, date=when, sender=sender)


def _dialog(id, name, *, channel=False, group=False):
    return SimpleNamespace(id=id, name=name, is_channel=channel, is_group=group)


class FakeClient:
    """Mimics the subset of Telethon's async iterators that TelegramReader uses."""

    def __init__(self, *, messages=None, dialogs=None):
        self._messages = messages or []
        self._dialogs = dialogs or []

    def iter_messages(self, chat, limit=None, search=None):
        items = self._messages
        if search is not None:
            items = [m for m in items if search.casefold() in (m.message or "").casefold()]

        async def gen():
            for m in items[: (limit or len(items))]:
                yield m

        return gen()

    def iter_dialogs(self):
        async def gen():
            for d in self._dialogs:
                yield d

        return gen()


async def test_fetch_messages_maps_and_skips_empty():
    now = datetime(2026, 6, 2, 12, tzinfo=timezone.utc)
    client = FakeClient(messages=[
        _msg(1, "hi", now, username="bob"),
        _msg(2, "", now),          # empty/service message -> skipped
        _msg(3, "there", now),
    ])
    reader = TelegramReader(client)

    out = await reader.fetch_messages("chan", limit=10)

    assert [m.id for m in out] == [1, 3]
    assert out[0].sender == "bob"
    assert out[0].text == "hi"


async def test_fetch_messages_stops_at_since():
    base = datetime(2026, 6, 2, tzinfo=timezone.utc)
    client = FakeClient(messages=[
        _msg(3, "newest", base),
        _msg(2, "older", base - timedelta(days=1)),
        _msg(1, "oldest", base - timedelta(days=2)),
    ])
    reader = TelegramReader(client)

    out = await reader.fetch_messages("chan", since=base - timedelta(hours=12), limit=10)

    assert [m.id for m in out] == [3]


async def test_search_messages_across_chats():
    now = datetime(2026, 6, 2, tzinfo=timezone.utc)
    client = FakeClient(messages=[
        _msg(1, "alpha topic", now),
        _msg(2, "beta", now),
        _msg(3, "more alpha", now),
    ])
    reader = TelegramReader(client)

    out = await reader.search_messages("alpha", ["a", "b"], limit=10)

    # matched in both chats -> 2 hits per chat == 4
    assert [m.id for m in out] == [1, 3, 1, 3]


async def test_search_messages_stops_at_since():
    base = datetime(2026, 6, 2, tzinfo=timezone.utc)
    client = FakeClient(messages=[
        _msg(3, "alpha newest", base),
        _msg(2, "alpha older", base - timedelta(days=1)),
        _msg(1, "alpha oldest", base - timedelta(days=2)),
    ])
    reader = TelegramReader(client)

    out = await reader.search_messages("alpha", ["a"], since=base - timedelta(hours=12), limit=10)

    assert [m.id for m in out] == [3]


async def test_list_dialogs_filters_by_name_and_kind():
    client = FakeClient(dialogs=[
        _dialog(1, "News Channel", channel=True),
        _dialog(2, "Friends Group", group=True),
        _dialog(3, "Newsletter", channel=True),
    ])
    reader = TelegramReader(client)

    out = await reader.list_dialogs("news")

    assert [(d.id, d.kind) for d in out] == [(1, "channel"), (3, "channel")]
