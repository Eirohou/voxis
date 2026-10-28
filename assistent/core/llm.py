"""LLM client interface supporting Groq with native tool/function calling."""

import json
from typing import Any, Dict, List, Optional
import httpx
from pydantic import BaseModel

from assistent.config import get_config
from assistent.core.persona import SYSTEM_PROMPT


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: Dict[str, Any]


class LLMResponse(BaseModel):
    content: Optional[str] = None
    tool_calls: List[ToolCall] = []


class GroqLLMClient:
    """Client for Groq Chat Completions API with function calling."""

    API_URL = "https://api.groq.com/openai/v1/chat/completions"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        fallback_model: Optional[str] = None,
        temperature: float = 0.2,
    ):
        config = get_config()
        self.api_key = api_key or config.llm.api_key
        self.model = model or config.llm.model
        self.fallback_model = fallback_model or config.llm.fallback_model
        self.temperature = temperature

    async def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> LLMResponse:
        """Sends messages to Groq and parses tool calls or text response."""
        if not self.api_key:
            return LLMResponse(
                content="Error: GROQ_API_KEY is not set. Please set it in .env or config.yaml."
            )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # Build payload
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
        }

        if tools and len(tools) > 0:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.post(self.API_URL, headers=headers, json=payload)
                if response.status_code == 404 or response.status_code == 400:
                    # Retry with fallback model if primary fails
                    if self.fallback_model and self.model != self.fallback_model:
                        payload["model"] = self.fallback_model
                        response = await client.post(self.API_URL, headers=headers, json=payload)

                response.raise_for_status()
                data = response.json()
            except httpx.HTTPStatusError as e:
                return LLMResponse(content=f"Groq API error ({e.response.status_code}): {e.response.text}")
            except Exception as e:
                return LLMResponse(content=f"Connection error to Groq API: {str(e)}")

        choice = data.get("choices", [{}])[0]
        message = choice.get("message", {})
        content = message.get("content")

        tool_calls: List[ToolCall] = []
        raw_tool_calls = message.get("tool_calls", [])
        for raw in raw_tool_calls:
            func = raw.get("function", {})
            try:
                args = json.loads(func.get("arguments", "{}"))
            except Exception:
                args = {}
            tool_calls.append(
                ToolCall(
                    id=raw.get("id", ""),
                    name=func.get("name", ""),
                    arguments=args,
                )
            )

        return LLMResponse(content=content, tool_calls=tool_calls)
