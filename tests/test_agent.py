from datetime import datetime, timezone

from pydantic_ai.models.test import TestModel

from yougram.agent import ask, build_agent
from yougram.models import Message


class FakeReader:
    async def fetch_messages(self, chat, since=None, limit=100):
        return [Message(id=1, date=datetime(2026, 6, 2, tzinfo=timezone.utc), sender="x", text="hi")]

    async def search_messages(self, query, chats, since=None, limit=50):
        return []

    async def list_dialogs(self, query, limit=20):
        return []


async def test_ask_runs_agent_and_calls_tools_without_real_llm():
    agent = build_agent("anthropic:claude-haiku-4-5")
    # TestModel drives the agent without a real provider; it exercises every tool.
    with agent.override(model=TestModel()):
        answer = await ask(agent, FakeReader(), "what did channel X say today?")

    assert isinstance(answer, str)
    assert answer != ""
