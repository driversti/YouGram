# Context Memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the bot remember the conversation between turns so follow-ups like "про що його останній пост?" resolve, without ballooning token cost.

**Architecture:** Two in-memory, per-user layers on top of the existing `ConversationContext`: (1) an *active chat* the read tools set whenever they resolve exactly one chat, injected into the next prompt; (2) a *2-turn history window* passed as `message_history`, with each turn collapsed to a single user→assistant text pair so heavy tool-result dumps are never stored. The agent's `system_prompt` becomes `instructions` because Pydantic AI drops system prompts (but re-applies instructions) when `message_history` is supplied — without this the dynamic "current time" prompt silently dies on every follow-up.

**Tech Stack:** Python 3.14, Pydantic AI 1.105, Telethon (mocked in tests), pytest + pytest-asyncio (`asyncio_mode=auto`), uv.

---

## Background the engineer must know

- Run all tests with `uv run pytest`. A single test: `uv run pytest tests/test_x.py::test_name -v`.
- `ConversationContext` (`yougram/context.py`) is a per-user dict. Today it only holds a "current chat" `Dialog`. We extend it with conversation history. It must NOT import anything heavy — only `yougram.models`.
- `Deps` (`yougram/tools.py`) is the dataclass injected into every tool call. Tools read `ctx.deps.reader`.
- `ask()` (`yougram/agent.py`) runs one question through the agent. `bot.py`'s `handle_question` calls it.
- **Pydantic AI fact (verified):** when you pass `message_history=...`, the framework does NOT re-emit the agent's `system_prompt` parts, but it DOES re-apply `instructions`. So our prompt and the dynamic time-context must be `instructions`, and stored history must be a valid alternating user→assistant sequence.
- **Message classes** live in `pydantic_ai.messages`: `ModelRequest(parts=[...])` (user side), `ModelResponse(parts=[...])` (model side), `UserPromptPart`, `TextPart`. A finished run's `result.new_messages()` returns the messages added by that run.

---

## Task 1: Conversation history in ConversationContext

**Files:**
- Modify: `yougram/context.py`
- Test: `tests/test_context.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_context.py`:

```python
def test_history_append_and_get():
    ctx = ConversationContext()
    assert ctx.get_history(1) == []

    ctx.append_turn(1, ["q1", "a1"])
    assert ctx.get_history(1) == ["q1", "a1"]

    ctx.append_turn(1, ["q2", "a2"])
    assert ctx.get_history(1) == ["q1", "a1", "q2", "a2"]


def test_history_keeps_only_last_two_turns():
    ctx = ConversationContext()
    ctx.append_turn(1, ["q1", "a1"])
    ctx.append_turn(1, ["q2", "a2"])
    ctx.append_turn(1, ["q3", "a3"])  # third turn evicts the first
    assert ctx.get_history(1) == ["q2", "a2", "q3", "a3"]


def test_history_is_per_user():
    ctx = ConversationContext()
    ctx.append_turn(1, ["a"])
    ctx.append_turn(2, ["b"])
    assert ctx.get_history(1) == ["a"]
    assert ctx.get_history(2) == ["b"]


def test_clear_wipes_history_too():
    ctx = ConversationContext()
    ctx.append_turn(1, ["q", "a"])
    ctx.set_chat(1, Dialog(id=5, name="C", kind="channel"))
    ctx.clear(1)
    assert ctx.get_history(1) == []
    assert ctx.get_chat(1) is None


def test_empty_turn_is_ignored():
    ctx = ConversationContext()
    ctx.append_turn(1, [])  # trimming produced nothing — don't store an empty turn
    assert ctx.get_history(1) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_context.py -v`
Expected: FAIL — `ConversationContext` has no `append_turn`/`get_history`.

- [ ] **Step 3: Implement**

Replace the body of `yougram/context.py` with:

