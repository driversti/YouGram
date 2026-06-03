from datetime import datetime, timezone

from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart, ToolCallPart, ToolReturnPart, SystemPromptPart
from pydantic_ai.models.test import TestModel

from yougram.agent import ask, build_agent, current_time_context, trim_messages
from yougram.context import ConversationContext
from yougram.models import Message
from yougram.tools import Deps


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
    now = datetime.now(timezone.utc)
    ctx = current_time_context()
    # The model must be told the real current year (so it stops calling it "the future").
    assert str(now.year) in ctx
    assert "UTC" in ctx
    assert "today" in ctx.lower()


def test_current_time_context_uses_given_timezone():
    ctx = current_time_context("Europe/Warsaw")
    assert "Europe/Warsaw" in ctx


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


def test_trim_messages_drops_response_without_a_user_turn():
    # A response with no preceding user prompt would be an invalid history
    # (providers require it to start with a user message) — store nothing.
    trimmed = trim_messages([
        ModelResponse(parts=[TextPart(content="orphan answer")]),
    ])
    assert trimmed == []


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
