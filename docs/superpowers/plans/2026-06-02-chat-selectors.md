# Chat Selectors Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user pick which chats to read without exact @usernames — by folder, by fuzzy name, or by forwarding a message (which sets a remembered "current chat" context).

**Architecture:** New read capabilities on `TelegramReader` (folders, fuzzy dialog ranking, entity resolution) exposed as new Pydantic AI tools; a small in-memory `ConversationContext` plus a forward-metadata parser in the bot layer that sets/injects the current chat. All selectors feed the existing `fetch_messages`/`search_messages`.

**Tech Stack:** Python 3.12+, Telethon (dialog filters + forward headers), Pydantic AI, `difflib` (stdlib) for fuzzy matching, pytest.

---

## File Structure

```
yougram/
  models.py            # + Folder value object
  telegram_reader.py   # + list_folders, chats_in_folder, resolve_chat; fuzzy list_dialogs; numeric chat refs
  tools.py             # + list_folders, chats_in_folder tools
  forwards.py          # NEW: ForwardSource + extract_forward_source(message)
  context.py           # NEW: ConversationContext (in-memory current-chat store)
  bot.py               # forward handling + context injection (signature change)
  agent.py             # register new tools + prompt update
  __main__.py          # construct ConversationContext, pass to register_bot
tests/
  test_models.py
  test_telegram_reader.py   # FakeClient extended with __call__ + get_entity
  test_tools.py
  test_forwards.py          # NEW
  test_context.py           # NEW
  test_bot.py               # rewritten for new signature + forward/context
  test_agent.py             # FakeReader gains folder methods
```

---

## Task 1: Folder model

**Files:**
- Modify: `yougram/models.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: Add the failing test** — append to `tests/test_models.py`:

```python
def test_folder_holds_core_fields():
    from yougram.models import Folder

    f = Folder(id=2, title="AI")
    assert f.id == 2
    assert f.title == "AI"
```

- [ ] **Step 2: Run it, verify FAIL**

Run: `uv run pytest tests/test_models.py::test_folder_holds_core_fields -v`
Expected: FAIL with `ImportError: cannot import name 'Folder'`.

- [ ] **Step 3: Add `Folder` to `yougram/models.py`** — append after the `Dialog` class:

```python
class Folder(BaseModel):
    id: int
    title: str
```

- [ ] **Step 4: Run it, verify PASS**

Run: `uv run pytest tests/test_models.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add yougram/models.py tests/test_models.py
git commit -m "feat: add Folder value object"
```

---

## Task 2: Fuzzy `list_dialogs` ranking

Make `list_dialogs` typo-tolerant and ranked: exact substring matches first (in their original order), then `difflib` similarity ≥ 0.6.

**Files:**
- Modify: `yougram/telegram_reader.py`
- Test: `tests/test_telegram_reader.py`

- [ ] **Step 1: Add the failing test** — append to `tests/test_telegram_reader.py`:

```python
async def test_list_dialogs_fuzzy_matches_typo():
    client = FakeClient(dialogs=[
        _dialog(1, "News", channel=True),
        _dialog(2, "Sports", channel=True),
    ])
    reader = TelegramReader(client)

    out = await reader.list_dialogs("newz")  # typo for "news"

    assert [d.id for d in out] == [1]
```

- [ ] **Step 2: Run it, verify FAIL**

Run: `uv run pytest tests/test_telegram_reader.py::test_list_dialogs_fuzzy_matches_typo -v`
Expected: FAIL (current substring-only `list_dialogs` returns `[]` for "newz").

- [ ] **Step 3: Replace `list_dialogs` and add `_match_score`** in `yougram/telegram_reader.py`.

Add `import difflib` at the top (below the existing `from datetime import ...` line). Replace the whole `list_dialogs` method with:

```python
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
```

- [ ] **Step 4: Run the reader suite, verify PASS**

Run: `uv run pytest tests/test_telegram_reader.py -v`
Expected: ALL pass — the new fuzzy test passes AND `test_list_dialogs_filters_by_name_and_kind` still returns `[(1, "channel"), (3, "channel")]` (both are substring matches scoring 2.0, preserved in order by the stable sort).

- [ ] **Step 5: Commit**

```bash
git add yougram/telegram_reader.py tests/test_telegram_reader.py
git commit -m "feat: fuzzy ranking for list_dialogs"
```

---

## Task 3: Folders — `list_folders` and `chats_in_folder`

**Files:**
- Modify: `yougram/telegram_reader.py`
- Test: `tests/test_telegram_reader.py`

- [ ] **Step 1: Extend `FakeClient` and add failing tests** in `tests/test_telegram_reader.py`.

First, replace the `FakeClient` class with this version (adds `__call__` for dialog filters and `get_entity`; existing kwargs unchanged):

```python
class FakeClient:
    """Mimics the subset of Telethon's async API that TelegramReader uses."""

    def __init__(self, *, messages=None, dialogs=None, filters=None, entities=None):
        self._messages = messages or []
        self._dialogs = dialogs or []
        self._filters = filters or []
        self._entities = entities or {}

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

    async def __call__(self, request):
        # Stands in for messages.GetDialogFiltersRequest().
        return SimpleNamespace(filters=self._filters)

    async def get_entity(self, peer):
        return self._entities[peer]
