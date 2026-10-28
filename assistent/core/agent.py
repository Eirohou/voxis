"""Agent orchestrator managing conversation history, tool execution, and responses."""

import json
from typing import Any, Callable, Dict, List, Optional
from pydantic import BaseModel

from assistent.core.llm import GroqLLMClient, LLMResponse
from assistent.core.persona import SYSTEM_PROMPT
from assistent.skills.base import ToolRegistry, default_registry


class AgentResult(BaseModel):
    text: str
    silent_feedback: bool = False
    tools_executed: List[str] = []


class Agent:
    """Agent orchestrator for the voice assistant."""

    def __init__(
        self,
        registry: Optional[ToolRegistry] = None,
        llm_client: Optional[GroqLLMClient] = None,
        max_history: int = 10,
    ):
        self.registry = registry or default_registry
        self.llm = llm_client or GroqLLMClient()
        self.max_history = max_history
        self.history: List[Dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]

    def reset_conversation(self):
        """Clears conversation history except system prompt."""
        self.history = [{"role": "system", "content": SYSTEM_PROMPT}]

    async def run(
        self,
        user_input: str,
        on_tool_call: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ) -> AgentResult:
        """Processes user input through LLM, dispatches tools, and returns final answer."""
        self.history.append({"role": "user", "content": user_input})

        tools_executed: List[str] = []
        silent_feedback = False

        # Run multi-turn tool calling loop (up to 5 iterations)
        for _ in range(5):
            schemas = self.registry.get_schemas()
            response: LLMResponse = await self.llm.chat(
                messages=self.history,
                tools=schemas if schemas else None,
            )

            # Check if LLM requested tool execution
            if response.tool_calls:
                # Add assistant message with tool calls to history
                assistant_msg: Dict[str, Any] = {
                    "role": "assistant",
                    "content": response.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments),
                            },
                        }
                        for tc in response.tool_calls
                    ],
                }
                self.history.append(assistant_msg)

                # Execute each tool
                for tc in response.tool_calls:
                    tools_executed.append(tc.name)
                    tool_obj = self.registry.get_tool(tc.name)
                    if tool_obj and tool_obj.silent_feedback:
                        silent_feedback = True

                    if on_tool_call:
                        on_tool_call(tc.name, tc.arguments)

                    result = self.registry.execute(tc.name, **tc.arguments)
                    str_result = json.dumps(result) if not isinstance(result, str) else result

                    self.history.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "name": tc.name,
                            "content": str_result,
                        }
                    )
            else:
                # Final response reached
                content = response.content or ""
                self.history.append({"role": "assistant", "content": content})

                # Trim history if exceeding limit
                if len(self.history) > (self.max_history * 2 + 1):
                    # Keep system prompt at index 0, trim older user/assistant pairs
                    self.history = [self.history[0]] + self.history[-(self.max_history * 2):]

                return AgentResult(
                    text=content.strip(),
                    silent_feedback=silent_feedback,
                    tools_executed=tools_executed,
                )

        # Fallback if loop exceeded
        return AgentResult(
            text="Completed.",
            silent_feedback=silent_feedback,
            tools_executed=tools_executed,
        )
