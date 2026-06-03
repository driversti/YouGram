from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from pydantic_ai import Agent, Tool
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)

from .context import ConversationContext
from .telegram_reader import TelegramReader
from .tools import Deps, chats_in_folder, fetch_messages, list_dialogs, list_folders, search_messages

SYSTEM_PROMPT = """\
You are YouGram, a personal assistant that answers questions about the user's
own Telegram account. You have read-only tools to find chats and read messages.

Guidelines:
- To answer questions about a named channel/group/person, call `list_dialogs`
  (fuzzy/typo-tolerant; it matches both display names and @usernames) FIRST to
  resolve the name into a concrete chat, then pass the returned id/@username to
  the read tools. NEVER pass a raw descriptive name (e.g. "my girlfriend") straight
  to `fetch_messages`/`search_messages` — it will fail to resolve.
- EXCEPTION: an explicit `@username` or a numeric chat id can be passed DIRECTLY to
  the read tools — Telegram resolves these globally, even for chats not in your
  recent dialogs. So if `list_dialogs` returns nothing for an `@username` the user
  gave, try passing that `@username` straight to the read tool before giving up.
- If asked which chat discussed something but there is no current chat context
  and no chat/folder is named, ASK the user to name a folder or channel — do not
  guess.
- For a "folder", call `list_folders` to see folder names, then
  `chats_in_folder(name)` to get its chats, and read each with `fetch_messages`
  (e.g. to summarize a folder "today").
- A message may begin with a "[Current chat context: 'Name' (id=N)]" line set by
  an earlier forward — treat that chat as the target unless the user names
  another, and pass that numeric id=N as the `chat` argument to the read tools.
- Use `fetch_messages` for "what was said in chat X" and `search_messages` for
  "did anyone mention Y across these chats".
- Telegram message dates are UTC. When the user says "today", "yesterday" or
  "this week", compute the matching `since` as a TIMEZONE-AWARE datetime (include
  the UTC offset) at the start of that period in the user's timezone given below,
  and pass it to the tools — do NOT fetch the whole backlog and summarize it as
  if it were "today".
- Answer concisely. Quote or summarize ONLY the actual messages the tools
  returned; never invent content. When you reference a specific post, include its
  `link` field so the user can open it.
- If a tool returns nothing for the requested period, say so plainly.
"""


def current_time_context(tz_name: str = "UTC") -> str:
    """A system-prompt fragment telling the model what 'now' is, in `tz_name`.

    Without this the model assumes its training cutoff is the present, treats
    real (recent) message dates as 'the future', and cannot resolve 'today'.
    `tz_name` is an IANA name (e.g. "Europe/Warsaw") so "today" is the user's
    calendar day, not the host's (which is UTC in Docker).
    """
    now_local = datetime.now(ZoneInfo(tz_name))
    now_utc = now_local.astimezone(timezone.utc)
    return (
        f"Current date and time: {now_local:%Y-%m-%d %H:%M %Z%z} "
        f"(UTC: {now_utc:%Y-%m-%d %H:%M}). "
        f"This is the present moment — the year {now_local:%Y} is NOT the future, "
        f"and recent messages are current, not an archive. "
        f"The user's timezone is {tz_name}; resolve 'today' as the start of the "
        f"current day in that timezone, as a timezone-aware `since`."
    )


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
    if not user_parts:
        return []  # never store a response without its user turn — that's an
        # invalid history (providers require it to start with a user message)
    out: list[ModelMessage] = [ModelRequest(parts=user_parts)]
    if text_parts:
        out.append(ModelResponse(parts=text_parts))
    return out


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