```

Then append these helpers and tests:

```python
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
    # Recent Telethon layers wrap the title in a TextWithEntities-like object.
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
```

- [ ] **Step 2: Run them, verify FAIL**

Run: `uv run pytest tests/test_telegram_reader.py -k "folder" -v`
Expected: FAIL with `AttributeError: 'TelegramReader' object has no attribute 'list_folders'`.

- [ ] **Step 3: Implement folders** in `yougram/telegram_reader.py`.

Add this import near the top (below `import difflib`):

```python
from telethon.tl.functions.messages import GetDialogFiltersRequest
```

Add `Folder` to the models import line so it reads:

```python
from .models import Dialog, Folder, Message
```

Add these methods to the `TelegramReader` class (e.g. after `list_dialogs`):

```python
    async def list_folders(self) -> list[Folder]:
        filters = await self._fetch_filters()
        out: list[Folder] = []
        for f in filters:
            title = self._filter_title(f)
            if title is None:
                continue  # default/preset filter without a real title
            out.append(Folder(id=getattr(f, "id", 0), title=title))
        return out

    async def chats_in_folder(self, name: str, limit: int = 50) -> list[Dialog]:
        filters = await self._fetch_filters()
        match = self._best_folder(name, filters)
        if match is None:
            return []
        out: list[Dialog] = []
        for peer in list(getattr(match, "include_peers", []))[:limit]:
            entity = await self._client.get_entity(peer)
            out.append(self._entity_to_dialog(entity))
        return out

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
```

- [ ] **Step 4: Run the reader suite, verify PASS**

Run: `uv run pytest tests/test_telegram_reader.py -v`
Expected: ALL pass (existing + 4 new folder tests).

- [ ] **Step 5: Commit**

```bash
git add yougram/telegram_reader.py tests/test_telegram_reader.py
git commit -m "feat: read chat folders (list_folders, chats_in_folder)"
```

---

## Task 4: `resolve_chat` + numeric chat references

`resolve_chat` turns a forwarded chat id into a `Dialog` (and primes Telethon's
entity cache). `_entity_ref` lets the agent pass a numeric id as a string.

**Files:**
- Modify: `yougram/telegram_reader.py`
- Test: `tests/test_telegram_reader.py`

- [ ] **Step 1: Add failing tests** — append to `tests/test_telegram_reader.py`:

```python
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
```

- [ ] **Step 2: Run them, verify FAIL**

Run: `uv run pytest tests/test_telegram_reader.py -k "entity_ref or resolve_chat" -v`
Expected: FAIL with `AttributeError` (`_entity_ref` / `resolve_chat` missing).

- [ ] **Step 3: Implement** in `yougram/telegram_reader.py`.

Add `resolve_chat` (e.g. after `chats_in_folder`):

```python
    async def resolve_chat(self, ref) -> Dialog:
        """Resolve a chat reference (id, @username, or title) to a Dialog.

        Also primes Telethon's entity cache so later fetches by id succeed.
        """
        entity = await self._client.get_entity(ref)
        return self._entity_to_dialog(entity)
```

Add the `_entity_ref` static helper (next to the other staticmethods):

```python
    @staticmethod
    def _entity_ref(chat):
        """A numeric-string chat (e.g. '555' from forward context) -> int id."""
        if isinstance(chat, str) and chat.lstrip("-").isdigit():
            return int(chat)
        return chat
```

Now route `fetch_messages` and `search_messages` through it. Change the
`iter_messages` calls:

In `fetch_messages`, change:
```python
        async for m in self._client.iter_messages(chat, limit=limit):