```python
from .models import Dialog

# How many recent turns to keep per user. A "turn" is one user question plus
# the assistant's answer (collapsed to a user→assistant message pair before it
# is stored, so no tool-result dumps are kept).
HISTORY_TURNS = 2


class ConversationContext:
    """In-memory per-user memory: a 'current chat' and a short message history.

    Set the current chat when the user forwards a message or a read tool resolves
    exactly one chat; read it to scope follow-up questions. History is the last
    `HISTORY_TURNS` turns, passed to the model as `message_history`.
    Not persisted — resets when the process restarts (by design).
    """

    def __init__(self) -> None:
        self._chats: dict[int, Dialog] = {}
        self._history: dict[int, list[list]] = {}

    def set_chat(self, user_id: int, chat: Dialog) -> None:
        self._chats[user_id] = chat

    def get_chat(self, user_id: int) -> Dialog | None:
        return self._chats.get(user_id)

    def append_turn(self, user_id: int, messages: list) -> None:
        """Store one turn's (already trimmed) messages, keeping the last N turns."""
        if not messages:
            return  # nothing survived trimming — don't store an empty turn
        turns = self._history.setdefault(user_id, [])
        turns.append(messages)
        del turns[:-HISTORY_TURNS]  # keep only the last HISTORY_TURNS turns

    def get_history(self, user_id: int) -> list:
        """Flatten the stored turns into one message list for `message_history`."""
        return [msg for turn in self._history.get(user_id, []) for msg in turn]

    def clear(self, user_id: int) -> None:
        self._chats.pop(user_id, None)
        self._history.pop(user_id, None)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_context.py -v`
Expected: PASS (new tests + the existing `test_set_get_clear`, `test_clear_unknown_user_is_noop`).

- [ ] **Step 5: Commit**

```bash
git add yougram/context.py tests/test_context.py
git commit -m "feat: per-user conversation history in ConversationContext"
```

---

## Task 2: Convert the agent's system prompt to instructions

**Why:** Pydantic AI drops `system_prompt` parts when `message_history` is supplied but re-applies `instructions`. The dynamic time-context (the "2026 is not the future" fix) and the resolve-first rules must be `instructions` so they survive follow-up turns.

**Files:**
- Modify: `yougram/agent.py:61-84` (the `build_agent` function)
- Test: `tests/test_agent.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_agent.py`:

```python
from pydantic_ai.messages import ModelRequest, ModelResponse, UserPromptPart, TextPart


def test_instructions_survive_message_history():
    # Regression: with message_history, system prompts are dropped but
    # instructions are re-applied. The current-year context must reach the model
    # on follow-up turns, or "today" breaks again.
    agent = build_agent("anthropic:claude-haiku-4-5", tz="Europe/Warsaw")
    year = str(datetime.now(timezone.utc).year)
    with agent.override(model=TestModel()):
        r1 = agent.run_sync("first", deps=Deps(reader=FakeReader()))
        history = [
            ModelRequest(parts=[UserPromptPart(content="first")]),
            ModelResponse(parts=[TextPart(content="ok")]),
        ]
        r2 = agent.run_sync("second", deps=Deps(reader=FakeReader()),
                            message_history=history)

    # The latest request to the model still carries the time-context instructions.
    last_request = [m for m in r2.all_messages() if isinstance(m, ModelRequest)][-1]
    assert last_request.instructions is not None
    assert year in last_request.instructions
```

Add the import at the top of the test file (it already imports from `yougram.agent`):

```python
from yougram.tools import Deps
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_agent.py::test_instructions_survive_message_history -v`
Expected: FAIL — with `system_prompt`, `last_request.instructions` is `None`.

- [ ] **Step 3: Implement**

In `yougram/agent.py`, change `build_agent` to use `instructions` instead of `system_prompt`. Replace lines 61-84 with:

