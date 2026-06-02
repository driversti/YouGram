from datetime import datetime

from .models import Dialog, Message


class TelegramReader:
    """Read-only wrapper over a Telethon user-client.

    Accepts any object exposing the async iterators `iter_messages` and
    `iter_dialogs` (the real `telethon.TelegramClient`, or a fake in tests).
    """

    def __init__(self, client):
        self._client = client

    async def fetch_messages(self, chat, since: datetime | None = None, limit: int = 100) -> list[Message]:
        out: list[Message] = []
        async for m in self._client.iter_messages(chat, limit=limit):
            if since is not None and m.date < since:
                break  # iter_messages yields newest-first; older than `since` -> done
            if not m.message:
                continue  # skip service/empty messages
            out.append(self._to_message(m))
        return out

    async def search_messages(self, query: str, chats, since: datetime | None = None, limit: int = 50) -> list[Message]:
        out: list[Message] = []
        for chat in chats:
            async for m in self._client.iter_messages(chat, search=query, limit=limit):
                if since is not None and m.date < since:
                    break
                if not m.message:
                    continue
                out.append(self._to_message(m))
        return out

    async def list_dialogs(self, query: str, limit: int = 20) -> list[Dialog]:
        needle = query.casefold()
        out: list[Dialog] = []
        async for d in self._client.iter_dialogs():
            name = d.name or ""
            if needle in name.casefold():
                out.append(Dialog(id=d.id, name=name, kind=self._kind(d)))
                if len(out) >= limit:
                    break
        return out

    @staticmethod
    def _kind(d) -> str:
        if getattr(d, "is_channel", False):
            return "channel"
        if getattr(d, "is_group", False):
            return "group"
        return "user"

    @staticmethod
    def _to_message(m) -> Message:
        sender = None
        if m.sender is not None:
            sender = getattr(m.sender, "username", None) or getattr(m.sender, "first_name", None)
        return Message(id=m.id, date=m.date, sender=sender, text=m.message)
