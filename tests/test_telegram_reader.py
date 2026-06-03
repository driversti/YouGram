from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from yougram.telegram_reader import ChatNotResolved, TelegramReader


def _msg(id, text, when, username=None):
    sender = SimpleNamespace(username=username, first_name=None) if username else None
    return SimpleNamespace(id=id, message=text, date=when, sender=sender)


def _dialog(id, name, *, channel=False, group=False):
    return SimpleNamespace(id=id, name=name, is_channel=channel, is_group=group)


class FakeClient:
    """Mimics the subset of Telethon's async API that TelegramReader uses."""

    def __init__(self, *, messages=None, dialogs=None, filters=None, entities=None, failing=None):
        self._messages = messages or []
        self._dialogs = dialogs or []
        self._filters = filters or []
        self._entities = entities or {}
        self._failing = set(failing or [])
        self.seen_chats = []
        self.resolved = []

    def iter_messages(self, chat, limit=None, search=None):
        self.seen_chats.append(chat)
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

    async def __call__(self, request):
        return SimpleNamespace(filters=self._filters)

    async def get_entity(self, peer):
        self.resolved.append(peer)
        if peer in self._failing:
            raise ValueError(f"Cannot resolve {peer!r}")
        if peer in self._entities:
            return self._entities[peer]
        # Default: a generic accessible channel (no username) so message-reading
        # tests that don't care about links still resolve.
        return SimpleNamespace(
            id=peer if isinstance(peer, int) else 0,
            title=None, username=None, broadcast=True, megagroup=False,
        )


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


async def test_fetch_messages_handles_naive_since():
    # The LLM may pass a naive `since` (no tzinfo); comparing it against
    # Telethon's UTC-aware dates must not raise TypeError. Default tz is UTC.
    client = FakeClient(messages=[
        _msg(2, "today", datetime(2026, 6, 2, 23, tzinfo=timezone.utc)),
        _msg(1, "old", datetime(2026, 5, 1, tzinfo=timezone.utc)),
    ])
    reader = TelegramReader(client)

    out = await reader.fetch_messages("chan", since=datetime(2026, 6, 2, 0, 0), limit=10)

    # Naive midnight -> 2026-06-02 00:00 UTC: the 23:00 msg is kept, May dropped.
    assert [m.id for m in out] == [2]


async def test_fetch_messages_naive_since_uses_configured_tz():
    from zoneinfo import ZoneInfo

    # Europe/Warsaw is UTC+2 in June, so naive 02:00 -> 00:00 UTC.
    client = FakeClient(messages=[
        _msg(2, "after", datetime(2026, 6, 2, 1, tzinfo=timezone.utc)),    # 01:00 UTC >= cutoff
        _msg(1, "before", datetime(2026, 6, 1, 23, tzinfo=timezone.utc)),  # prev-day 23:00 UTC < cutoff
    ])
    reader = TelegramReader(client, tz=ZoneInfo("Europe/Warsaw"))

    out = await reader.fetch_messages("chan", since=datetime(2026, 6, 2, 2, 0), limit=10)

    assert [m.id for m in out] == [2]


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


async def test_list_dialogs_fuzzy_matches_typo():
    client = FakeClient(dialogs=[
        _dialog(1, "News", channel=True),
        _dialog(2, "Sports", channel=True),
    ])
    reader = TelegramReader(client)

    out = await reader.list_dialogs("newz")  # typo for "news"

    assert [d.id for d in out] == [1]


def _folder(id, title, include_peers=()):
    return SimpleNamespace(id=id, title=title, include_peers=list(include_peers))


def _channel_entity(id, title, *, broadcast=True, megagroup=False):
    return SimpleNamespace(id=id, title=title, broadcast=broadcast, megagroup=megagroup)


async def test_list_folders_returns_named_folders_only():
    client = FakeClient(filters=[
        SimpleNamespace(),                 # DialogFilterDefault — no title, skipped
        _folder(1, "AI"),
        _folder(2, "Friends"),
    ])
    reader = TelegramReader(client)

    out = await reader.list_folders()

    assert [(f.id, f.title) for f in out] == [(1, "AI"), (2, "Friends")]


async def test_list_folders_normalizes_textwithentities_title():
    client = FakeClient(filters=[_folder(1, SimpleNamespace(text="AI"))])
    reader = TelegramReader(client)

    out = await reader.list_folders()

    assert out[0].title == "AI"


async def test_chats_in_folder_resolves_member_chats():
    client = FakeClient(
        filters=[_folder(1, "AI", include_peers=["p1", "p2"])],
        entities={
            "p1": _channel_entity(10, "AI News", broadcast=True),
            "p2": _channel_entity(11, "AI Chat", broadcast=False, megagroup=True),
        },
    )
    reader = TelegramReader(client)

    out = await reader.chats_in_folder("ai")  # fuzzy / case-insensitive

    assert [(d.id, d.name, d.kind) for d in out] == [
        (10, "AI News", "channel"),
        (11, "AI Chat", "group"),
    ]