```python
def build_agent(model: str, tz: str = "UTC") -> Agent[Deps, str]:
    """Construct the provider-agnostic agent. `model` is any Pydantic AI model
    string (e.g. 'anthropic:claude-haiku-4-5', 'openai:gpt-4o-mini'). `tz` is the
    user's IANA timezone, used to resolve relative dates like "today"."""
    agent = Agent(
        model,
        deps_type=Deps,
        # `instructions`, not `system_prompt`: Pydantic AI omits system prompts
        # when message_history is supplied (follow-up turns) but always re-applies
        # instructions, so the rules below and the dynamic time-context survive.
        instructions=SYSTEM_PROMPT,
        tools=[
            Tool(list_dialogs, takes_ctx=True),
            Tool(list_folders, takes_ctx=True),
            Tool(chats_in_folder, takes_ctx=True),
            Tool(fetch_messages, takes_ctx=True),
            Tool(search_messages, takes_ctx=True),
        ],
        defer_model_check=True,
    )

    # Dynamic instruction: re-evaluated on every run so 'now' is always current.
    @agent.instructions
    def _time_context() -> str:
        return current_time_context(tz)

    return agent
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_agent.py -v`
Expected: PASS — the new regression test plus the existing agent tests.

- [ ] **Step 5: Commit**

```bash
git add yougram/agent.py tests/test_agent.py
git commit -m "fix: use instructions so prompt survives message_history"
```

---

## Task 3: Add the message-trimming helper

**Why:** Storing raw `new_messages()` would keep the giant tool-result dumps (the token cost we want to avoid). We collapse one run into a single user→assistant text pair — drops tool calls/returns AND guarantees a valid alternating sequence with no adjacent same-role messages.

**Files:**
- Modify: `yougram/agent.py` (add helper + imports)
- Test: `tests/test_agent.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_agent.py` (imports from Task 2 already added):

```python
from pydantic_ai.messages import ToolCallPart, ToolReturnPart, SystemPromptPart


def test_trim_messages_keeps_only_user_and_text():
    messages = [
        ModelRequest(parts=[SystemPromptPart(content="sys"),
                            UserPromptPart(content="hello")]),
        ModelResponse(parts=[ToolCallPart(tool_name="fetch_messages", args={})]),
        ModelRequest(parts=[ToolReturnPart(tool_name="fetch_messages",
                                           content="HUGE DUMP")]),
        ModelResponse(parts=[TextPart(content="here is the answer")]),
    ]
    trimmed = trim_messages(messages)

    # Exactly one user request followed by one model response, nothing else.
    assert len(trimmed) == 2
    assert isinstance(trimmed[0], ModelRequest)
    assert [p.content for p in trimmed[0].parts] == ["hello"]
    assert isinstance(trimmed[1], ModelResponse)
    assert [p.content for p in trimmed[1].parts] == ["here is the answer"]
    # No tool-call/return parts and no system prompt survive.
    kinds = [type(p).__name__ for m in trimmed for p in m.parts]
    assert kinds == ["UserPromptPart", "TextPart"]


def test_trim_messages_collapses_multiple_text_parts():
    # A run with narration + final answer collapses to ONE response (no adjacent
    # same-role messages, which some providers reject).
    messages = [
        ModelRequest(parts=[UserPromptPart(content="q")]),
        ModelResponse(parts=[TextPart(content="let me look")]),
        ModelResponse(parts=[TextPart(content="done")]),
    ]
    trimmed = trim_messages(messages)
    assert len(trimmed) == 2
    assert [p.content for p in trimmed[1].parts] == ["let me look", "done"]


def test_trim_messages_empty_when_no_user_or_text():
    trimmed = trim_messages([
        ModelResponse(parts=[ToolCallPart(tool_name="x", args={})]),
    ])
    assert trimmed == []
```

Update the import line in `test_agent.py` to pull in `trim_messages`:

```python
from yougram.agent import ask, build_agent, current_time_context, trim_messages
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_agent.py -k trim_messages -v`
Expected: FAIL — `trim_messages` is not defined.

- [ ] **Step 3: Implement**

In `yougram/agent.py`, add the import near the top (after the existing `from pydantic_ai import ...` line):

```python
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)
```

Then add this function (place it above `ask`):

