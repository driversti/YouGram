from dataclasses import dataclass
from datetime import datetime, timezone

from yougram.context import ConversationContext
from yougram.models import Dialog, Folder, Message
from yougram.tools import Deps, chats_in_folder, fetch_messages, list_dialogs, list_folders, search_messages


@dataclass
class FakeReader:
    """Records calls and returns canned results."""

    calls: list = None

    def __post_init__(self):
        self.calls = []

    async def fetch_messages(self, chat, since=None, limit=100):
        self.calls.append(("fetch", chat, since, limit))
        return [Message(id=1, date=datetime(2026, 6, 2, tzinfo=timezone.utc), sender="x", text="hi")]

    async def search_messages(self, query, chats, since=None, limit=50):
        self.calls.append(("search", query, chats, since, limit))
        return [Message(id=2, date=datetime(2026, 6, 2, tzinfo=timezone.utc), sender="y", text="alpha")]

    async def list_dialogs(self, query, limit=20):
        self.calls.append(("dialogs", query, limit))
        return [Dialog(id=3, name="News", kind="channel")]

    async def list_folders(self):
        self.calls.append(("folders",))
        return [Folder(id=1, title="AI")]

    async def chats_in_folder(self, name, limit=50):
        self.calls.append(("chats_in_folder", name, limit))
        return [Dialog(id=9, name="AI News", kind="channel")]

    async def resolve_chat(self, ref):
        self.calls.append(("resolve_chat", ref))
        return Dialog(id=42, name=f"resolved:{ref}", kind="channel")


def _ctx(reader, context=None, user_id=None):
    class Ctx:
        deps = Deps(reader=reader, context=context, user_id=user_id)

    return Ctx()


async def test_fetch_messages_tool_delegates():
    reader = FakeReader()
    out = await fetch_messages(_ctx(reader), chat="chan", limit=5)
    assert out[0].text == "hi"
    assert reader.calls == [("fetch", "chan", None, 5)]


async def test_search_messages_tool_delegates():
    reader = FakeReader()
    out = await search_messages(_ctx(reader), query="alpha", chats=["a", "b"])
    assert out[0].text == "alpha"
    assert reader.calls[0][0] == "search"


async def test_list_dialogs_tool_delegates():
    reader = FakeReader()
    out = await list_dialogs(_ctx(reader), query="news")
    assert out[0].name == "News"
    assert reader.calls == [("dialogs", "news", 20)]


async def test_list_folders_tool_delegates():
    reader = FakeReader()
    out = await list_folders(_ctx(reader))
    assert out[0].title == "AI"
    assert reader.calls == [("folders",)]


async def test_chats_in_folder_tool_delegates():
    reader = FakeReader()
    out = await chats_in_folder(_ctx(reader), name="ai")
    assert out[0].name == "AI News"
    assert reader.calls == [("chats_in_folder", "ai", 50)]


async def test_fetch_messages_tool_reports_unresolved_chat():
    from yougram.telegram_reader import ChatNotResolved

    class FailReader:
        async def fetch_messages(self, chat, since=None, limit=100):
            raise ChatNotResolved(chat)

    out = await fetch_messages(_ctx(FailReader()), chat="ghost")

    assert isinstance(out, str)
    assert "ghost" in out


async def test_fetch_messages_sets_active_chat_on_success():
    reader = FakeReader()
    context = ConversationContext()
    await fetch_messages(_ctx(reader, context, user_id=7), chat="News")
    active = context.get_chat(7)
    assert active is not None
    assert active.name == "resolved:News"


async def test_fetch_messages_without_context_does_not_crash():
    reader = FakeReader()
    out = await fetch_messages(_ctx(reader), chat="News")  # no context/user_id
    assert out[0].text == "hi"


async def test_fetch_messages_unresolved_does_not_set_active_chat():
    from yougram.telegram_reader import ChatNotResolved

    class FailReader:
        async def fetch_messages(self, chat, since=None, limit=100):
            raise ChatNotResolved(chat)

    context = ConversationContext()
    out = await fetch_messages(_ctx(FailReader(), context, user_id=7), chat="ghost")
    assert isinstance(out, str)
    assert context.get_chat(7) is None


async def test_search_messages_sets_active_chat_for_single_chat():
    reader = FakeReader()
    context = ConversationContext()
    await search_messages(_ctx(reader, context, user_id=7), query="x", chats=["Solo"])
    assert context.get_chat(7).name == "resolved:Solo"


async def test_search_messages_multi_chat_does_not_set_active_chat():
    reader = FakeReader()
    context = ConversationContext()
    await search_messages(_ctx(reader, context, user_id=7),
                          query="x", chats=["A", "B"])
    assert context.get_chat(7) is None
