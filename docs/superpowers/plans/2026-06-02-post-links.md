# Post Links + Robust Resolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the bot reliably find a post and return a clickable `t.me` link, and stop crashing when the agent passes an unresolvable chat name.

**Architecture:** `Message` gains a `link`. The reader resolves the target chat entity once per fetch/search (used both to build per-message permalinks and to detect resolution failure, which becomes a typed `ChatNotResolved`). The tool layer turns that into a friendly "name a folder/channel" message; the prompt tells the agent to resolve names first and to ask when scope is unknown.

**Tech Stack:** Python 3.12+, Telethon, Pydantic AI, pytest.

---

## File Structure

```
yougram/
  models.py            # Message gains link: str | None
  telegram_reader.py   # ChatNotResolved; _message_link; resolve-once + link in fetch/search; search skips unresolved
  tools.py             # fetch_messages tool catches ChatNotResolved -> friendly string
  agent.py             # prompt: resolve-first, ask-when-no-scope, show link
tests/
  test_models.py
  test_telegram_reader.py   # FakeClient gains failing set + default get_entity + resolved list
  test_tools.py
```

---

## Task 1: `Message.link` field

**Files:**
- Modify: `yougram/models.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: Append failing tests** to `tests/test_models.py`:

```python
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
```

- [ ] **Step 2: Run, verify FAIL**

Run: `uv run pytest tests/test_models.py -k "link" -v`
Expected: FAIL (`Message` has no `link`; passing `link=` raises a validation error).

- [ ] **Step 3: Add the field** in `yougram/models.py`. Change the `Message` class to:

```python
class Message(BaseModel):
    id: int
    date: datetime
    sender: str | None
    text: str
    link: str | None = None
```

- [ ] **Step 4: Run, verify PASS**

Run: `uv run pytest tests/test_models.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add yougram/models.py tests/test_models.py
git commit -m "feat: Message.link field"
```

---

## Task 2: `_message_link` permalink builder

A pure static helper. Public channels use `@username`; private channels use
`t.me/c/<id>`; anything else (no username and not a channel) has no public link.

**Files:**
- Modify: `yougram/telegram_reader.py`
- Test: `tests/test_telegram_reader.py`

- [ ] **Step 1: Append failing tests** to `tests/test_telegram_reader.py`:

```python
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
```

- [ ] **Step 2: Run, verify FAIL**

Run: `uv run pytest tests/test_telegram_reader.py -k "message_link" -v`
Expected: FAIL with `AttributeError: ... has no attribute '_message_link'`.

- [ ] **Step 3: Add the helper** to the `TelegramReader` class in `yougram/telegram_reader.py` (e.g. directly above `_to_message`):

```python
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
```

- [ ] **Step 4: Run, verify PASS**

Run: `uv run pytest tests/test_telegram_reader.py -k "message_link" -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add yougram/telegram_reader.py tests/test_telegram_reader.py
git commit -m "feat: t.me permalink builder"
```

---

## Task 3: Resolve chat once — populate links + raise `ChatNotResolved`

`fetch_messages`/`search_messages` resolve the chat entity once (via `get_entity`),
use it to populate each message's `link`, and convert resolution failures into a
typed `ChatNotResolved`. `fetch` raises it; `search` skips that chat and continues.

**Files:**
- Modify: `yougram/telegram_reader.py`
- Test: `tests/test_telegram_reader.py`

- [ ] **Step 1: Update the test scaffolding + add failing tests** in `tests/test_telegram_reader.py`.

(a) Change the import line at the top from:
```python
from yougram.telegram_reader import TelegramReader
```
to:
```python
import pytest

from yougram.telegram_reader import ChatNotResolved, TelegramReader
```

(b) REPLACE the whole `FakeClient` class with this version (adds a `failing` set, a `resolved` log, and a default-resolving `get_entity` so message tests that don't care about links still resolve):
```python
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
```

(c) UPDATE the existing `test_chats_in_folder_skips_inaccessible_peers` to make "bad" fail via the new `failing` set (default `get_entity` no longer raises on unknown peers). Replace that test with:
```python
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
```

(d) UPDATE the existing `test_search_messages_routes_numeric_ref_to_int` (fetch/search now iterate by the resolved entity, so the numeric conversion is observed at `get_entity`, recorded in `resolved`). Replace that test with:
```python
async def test_search_messages_routes_numeric_ref_to_int():
    client = FakeClient(messages=[])
    reader = TelegramReader(client)

    await reader.search_messages("q", ["555"], limit=5)

    assert 555 in client.resolved  # "555" -> int 555 passed to get_entity via _entity_ref
```

(e) APPEND these new tests:
```python
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
```

- [ ] **Step 2: Run the reader suite, verify FAIL**

Run: `uv run pytest tests/test_telegram_reader.py -v`
Expected: FAIL — `ImportError: cannot import name 'ChatNotResolved'` (and the new link/resolve tests fail once that's fixed).

- [ ] **Step 3: Implement** in `yougram/telegram_reader.py`.

(a) Add the exception at module level (after the imports, before the class):
```python
class ChatNotResolved(Exception):
    """Raised when a chat reference can't be resolved to a Telegram entity."""

    def __init__(self, chat):
        self.chat = chat
        super().__init__(f"Could not resolve chat: {chat!r}")
```

(b) Add a private resolver method to the class (e.g. above `_fetch_filters`):
```python
    async def _resolve_entity(self, chat):
        try:
            return await self._client.get_entity(self._entity_ref(chat))
        except ChatNotResolved:
            raise
        except Exception as exc:  # noqa: BLE001 — any Telethon resolution failure
            raise ChatNotResolved(chat) from exc