```
to:
```python
        async for m in self._client.iter_messages(self._entity_ref(chat), limit=limit):
```

In `search_messages`, change:
```python
            async for m in self._client.iter_messages(chat, search=query, limit=limit):
```
to:
```python
            async for m in self._client.iter_messages(self._entity_ref(chat), search=query, limit=limit):
```

- [ ] **Step 4: Run the reader suite, verify PASS**

Run: `uv run pytest tests/test_telegram_reader.py -v`
Expected: ALL pass (existing message tests still pass — `_entity_ref("chan")` returns `"chan"` unchanged).

- [ ] **Step 5: Commit**

```bash
git add yougram/telegram_reader.py tests/test_telegram_reader.py
git commit -m "feat: resolve_chat + numeric chat references"
```

---

## Task 5: Folder tools for the agent

**Files:**
- Modify: `yougram/tools.py`
- Test: `tests/test_tools.py`

- [ ] **Step 1: Add failing tests** — append to `tests/test_tools.py`.

First extend `FakeReader` (in that file) with two methods — add inside the class:

```python
    async def list_folders(self):
        self.calls.append(("folders",))
        return [Folder(id=1, title="AI")]

    async def chats_in_folder(self, name, limit=50):
        self.calls.append(("chats_in_folder", name, limit))
        return [Dialog(id=9, name="AI News", kind="channel")]
```

Add the new tools to the existing import and write tests:

```python
async def test_list_folders_tool_delegates():
    reader = FakeReader()
    from yougram.tools import list_folders

    out = await list_folders(_ctx(reader))
    assert out[0].title == "AI"
    assert reader.calls == [("folders",)]


async def test_chats_in_folder_tool_delegates():
    reader = FakeReader()
    from yougram.tools import chats_in_folder

    out = await chats_in_folder(_ctx(reader), name="ai")
    assert out[0].name == "AI News"
    assert reader.calls == [("chats_in_folder", "ai", 50)]
```

(`Folder` is needed in the test imports — change the existing
`from yougram.models import Dialog, Message` line to
`from yougram.models import Dialog, Folder, Message`.)

- [ ] **Step 2: Run them, verify FAIL**

Run: `uv run pytest tests/test_tools.py -k "folder" -v`
Expected: FAIL with `ImportError: cannot import name 'list_folders'`.

- [ ] **Step 3: Implement** — append to `yougram/tools.py`:

```python
async def list_folders(ctx: RunContext[Deps]) -> list:
    """List the user's Telegram chat folders by name.

    Call this when the user refers to a "folder" so you can then read the chats
    inside the one they mean.
    """
    return await ctx.deps.reader.list_folders()


async def chats_in_folder(ctx: RunContext[Deps], name: str) -> list:
    """List the channels/chats inside the folder whose name best matches `name`.

    Then read each with `fetch_messages` (e.g. to summarize a folder "today").
    """
    return await ctx.deps.reader.chats_in_folder(name)
```

- [ ] **Step 4: Run the tools suite, verify PASS**

Run: `uv run pytest tests/test_tools.py -v`
Expected: ALL pass (3 existing + 2 new).

- [ ] **Step 5: Commit**

```bash
git add yougram/tools.py tests/test_tools.py
git commit -m "feat: list_folders + chats_in_folder agent tools"
```

---

## Task 6: Forward source parser

**Files:**
- Create: `yougram/forwards.py`
- Test: `tests/test_forwards.py`

- [ ] **Step 1: Write the failing test** — `tests/test_forwards.py`:

```python
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
```

- [ ] **Step 2: Run it, verify FAIL**

Run: `uv run pytest tests/test_forwards.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'yougram.forwards'`.

- [ ] **Step 3: Implement `yougram/forwards.py`**:

```python
from dataclasses import dataclass


@dataclass
class ForwardSource:
    """Where a forwarded message came from.

    `resolvable` is True when Telegram exposed the origin chat (we have a
    `chat_id` to read). It is False when the origin is hidden by the sender's
    privacy settings — then only `name` may be available.
    """

    resolvable: bool
    chat_id: int | None = None
    name: str | None = None


def extract_forward_source(message) -> ForwardSource | None:
    """Parse Telethon forward metadata; return None if it isn't a forward."""
    fwd = getattr(message, "fwd_from", None)
    if fwd is None:
        return None

    from_id = getattr(fwd, "from_id", None)
    if from_id is None:
        # Origin hidden by privacy; only a display name may be present.
        return ForwardSource(resolvable=False, name=getattr(fwd, "from_name", None))

    chat_id = (
        getattr(from_id, "channel_id", None)
        or getattr(from_id, "user_id", None)
        or getattr(from_id, "chat_id", None)
    )
    return ForwardSource(resolvable=True, chat_id=chat_id)