```python
def trim_messages(messages: list[ModelMessage]) -> list[ModelMessage]:
    """Collapse one run's messages into a single user→assistant text pair.

    Drops tool calls/returns and system prompts (the token-heavy parts we don't
    want in stored history) and merges all text into one response, so the result
    is a valid alternating sequence with no adjacent same-role messages.
    """
    user_parts = []
    text_parts = []
    for m in messages:
        if isinstance(m, ModelRequest):
            user_parts += [p for p in m.parts if isinstance(p, UserPromptPart)]
        elif isinstance(m, ModelResponse):
            text_parts += [p for p in m.parts if isinstance(p, TextPart)]
    out: list[ModelMessage] = []
    if user_parts:
        out.append(ModelRequest(parts=user_parts))
    if text_parts:
        out.append(ModelResponse(parts=text_parts))
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_agent.py -k trim_messages -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add yougram/agent.py tests/test_agent.py
git commit -m "feat: trim_messages collapses a run to a user/assistant pair"
```

---

## Task 4: Deps carries context; read tools set the active chat

**Files:**
- Modify: `yougram/tools.py`
- Test: `tests/test_tools.py`

- [ ] **Step 1: Write the failing tests**

In `tests/test_tools.py`, first extend the `FakeReader` with a `resolve_chat` method (add inside the class, after `chats_in_folder`):

```python
    async def resolve_chat(self, ref):
        self.calls.append(("resolve_chat", ref))
        return Dialog(id=42, name=f"resolved:{ref}", kind="channel")
```

Replace the `_ctx` helper so a context + user_id can be supplied:

```python
from yougram.context import ConversationContext


def _ctx(reader, context=None, user_id=None):
    class Ctx:
        deps = Deps(reader=reader, context=context, user_id=user_id)

    return Ctx()
```

Then add these tests:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tools.py -v`
Expected: FAIL — `Deps` has no `context`/`user_id`; tools don't set the active chat.

- [ ] **Step 3: Implement**

In `yougram/tools.py`, update the imports and `Deps`, and have the read tools remember the chat. Replace lines 1-14 (imports + `Deps`) with:

```python
from dataclasses import dataclass
from datetime import datetime

from pydantic_ai import RunContext

from .context import ConversationContext
from .models import Dialog, Folder, Message
from .telegram_reader import ChatNotResolved, TelegramReader


@dataclass
class Deps:
    """Dependencies injected into every tool call for one agent run.

    `context` + `user_id` let the read tools record the active chat (the single
    chat they just resolved) so follow-up questions like "his last post" work.
    Both are optional so `ask`/tests can run without conversation memory.
    """

    reader: TelegramReader
    context: ConversationContext | None = None
    user_id: int | None = None
```

Add this helper after `Deps` (before `list_dialogs`):

```python
async def _remember_chat(ctx: RunContext[Deps], chat: str) -> None:
    """Record `chat` as the active chat, if memory is available and it resolves.

    Telethon already cached the entity during the read, so this resolve is cheap.
    Any failure is ignored — remembering the chat is best-effort.
    """
    deps = ctx.deps
    if deps.context is None or deps.user_id is None:
        return
    try:
        dialog = await deps.reader.resolve_chat(chat)
    except Exception:  # noqa: BLE001 — best-effort; never break the read on this
        return
    deps.context.set_chat(deps.user_id, dialog)
```

Replace the body of `fetch_messages` (the `try/except` block, lines 39-45) with:

```python
    try:
        messages = await ctx.deps.reader.fetch_messages(chat, since=since, limit=limit)
    except ChatNotResolved:
        return (
            f"Could not find a chat matching '{chat}'. Resolve it first with "
            f"list_dialogs/chats_in_folder, or ask the user to name a folder or channel."
        )
    await _remember_chat(ctx, chat)  # single chat resolved -> make it the active chat
    return messages
