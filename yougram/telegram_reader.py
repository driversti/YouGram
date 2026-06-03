import difflib
from datetime import datetime, timezone, tzinfo

from telethon.tl.functions.messages import GetDialogFiltersRequest

from .models import Dialog, Folder, Message


class ChatNotResolved(Exception):
    """Raised when a chat reference can't be resolved to a Telegram entity."""

    def __init__(self, chat):
        self.chat = chat
        super().__init__(f"Could not resolve chat: {chat!r}")


class TelegramReader:
    """Read-only wrapper over a Telethon user-client.

    Accepts any object exposing the async iterators `iter_messages` and
    `iter_dialogs` (the real `telethon.TelegramClient`, or a fake in tests).
    `tz` is the timezone a naive `since` is interpreted in (defaults to UTC).
    """

    def __init__(self, client, tz: tzinfo | None = None):
        self._client = client
        self._tz = tz or timezone.utc

    async def fetch_messages(self, chat, since: datetime | None = None, limit: int = 100) -> list[Message]:
        since = self._as_aware(since)
        entity = await self._resolve_entity(chat)
        out: list[Message] = []
        async for m in self._client.iter_messages(entity, limit=limit):
            if since is not None and m.date < since:
                break  # iter_messages yields newest-first; older than `since` -> done
            if not m.message:
                continue  # skip service/empty messages
            out.append(self._to_message(m, entity))
        return out

    async def search_messages(self, query: str, chats, since: datetime | None = None, limit: int = 50) -> list[Message]:
        since = self._as_aware(since)
        out: list[Message] = []
        for chat in chats:
            try:
                entity = await self._resolve_entity(chat)
            except ChatNotResolved:
                continue  # skip chats we can't resolve; keep searching the rest
            async for m in self._client.iter_messages(entity, search=query, limit=limit):
                if since is not None and m.date < since:
                    break
                if not m.message:
                    continue
                out.append(self._to_message(m, entity))
        return out

    async def list_dialogs(self, query: str, limit: int = 20) -> list[Dialog]:
        needle = query.casefold()
        scored: list[tuple[float, Dialog]] = []
        async for d in self._client.iter_dialogs():
            name = d.name or ""
            score = self._match_score(needle, name)
            if score > 0:
                scored.append((score, Dialog(id=d.id, name=name, kind=self._kind(d))))
        # Stable sort: equal-scored (e.g. all substring) keep their original order.
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [dialog for _, dialog in scored[:limit]]

    async def list_folders(self) -> list[Folder]:
        filters = await self._fetch_filters()
        out: list[Folder] = []
        for f in filters:
            title = self._filter_title(f)
            if title is None:
                continue  # default/preset filter without a real title
            out.append(Folder(id=getattr(f, "id", 0), title=title))
        return out

    async def resolve_chat(self, ref) -> Dialog:
        """Resolve a chat reference (id, @username, or title) to a Dialog.

        Also primes Telethon's entity cache so later fetches by id succeed.
        """
        entity = await self._client.get_entity(ref)
        return self._entity_to_dialog(entity)

    async def chats_in_folder(self, name: str, limit: int = 50) -> list[Dialog]:
        filters = await self._fetch_filters()
        match = self._best_folder(name, filters)
        if match is None:
            return []
        out: list[Dialog] = []
        for peer in list(getattr(match, "include_peers", []))[:limit]:
            try:
                entity = await self._client.get_entity(peer)
            except Exception:  # noqa: BLE001 — skip chats we can't access, keep the rest
                continue
            out.append(self._entity_to_dialog(entity))
        return out

    async def _resolve_entity(self, chat):
        try:
            return await self._client.get_entity(self._entity_ref(chat))
        except ChatNotResolved:
            raise  # guard: a custom client wrapper may already raise this — don't double-wrap
        except Exception as exc:  # noqa: BLE001 — any Telethon resolution failure (RPCError, ValueError, ...)
            raise ChatNotResolved(chat) from exc

    async def _fetch_filters(self) -> list:
        result = await self._client(GetDialogFiltersRequest())
        # Modern Telethon returns messages.DialogFilters (.filters); older a list.
        return list(getattr(result, "filters", result))

    def _best_folder(self, name: str, filters: list):
        needle = name.casefold()
        best, best_score = None, 0.0
        for f in filters:
            title = self._filter_title(f)
            if title is None:
                continue
            score = self._match_score(needle, title)
            if score > best_score:
                best, best_score = f, score
        return best

    @staticmethod
    def _entity_ref(chat):
        """A numeric-string chat (e.g. '555' from forward context) -> int id."""
        if isinstance(chat, str) and chat.lstrip("-").isdigit():
            return int(chat)
        return chat

    @staticmethod
    def _filter_title(f) -> str | None:
        title = getattr(f, "title", None)
        if title is None:
            return None
        return getattr(title, "text", title)  # TextWithEntities -> str, or plain str

    @staticmethod
    def _entity_to_dialog(e) -> Dialog:
        return Dialog(
            id=getattr(e, "id", 0),
            name=TelegramReader._entity_name(e),
            kind=TelegramReader._entity_kind(e),
        )

    @staticmethod
    def _entity_name(e) -> str:
        title = getattr(e, "title", None)
        if title:
            return title
        return getattr(e, "username", None) or getattr(e, "first_name", None) or str(getattr(e, "id", ""))

    @staticmethod
    def _entity_kind(e) -> str:
        # Duck-typed so it works for both real Telethon entities and test fakes.
        if getattr(e, "broadcast", False):
            return "channel"
        if getattr(e, "megagroup", False):
            return "group"
        if getattr(e, "title", None) is not None:
            return "group"  # basic group chat
        return "user"

    @staticmethod
    def _match_score(needle: str, name: str) -> float:
        """Rank a candidate name against `needle` (already casefolded).

        Substring hits all score 2.0 (kept in original order by the stable sort);
        otherwise a difflib similarity ratio, ignored below 0.6.
        """
        low = name.casefold()
        if needle in low:
            return 2.0
        ratio = difflib.SequenceMatcher(None, needle, low).ratio()
        return ratio if ratio >= 0.6 else 0.0

    def _as_aware(self, since: datetime | None) -> datetime | None:
        """Make `since` timezone-aware for comparison with Telethon's UTC dates.

        The LLM often passes a naive `since` (e.g. start of "today" with no
        tzinfo); a naive vs aware comparison raises TypeError. A naive value is
        interpreted as being in the configured timezone (`self._tz`).
        """
        if since is not None and since.tzinfo is None:
            return since.replace(tzinfo=self._tz)
        return since

    @staticmethod
    def _kind(d) -> str:
        if getattr(d, "is_channel", False):
            return "channel"
        if getattr(d, "is_group", False):
            return "group"
        return "user"

    @staticmethod
    def _message_link(entity, message_id) -> str | None:
        """Build a t.me permalink for a message in `entity`.

        Public channel (has @username) -> https://t.me/<username>/<id>.
        Private channel/supergroup -> https://t.me/c/<internal_id>/<id>.
        Otherwise (no username, not a channel) there is no public link.
        """
        if entity is None:
            return None
        username = getattr(entity, "username", None)
        if username:
            return f"https://t.me/{username}/{message_id}"
        cid = getattr(entity, "id", None)
        is_channel = getattr(entity, "broadcast", False) or getattr(entity, "megagroup", False)
        if cid and is_channel:
            return f"https://t.me/c/{cid}/{message_id}"
        return None

    @staticmethod
    def _to_message(m, entity=None) -> Message:
        sender = None
        if m.sender is not None:
            sender = getattr(m.sender, "username", None) or getattr(m.sender, "first_name", None)
        return Message(
            id=m.id,
            date=m.date,
            sender=sender,
            text=m.message,
            link=TelegramReader._message_link(entity, m.id),
        )