```

- [ ] **Step 4: Run it, verify PASS**

Run: `uv run pytest tests/test_forwards.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add yougram/forwards.py tests/test_forwards.py
git commit -m "feat: parse forwarded-message source"
```

---

## Task 7: Conversation context store

**Files:**
- Create: `yougram/context.py`
- Test: `tests/test_context.py`

- [ ] **Step 1: Write the failing test** — `tests/test_context.py`:

```python
from yougram.context import ConversationContext
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
```

- [ ] **Step 2: Run it, verify FAIL**

Run: `uv run pytest tests/test_context.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'yougram.context'`.

- [ ] **Step 3: Implement `yougram/context.py`**:

```python
from .models import Dialog


class ConversationContext:
    """In-memory per-user 'current chat' memory.

    Set when the user forwards a message; read to scope follow-up questions.
    Not persisted — resets when the process restarts (by design).
    """

    def __init__(self) -> None:
        self._chats: dict[int, Dialog] = {}

    def set_chat(self, user_id: int, chat: Dialog) -> None:
        self._chats[user_id] = chat

    def get_chat(self, user_id: int) -> Dialog | None:
        return self._chats.get(user_id)

    def clear(self, user_id: int) -> None:
        self._chats.pop(user_id, None)
```

- [ ] **Step 4: Run it, verify PASS**

Run: `uv run pytest tests/test_context.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add yougram/context.py tests/test_context.py
git commit -m "feat: in-memory conversation context store"
```

---

## Task 8: Bot — forward handling + context injection

`handle_question` gains a `context` parameter (placed before `allowed_user_id`).
Forwards set the current chat; normal messages inject it into the agent question.

**Files:**
- Modify: `yougram/bot.py`
- Test: `tests/test_bot.py` (rewritten)

- [ ] **Step 1: Rewrite `tests/test_bot.py`** to the new signature + behaviors:

```python
from types import SimpleNamespace
from unittest.mock import AsyncMock

import yougram.bot as bot_module
from yougram.bot import handle_question
from yougram.context import ConversationContext
from yougram.models import Dialog


class FakeEvent:
    def __init__(self, sender_id, text, message=None):
        self.sender_id = sender_id
        self.raw_text = text
        self.message = message  # None => not a forward
        self.reply = AsyncMock()


class FakeReader:
    def __init__(self, chat=None):
        self._chat = chat

    async def resolve_chat(self, ref):
        return self._chat


def _forward_message(channel_id):
    fwd = SimpleNamespace(from_id=SimpleNamespace(channel_id=channel_id), from_name=None)
    return SimpleNamespace(fwd_from=fwd)


async def test_ignores_non_whitelisted_user(monkeypatch):
    spy = AsyncMock(return_value="nope")
    monkeypatch.setattr(bot_module, "ask", spy)
    event = FakeEvent(sender_id=999, text="hi")

    await handle_question(event, agent=object(), reader=FakeReader(),
                          context=ConversationContext(), allowed_user_id=777)

    spy.assert_not_awaited()
    event.reply.assert_not_awaited()


async def test_answers_whitelisted_user(monkeypatch):
    spy = AsyncMock(return_value="here is your answer")
    monkeypatch.setattr(bot_module, "ask", spy)
    event = FakeEvent(sender_id=777, text="what did X say?")

    await handle_question(event, agent=object(), reader=FakeReader(),
                          context=ConversationContext(), allowed_user_id=777)

    spy.assert_awaited_once()
    event.reply.assert_awaited_once_with("here is your answer")


async def test_replies_with_error_when_ask_fails(monkeypatch):
    spy = AsyncMock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr(bot_module, "ask", spy)
    event = FakeEvent(sender_id=777, text="anything")

    await handle_question(event, agent=object(), reader=FakeReader(),
                          context=ConversationContext(), allowed_user_id=777)

    event.reply.assert_awaited_once()
    (sent,), _ = event.reply.call_args
    assert "boom" in sent