```

Replace the body of `search_messages` (line 59) with:

```python
    results = await ctx.deps.reader.search_messages(query, chats, since=since, limit=limit)
    if len(chats) == 1:  # only an unambiguous single-chat search sets context
        await _remember_chat(ctx, chats[0])
    return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tools.py -v`
Expected: PASS — new tests + the existing delegation tests (which call `_ctx(reader)` with no context, exercising the `None` guard).

- [ ] **Step 5: Commit**

```bash
git add yougram/tools.py tests/test_tools.py
git commit -m "feat: read tools record the active chat on single-chat resolve"
```

---

## Task 5: ask() wires history in and stores the trimmed turn

**Files:**
- Modify: `yougram/agent.py:87-91` (the `ask` function)
- Test: `tests/test_agent.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_agent.py`:

```python
from yougram.context import ConversationContext


async def test_ask_stores_trimmed_history_without_tool_dumps():
    agent = build_agent("anthropic:claude-haiku-4-5")
    reader = FakeReader()
    context = ConversationContext()
    with agent.override(model=TestModel()):
        await ask(agent, reader, "what did X say?", context=context, user_id=7)

    history = context.get_history(7)
    # One turn stored: a user request and a model response, nothing else.
    assert len(history) == 2
    assert isinstance(history[0], ModelRequest)
    assert isinstance(history[1], ModelResponse)
    kinds = [type(p).__name__ for m in history for p in m.parts]
    # No ToolReturnPart (the heavy dump) and no SystemPromptPart survive.
    assert "ToolReturnPart" not in kinds
    assert "SystemPromptPart" not in kinds


async def test_ask_caps_history_at_two_turns():
    agent = build_agent("anthropic:claude-haiku-4-5")
    reader = FakeReader()
    context = ConversationContext()
    with agent.override(model=TestModel()):
        for i in range(3):
            await ask(agent, reader, f"q{i}", context=context, user_id=7)
    # 2 turns * 2 messages each.
    assert len(context.get_history(7)) == 4


async def test_ask_without_context_is_backward_compatible():
    agent = build_agent("anthropic:claude-haiku-4-5")
    reader = FakeReader()
    with agent.override(model=TestModel()):
        answer = await ask(agent, reader, "hi")  # no context/user_id
    assert isinstance(answer, str)
    assert answer != ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_agent.py -k "ask_stores or ask_caps or backward" -v`
Expected: FAIL — `ask` doesn't accept `context`/`user_id` and stores nothing.

- [ ] **Step 3: Implement**

Replace `ask` (lines 87-91) in `yougram/agent.py` with:

```python
async def ask(
    agent: Agent[Deps, str],
    reader: TelegramReader,
    question: str,
    *,
    context: "ConversationContext | None" = None,
    user_id: int | None = None,
) -> str:
    """Run one question through the agent and return its text answer.

    When `context` and `user_id` are given, the last turns are replayed as
    `message_history` and this turn is stored back (trimmed) so follow-ups keep
    context. Without them, `ask` is stateless (used by tests and one-off calls).
    """
    history = None
    if context is not None and user_id is not None:
        history = context.get_history(user_id) or None

    deps = Deps(reader=reader, context=context, user_id=user_id)
    result = await agent.run(question, deps=deps, message_history=history)

    if context is not None and user_id is not None:
        context.append_turn(user_id, trim_messages(result.new_messages()))

    return result.output
```

Add the import for the type hint at the top of `yougram/agent.py` (with the other local imports):

```python
from .context import ConversationContext
```

(The `"ConversationContext | None"` string hint already works; importing it also lets `Deps` construction type-check and avoids confusion. `context.py` imports only `models`, so there is no import cycle.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_agent.py -v`
Expected: PASS — all agent tests, including the existing `test_ask_runs_agent_and_routes_through_tools_without_real_llm`.

- [ ] **Step 5: Commit**

```bash
git add yougram/agent.py tests/test_agent.py
git commit -m "feat: ask replays and stores trimmed conversation history"
```

---

## Task 6: Bot passes context + user_id into ask

**Files:**
- Modify: `yougram/bot.py:26-31`
- Test: `tests/test_bot.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_bot.py`:

