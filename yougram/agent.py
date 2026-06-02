from datetime import datetime, timezone

from pydantic_ai import Agent, Tool

from .telegram_reader import TelegramReader
from .tools import Deps, fetch_messages, list_dialogs, search_messages

SYSTEM_PROMPT = """\
You are YouGram, a personal assistant that answers questions about the user's
own Telegram account. You have read-only tools to find chats and read messages.

Guidelines:
- To answer questions about a named channel/group/person, first call
  `list_dialogs` to resolve the name into concrete chats.
- Use `fetch_messages` for "what was said in chat X" and `search_messages` for
  "did anyone mention Y across these chats".
- Telegram message dates are UTC. When the user says "today", "yesterday" or
  "this week", compute the matching `since` datetime from the current time given
  below and pass it to the tools — do NOT fetch the whole backlog and summarize
  it as if it were "today".
- Answer concisely. Quote or summarize ONLY the actual messages the tools
  returned; never invent content. If unsure, say what you actually saw.
- If a tool returns nothing for the requested period, say so plainly.
"""


def current_time_context() -> str:
    """A system-prompt fragment telling the model what 'now' is.

    Without this the model assumes its training cutoff is the present, treats
    real (recent) message dates as 'the future', and cannot resolve 'today'.
    """
    now_local = datetime.now().astimezone()
    now_utc = now_local.astimezone(timezone.utc)
    return (
        f"Current date and time: {now_local:%Y-%m-%d %H:%M %Z} "
        f"(UTC: {now_utc:%Y-%m-%d %H:%M}). "
        f"This is the present moment — the year {now_utc:%Y} is NOT the future, "
        f"and recent messages are current, not an archive. "
        f"For 'today', use the start of the current local day as `since`."
    )


def build_agent(model: str) -> Agent[Deps, str]:
    """Construct the provider-agnostic agent. `model` is any Pydantic AI model
    string (e.g. 'anthropic:claude-haiku-4-5', 'openai:gpt-4o-mini')."""
    agent = Agent(
        model,
        deps_type=Deps,
        system_prompt=SYSTEM_PROMPT,
        tools=[
            Tool(list_dialogs, takes_ctx=True),
            Tool(fetch_messages, takes_ctx=True),
            Tool(search_messages, takes_ctx=True),
        ],
        defer_model_check=True,
    )

    # Dynamic prompt: re-evaluated on every run so 'now' is always current.
    @agent.system_prompt
    def _time_context() -> str:
        return current_time_context()

    return agent


async def ask(agent: Agent[Deps, str], reader: TelegramReader, question: str) -> str:
    """Run one question through the agent and return its text answer."""
    result = await agent.run(question, deps=Deps(reader=reader))
    return result.output