async def test_forward_sets_context_and_acknowledges(monkeypatch):
    spy = AsyncMock(return_value="should not run")
    monkeypatch.setattr(bot_module, "ask", spy)
    context = ConversationContext()
    reader = FakeReader(chat=Dialog(id=555, name="Crypto", kind="channel"))
    event = FakeEvent(sender_id=777, text="", message=_forward_message(555))

    await handle_question(event, agent=object(), reader=reader,
                          context=context, allowed_user_id=777)

    spy.assert_not_awaited()  # a forward is not a question
    assert context.get_chat(777).name == "Crypto"
    (sent,), _ = event.reply.call_args
    assert "Crypto" in sent


async def test_question_injects_current_chat_context(monkeypatch):
    spy = AsyncMock(return_value="ok")
    monkeypatch.setattr(bot_module, "ask", spy)
    context = ConversationContext()
    context.set_chat(777, Dialog(id=5, name="Crypto", kind="channel"))
    event = FakeEvent(sender_id=777, text="what's new over 3 days?")

    await handle_question(event, agent=object(), reader=FakeReader(),
                          context=context, allowed_user_id=777)

    spy.assert_awaited_once()
    (_, _, question), _ = spy.call_args  # ask(agent, reader, question)
    assert "Crypto" in question
    assert "id=5" in question
    assert "what's new over 3 days?" in question
```

- [ ] **Step 2: Run it, verify FAIL**

Run: `uv run pytest tests/test_bot.py -v`
Expected: FAIL — `handle_question()` got an unexpected keyword argument `context` (old signature).

- [ ] **Step 3: Rewrite `yougram/bot.py`**:

```python
from telethon import events

from .agent import ask
from .forwards import extract_forward_source


async def handle_question(event, agent, reader, context, allowed_user_id: int) -> None:
    """Owner-only handler. A forward sets the current chat; any other message is
    answered, with the current chat (if any) injected as context."""
    if event.sender_id != allowed_user_id:
        return

    source = extract_forward_source(event.message)
    if source is not None:
        await _handle_forward(event, reader, context, allowed_user_id, source)
        return

    question = event.raw_text
    current = context.get_chat(allowed_user_id)
    if current is not None:
        question = (
            f"[Current chat context: '{current.name}' (id={current.id}). "
            f"Apply the question to this chat unless another is named.]\n{question}"
        )

    try:
        answer = await ask(agent, reader, question)
    except Exception as exc:  # noqa: BLE001 — surface any failure to the owner
        await event.reply(f"⚠️ Error: {exc}")
        return
    await event.reply(answer)


async def _handle_forward(event, reader, context, allowed_user_id, source) -> None:
    if not source.resolvable:
        await event.reply(
            "Походження форварду приховане приватністю 🔒 "
            "Назви канал приблизно — я пошукаю."
        )
        return
    try:
        chat = await reader.resolve_chat(source.chat_id)
    except Exception as exc:  # noqa: BLE001
        await event.reply(f"⚠️ Не вдалося відкрити канал: {exc}")
        return
    context.set_chat(allowed_user_id, chat)
    await event.reply(f"Контекст: {chat.name}. Тепер питай про нього 🙂")


def register_bot(bot_client, agent, reader, context, allowed_user_id: int) -> None:
    """Wire `handle_question` to the bot-client's incoming-message events."""

    @bot_client.on(events.NewMessage(incoming=True))
    async def _handler(event):
        await handle_question(event, agent, reader, context, allowed_user_id)
```

- [ ] **Step 4: Run it, verify PASS**

Run: `uv run pytest tests/test_bot.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add yougram/bot.py tests/test_bot.py
git commit -m "feat: forward sets chat context; questions inject it"
```

---

## Task 9: Wire new tools + prompt + entrypoint

Register the folder tools, teach the prompt about the new selectors, and pass a
`ConversationContext` through `__main__`.

**Files:**
- Modify: `yougram/agent.py`
- Modify: `yougram/__main__.py`
- Test: `tests/test_agent.py`

- [ ] **Step 1: Update `tests/test_agent.py`** so `TestModel` (which calls every
registered tool) finds the new reader methods. Replace the `FakeReader` class with:

```python
class FakeReader:
    def __init__(self):
        self.called = []

    async def fetch_messages(self, chat, since=None, limit=100):
        self.called.append("fetch_messages")
        return [Message(id=1, date=datetime(2026, 6, 2, tzinfo=timezone.utc), sender="x", text="hi")]

    async def search_messages(self, query, chats, since=None, limit=50):
        self.called.append("search_messages")
        return []

    async def list_dialogs(self, query, limit=20):
        self.called.append("list_dialogs")
        return []

    async def list_folders(self):
        self.called.append("list_folders")
        return []

    async def chats_in_folder(self, name, limit=50):
        self.called.append("chats_in_folder")
        return []
