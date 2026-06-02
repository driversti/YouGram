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
- Message dates are UTC. When the user says "today" or "this week", translate to
  a `since` datetime.
- Answer concisely. Quote or summarize the actual messages; never invent content.
- If a tool returns nothing, say so plainly rather than guessing.
"""


def build_agent(model: str) -> Agent[Deps, str]:
    """Construct the provider-agnostic agent. `model` is any Pydantic AI model
    string (e.g. 'anthropic:claude-haiku-4-5', 'openai:gpt-4o-mini')."""
    return Agent(
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


async def ask(agent: Agent[Deps, str], reader: TelegramReader, question: str) -> str:
    """Run one question through the agent and return its text answer."""
    result = await agent.run(question, deps=Deps(reader=reader))
    return result.output
