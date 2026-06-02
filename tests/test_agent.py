from datetime import datetime, timezone

from pydantic_ai.models.test import TestModel

from yougram.agent import ask, build_agent, current_time_context
from yougram.models import Message


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


async def test_ask_runs_agent_and_routes_through_tools_without_real_llm():
    agent = build_agent("anthropic:claude-haiku-4-5")
    reader = FakeReader()
    # TestModel drives the agent without a real provider and calls every
    # registered tool, so a non-empty answer + recorded tool calls confirm wiring.
    with agent.override(model=TestModel()):
        answer = await ask(agent, reader, "what did channel X say today?")

    assert isinstance(answer, str)
    assert answer != ""
    assert reader.called  # at least one tool was actually routed to the reader


def test_current_time_context_states_the_present_year():
    now = datetime.now().astimezone()
    ctx = current_time_context()
    # The model must be told the real current year (so it stops calling it "the future").
    assert str(now.year) in ctx
    assert "UTC" in ctx
    assert "today" in ctx.lower()