```

- [ ] **Step 2: Run the agent test, verify FAIL**

Run: `uv run pytest tests/test_agent.py -v`
Expected: FAIL — `TestModel` calls the not-yet-registered `list_folders`/`chats_in_folder`, or (after registration is missing) `FakeReader` mismatch. Specifically the run errors because the agent has no such tools yet OR the reader lacks them; this drives Step 3.

- [ ] **Step 3: Register the tools and update the prompt** in `yougram/agent.py`.

Update the tools import line:
```python
from .tools import Deps, chats_in_folder, fetch_messages, list_dialogs, list_folders, search_messages
```

Add the two tools to the `Agent(...)` `tools=[...]` list so it reads:
```python
        tools=[
            Tool(list_dialogs, takes_ctx=True),
            Tool(list_folders, takes_ctx=True),
            Tool(chats_in_folder, takes_ctx=True),
            Tool(fetch_messages, takes_ctx=True),
            Tool(search_messages, takes_ctx=True),
        ],
```

Replace the first two guideline bullets of `SYSTEM_PROMPT` (the `list_dialogs`
bullet) with these three bullets:
```python
- To answer questions about a named channel/group/person, call `list_dialogs`
  (it is fuzzy/typo-tolerant) to resolve the name into concrete chats.
- For a "folder", call `list_folders` to see folder names, then
  `chats_in_folder(name)` to get its chats, and read each with `fetch_messages`
  (e.g. to summarize a folder "today").
- A message may begin with a "[Current chat context: ...]" line set by an
  earlier forward — treat that chat as the target unless the user names another.
```

- [ ] **Step 4: Run the agent test, verify PASS**

Run: `uv run pytest tests/test_agent.py -v`
Expected: PASS (all agent tests).

- [ ] **Step 5: Wire `__main__.py`.** Update `yougram/__main__.py`:

Add the import (with the other local imports):
```python
from .context import ConversationContext
```

Change the wiring block from:
```python
    reader = TelegramReader(user_client, tz=ZoneInfo(s.timezone))
    agent = build_agent(s.llm_model, s.timezone)
    register_bot(bot_client, agent, reader, s.allowed_user_id)
```
to:
```python
    reader = TelegramReader(user_client, tz=ZoneInfo(s.timezone))
    agent = build_agent(s.llm_model, s.timezone)
    context = ConversationContext()
    register_bot(bot_client, agent, reader, context, s.allowed_user_id)
```

- [ ] **Step 6: Smoke-check imports + full suite**

Run:
```bash
uv run python -m py_compile yougram/__main__.py
uv run pytest -q
```
Expected: compile ok; ALL tests pass.

- [ ] **Step 7: Commit**

```bash
git add yougram/agent.py yougram/__main__.py tests/test_agent.py
git commit -m "feat: wire folder tools, prompt, and conversation context"
```

---

## Self-Review notes (already applied)

- **Spec coverage:** folders (T1/T3/T5), fuzzy name (T2), forward parse (T6), context memory (T7), bot forward handling + injection (T8), prompt + wiring (T9), error handling for hidden origin / unknown folder / no access (T8 `_handle_forward`, T3 empty result). All covered.
- **Type consistency:** `Folder(id, title)` consistent T1/T3/T5; `Dialog(id, name, kind)` reused for folder chats and resolved chats; `ForwardSource(resolvable, chat_id, name)` consistent T6/T8; `handle_question(event, agent, reader, context, allowed_user_id)` and `register_bot(..., context, allowed_user_id)` consistent T8/T9; reader methods `list_folders()`, `chats_in_folder(name)`, `resolve_chat(ref)` consistent across tasks.
- **No placeholders:** every code step contains complete code.

## Notes for the implementer

- `_match_score` returns a flat 2.0 for substring hits so the stable sort keeps
  their original order — this is why the pre-existing `list_dialogs` test still
  passes. Don't make substring scores vary.
- `_entity_kind` is duck-typed (attribute checks, not `isinstance`) so it works
  for both real Telethon entities and `SimpleNamespace` test fakes. Keep it so.
- A forwarded message is never treated as a question, even if it has a caption —
  it only sets context. The user asks in the next message.
- Reading a forwarded *public* channel the account hasn't joined may still fail
  inside Telethon (no access hash); the `_handle_forward` try/except reports it.