```

(c) Replace `fetch_messages` with (resolves once, iterates by entity, sets link):
```python
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
```

(d) Replace `search_messages` with (per-chat resolve, skip unresolved, set link):
```python
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
```

(e) Replace `_to_message` to accept the resolved entity and set the link:
```python
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
```

- [ ] **Step 4: Run the reader suite, verify PASS**

Run: `uv run pytest tests/test_telegram_reader.py -v`
Expected: ALL pass — existing message/search tests still pass (they resolve to the default entity), plus the new link/resolve/skip tests.

- [ ] **Step 5: Commit**

```bash
git add yougram/telegram_reader.py tests/test_telegram_reader.py
git commit -m "feat: resolve chat once to build links and detect unresolved chats"
```

---

## Task 4: Tool reports unresolved chats instead of crashing

**Files:**
- Modify: `yougram/tools.py`
- Test: `tests/test_tools.py`

- [ ] **Step 1: Append failing test** to `tests/test_tools.py`:

```python
async def test_fetch_messages_tool_reports_unresolved_chat():
    from yougram.telegram_reader import ChatNotResolved

    class FailReader:
        async def fetch_messages(self, chat, since=None, limit=100):
            raise ChatNotResolved(chat)

    out = await fetch_messages(_ctx(FailReader()), chat="ghost")

    assert isinstance(out, str)
    assert "ghost" in out
```

- [ ] **Step 2: Run, verify FAIL**

Run: `uv run pytest tests/test_tools.py -k "unresolved" -v`
Expected: FAIL — the tool currently lets `ChatNotResolved` propagate (the test asserts a returned string).

- [ ] **Step 3: Implement** in `yougram/tools.py`.

Change the telegram_reader import line from:
```python
from .telegram_reader import TelegramReader
```
to:
```python
from .telegram_reader import ChatNotResolved, TelegramReader
```

Replace the `fetch_messages` tool function with:
```python
async def fetch_messages(
    ctx: RunContext[Deps],
    chat: str,
    since: datetime | None = None,
    limit: int = 100,
) -> list[Message] | str:
    """Fetch recent messages from a single chat (newest first).

    `chat` is a chat title, @username, or numeric id. Pass `since` (UTC) to stop
    at messages older than that time, e.g. for "today". Each message includes a
    `link` you can show the user. If the chat can't be resolved, returns a short
    explanation string instead of raising.
    """
    try:
        return await ctx.deps.reader.fetch_messages(chat, since=since, limit=limit)
    except ChatNotResolved:
        return (
            f"Could not find a chat matching '{chat}'. Resolve it first with "
            f"list_dialogs/chats_in_folder, or ask the user to name a folder or channel."
        )
```

- [ ] **Step 4: Run the tools suite, verify PASS**

Run: `uv run pytest tests/test_tools.py -v`
Expected: ALL pass.

- [ ] **Step 5: Commit**

```bash
git add yougram/tools.py tests/test_tools.py
git commit -m "feat: fetch tool reports unresolved chats instead of crashing"
```

---

## Task 5: Prompt — resolve-first, ask-when-no-scope, show links

No new unit test (prompt text); verified by the full suite staying green and the
agent test passing.

**Files:**
- Modify: `yougram/agent.py`

- [ ] **Step 1: Update `SYSTEM_PROMPT`** in `yougram/agent.py`.

Replace the existing bullet that starts with "- To answer questions about a named channel/group/person" with:
```
- To answer questions about a named channel/group/person, call `list_dialogs`
  (fuzzy/typo-tolerant) FIRST to resolve the name into a concrete chat, then pass
  the returned id/@username to the read tools. NEVER pass a raw human name
  straight to `fetch_messages`/`search_messages` — it will fail to resolve.
- If asked which chat discussed something but there is no current chat context
  and no chat/folder is named, ASK the user to name a folder or channel — do not
  guess.
```

Replace the bullet that starts with "- Answer concisely. Quote or summarize" with:
```
- Answer concisely. Quote or summarize ONLY the actual messages the tools
  returned; never invent content. When you reference a specific post, include its
  `link` field so the user can open it.
```

- [ ] **Step 2: Run the full suite**

Run: `uv run pytest -q`
Expected: ALL tests pass (the agent test's `TestModel` still drives the agent; `Message` now carries `link`, default `None`, which is harmless).

- [ ] **Step 3: Commit**

```bash
git add yougram/agent.py
git commit -m "feat: prompt resolves names first, asks when scope unknown, shows links"
```

---

## Self-Review notes (already applied)

- **Spec coverage:** robust resolution / no-crash (T3 `ChatNotResolved`, T4 tool message); resolve-first + ask-when-no-scope prompt (T5); scoped search via skip-unresolved + prompt (T3/T5); links public/private/none (T1/T2/T3); per-chat continue on failure in search (T3). All covered.
- **Type consistency:** `Message.link: str | None` (T1) populated via `_message_link` (T2) in `_to_message(m, entity)` (T3); `ChatNotResolved` defined T3, imported in tests T3 and in `tools.py` T4; `_resolve_entity` used by both fetch/search (T3).
- **No placeholders:** every code step contains complete code.

## Notes for the implementer

- `fetch`/`search` now iterate by the **resolved entity**, not the raw ref — this is why `test_search_messages_routes_numeric_ref_to_int` asserts on `client.resolved` (get_entity), not `seen_chats`.
- The default `FakeClient.get_entity` returns a generic channel so the many existing message tests keep working without declaring entities. Tests that need a *failure* use the `failing=` set.
- `t.me/c/<id>` links open only for chats the account is a member of; that's expected. There is no public link for basic groups or DMs, so `link` is `None` there.