async def test_chats_in_folder_unknown_returns_empty():
    client = FakeClient(filters=[_folder(1, "AI")])
    reader = TelegramReader(client)

    assert await reader.chats_in_folder("nonexistent") == []


def test_entity_ref_converts_numeric_strings():
    assert TelegramReader._entity_ref("123") == 123
    assert TelegramReader._entity_ref("-100500") == -100500
    assert TelegramReader._entity_ref("@chan") == "@chan"
    assert TelegramReader._entity_ref("News") == "News"


async def test_resolve_chat_returns_dialog():
    client = FakeClient(entities={555: _channel_entity(555, "Crypto", broadcast=True)})
    reader = TelegramReader(client)

    d = await reader.resolve_chat(555)

    assert (d.id, d.name, d.kind) == (555, "Crypto", "channel")


async def test_chats_in_folder_skips_inaccessible_peers():
    # A folder may include a channel the account can't open; skip it, keep the rest.
    client = FakeClient(
        filters=[_folder(1, "AI", include_peers=["ok", "bad"])],
        entities={"ok": _channel_entity(10, "AI News", broadcast=True)},
        failing={"bad"},
    )
    reader = TelegramReader(client)

    out = await reader.chats_in_folder("ai")

    assert [d.id for d in out] == [10]


async def test_search_messages_routes_numeric_ref_to_int():
    client = FakeClient(messages=[])
    reader = TelegramReader(client)

    await reader.search_messages("q", ["555"], limit=5)

    assert 555 in client.resolved  # "555" -> int 555 passed to get_entity via _entity_ref


def test_message_link_public_uses_username():
    e = SimpleNamespace(username="news", broadcast=True, megagroup=False, id=10)
    assert TelegramReader._message_link(e, 55) == "https://t.me/news/55"


def test_message_link_private_channel_uses_c_id():
    e = SimpleNamespace(username=None, broadcast=True, megagroup=False, id=777)
    assert TelegramReader._message_link(e, 7) == "https://t.me/c/777/7"


def test_message_link_none_when_no_username_and_not_channel():
    e = SimpleNamespace(username=None, broadcast=False, megagroup=False, id=5)
    assert TelegramReader._message_link(e, 1) is None


def test_message_link_none_for_none_entity():
    assert TelegramReader._message_link(None, 1) is None


async def test_fetch_messages_populates_public_link():
    now = datetime(2026, 6, 2, 12, tzinfo=timezone.utc)
    client = FakeClient(
        messages=[_msg(42, "hi", now, username="bob")],
        entities={"@pub": SimpleNamespace(id=10, username="pub", broadcast=True, megagroup=False, title=None)},
    )
    reader = TelegramReader(client)

    out = await reader.fetch_messages("@pub", limit=10)

    assert out[0].link == "https://t.me/pub/42"


async def test_fetch_messages_populates_private_channel_link():
    now = datetime(2026, 6, 2, 12, tzinfo=timezone.utc)
    client = FakeClient(
        messages=[_msg(7, "hi", now)],
        entities={777: SimpleNamespace(id=777, username=None, broadcast=True, megagroup=False, title="Priv")},
    )
    reader = TelegramReader(client)

    out = await reader.fetch_messages(777, limit=10)

    assert out[0].link == "https://t.me/c/777/7"


async def test_fetch_messages_raises_when_chat_unresolvable():
    client = FakeClient(messages=[], failing={"ghost"})
    reader = TelegramReader(client)

    with pytest.raises(ChatNotResolved):
        await reader.fetch_messages("ghost")


async def test_search_messages_skips_unresolved_chats():
    now = datetime(2026, 6, 2, tzinfo=timezone.utc)
    client = FakeClient(
        messages=[_msg(1, "alpha", now)],
        entities={"@ok": SimpleNamespace(id=1, username="ok", broadcast=True, megagroup=False, title=None)},
        failing={"@bad"},
    )
    reader = TelegramReader(client)

    out = await reader.search_messages("alpha", ["@bad", "@ok"], limit=10)

    # "@bad" is skipped; only "@ok"'s message comes back.
    assert [m.id for m in out] == [1]


async def test_search_messages_populates_link():
    now = datetime(2026, 6, 2, tzinfo=timezone.utc)
    client = FakeClient(
        messages=[_msg(5, "alpha", now)],
        entities={"@chan": SimpleNamespace(id=99, username="chan", broadcast=True, megagroup=False, title=None)},
    )
    reader = TelegramReader(client)

    out = await reader.search_messages("alpha", ["@chan"], limit=10)

    assert out[0].link == "https://t.me/chan/5"


async def test_fetch_messages_wraps_non_valueerror_resolution_failure():
    class RpcLikeError(Exception):
        pass

    class FailingClient(FakeClient):
        async def get_entity(self, peer):
            raise RpcLikeError("CHANNEL_PRIVATE")

    reader = TelegramReader(FailingClient(messages=[]))

    with pytest.raises(ChatNotResolved):
        await reader.fetch_messages("some_channel")
