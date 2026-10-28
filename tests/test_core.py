"""Tests for Agent loop and tool dispatching."""

import pytest
import pytest_asyncio
from assistent.core.agent import Agent
from assistent.core.llm import LLMResponse, ToolCall
from assistent.skills.base import ToolRegistry


class MockLLMClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def chat(self, messages, tools=None):
        self.calls.append({"messages": messages, "tools": tools})
        if self.responses:
            return self.responses.pop(0)
        return LLMResponse(content="Done.")


@pytest.mark.asyncio
async def test_agent_tool_dispatch():
    registry = ToolRegistry()

    @registry.register(name="add_numbers")
    def add_numbers(a: int, b: int) -> int:
        """Adds two numbers."""
        return a + b

    # Mock response 1: LLM decides to call tool 'add_numbers'
    # Mock response 2: LLM replies with the final calculated answer
    mock_responses = [
        LLMResponse(
            content=None,
            tool_calls=[
                ToolCall(id="call_1", name="add_numbers", arguments={"a": 5, "b": 7})
            ],
        ),
        LLMResponse(content="The result is 12.", tool_calls=[]),
    ]

    llm = MockLLMClient(mock_responses)
    agent = Agent(registry=registry, llm_client=llm)

    executed_tools = []

    def on_tool(name, args):
        executed_tools.append((name, args))

    result = await agent.run("What is 5 + 7?", on_tool_call=on_tool)

    assert result.text == "The result is 12."
    assert "add_numbers" in result.tools_executed
    assert executed_tools == [("add_numbers", {"a": 5, "b": 7})]
    assert len(agent.history) == 5  # system, user, assistant(tool_call), tool, assistant(final)