```python
async def test_ask_receives_context_and_user_id(monkeypatch):
    spy = AsyncMock(return_value="ok")
    monkeypatch.setattr(bot_module, "ask", spy)
    context = ConversationContext()
    event = FakeEvent(sender_id=777, text="hello")

    await handle_question(event, agent=object(), reader=FakeReader(),
                          context=context, allowed_user_id=777)

    spy.assert_awaited_once()
    _, kwargs = spy.call_args
    assert kwargs["context"] is context
    assert kwargs["user_id"] == 777
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_bot.py::test_ask_receives_context_and_user_id -v`
Expected: FAIL — `ask` is called with no `context`/`user_id` kwargs.

- [ ] **Step 3: Implement**

In `yougram/bot.py`, change the `ask` call (lines 26-29). Replace:

```python
    try:
        answer = await ask(agent, reader, question)
    except Exception as exc:  # noqa: BLE001 — surface any failure to the owner
        await event.reply(f"⚠️ Error: {exc}")
        return
```

with:

```python
    try:
        answer = await ask(agent, reader, question,
                           context=context, user_id=allowed_user_id)
    except Exception as exc:  # noqa: BLE001 — surface any failure to the owner
        await event.reply(f"⚠️ Error: {exc}")
        return
```

- [ ] **Step 4: Run the full suite**

Run: `uv run pytest -v`
Expected: PASS — including the existing `test_question_injects_current_chat_context` (it unpacks the first three positional args, which are unchanged) and `test_answers_whitelisted_user`.

- [ ] **Step 5: Commit**

```bash
git add yougram/bot.py tests/test_bot.py
git commit -m "feat: bot threads conversation context into ask"
```

---

## Task 7: Verify end-to-end wiring

**Files:**
- Read-only check: `yougram/__main__.py`

- [ ] **Step 1: Confirm `__main__` already wires context**

Run: `uv run python -c "import yougram.__main__"` (must import cleanly) and read `yougram/__main__.py` to confirm it constructs `ConversationContext()` and passes it to `register_bot(...)`. No code change is expected — `register_bot` → `handle_question` already receives `context`, and Task 6 made `handle_question` forward it to `ask`. If `__main__` does NOT create/pass a context, add it mirroring the existing `register_bot(bot, agent, reader, context, s.allowed_user_id)` call.

- [ ] **Step 2: Run the whole suite once more**

Run: `uv run pytest`
Expected: PASS (all tests).

- [ ] **Step 3: Manual smoke test (user-run, optional)**

Restart the bot and reproduce the original failure:
1. "підсумуй непрочитані повідомлення на каналі Винсент Ван Блог" → summary.
2. "про що його останній пост?" → should now answer about that channel instead of asking who "він" is.

- [ ] **Step 4: Commit any wiring fix (only if Step 1 required a change)**

```bash
git add yougram/__main__.py
git commit -m "chore: ensure ConversationContext is wired in __main__"
```

---

## Self-review notes

- **Spec coverage:** active-chat-on-single-resolve → Task 4; no active chat for folder/multi-chat → Task 4 (`len(chats)==1` guard; folder tool untouched); 2-turn history → Task 1; strip tool dumps → Task 3 + Task 5; `Deps` gains context/user_id → Task 4; `ask` history + backward compat → Task 5; bot threads context → Task 6; in-memory only → no persistence added; forward still overrides → unchanged `_handle_forward`. The spec's "ask returns new messages so the caller stores them" is implemented as **ask stores internally** (returns `str`) — this satisfies the same requirement while keeping `ask` backward-compatible (a tuple return would break existing callers/tests). The hidden requirement that the prompt survive `message_history` is handled by Task 2 (`instructions`).
- **Type consistency:** `append_turn(user_id, messages)`, `get_history(user_id)`, `trim_messages(messages)`, `Deps(reader, context, user_id)`, `ask(..., *, context, user_id)`, `_remember_chat(ctx, chat)` — names used consistently across tasks.
- **No placeholders:** every step has concrete code and exact commands.
