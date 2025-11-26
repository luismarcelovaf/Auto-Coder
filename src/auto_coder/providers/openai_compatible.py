"""OpenAI-compatible API provider."""

import json
from typing import Any, AsyncIterator

import httpx

from .base import LLMProvider, Message, StreamChunk, ToolCall, ToolDefinition


class OpenAICompatibleProvider(LLMProvider):
    """Provider for OpenAI-compatible APIs (OpenAI, Ollama, vLLM, etc.)."""

    def __init__(
        self,
        base_url: str = "https://api.openai.com/v1",
        model: str = "gpt-4",
        api_key: str | None = None,
        auth_headers: dict[str, str] | None = None,
        extra_params: dict[str, Any] | None = None,
        timeout: float = 120.0,
    ):
        # Build auth headers from api_key if provided
        headers = auth_headers or {}
        if api_key and "Authorization" not in headers:
            headers["Authorization"] = f"Bearer {api_key}"

        super().__init__(base_url, model, headers, extra_params)
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout),
                headers={
                    "Content-Type": "application/json",
                    **self.auth_headers,
                },
            )
        return self._client

    def _message_to_dict(self, msg: Message) -> dict[str, Any]:
        """Convert a Message to OpenAI API format."""
        result: dict[str, Any] = {"role": msg.role}

        if msg.content is not None:
            result["content"] = msg.content

        if msg.tool_calls:
            result["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments),
                    },
                }
                for tc in msg.tool_calls
            ]

        if msg.tool_call_id:
            result["tool_call_id"] = msg.tool_call_id

        if msg.name:
            result["name"] = msg.name

        return result

    def _parse_tool_calls(self, tool_calls_data: list[dict]) -> list[ToolCall]:
        """Parse tool calls from API response."""
        result = []
        for tc in tool_calls_data:
            try:
                arguments = json.loads(tc["function"]["arguments"])
            except json.JSONDecodeError:
                arguments = {}

            result.append(
                ToolCall(
                    id=tc["id"],
                    name=tc["function"]["name"],
                    arguments=arguments,
                )
            )
        return result

    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        stream: bool = False,
    ) -> Message | AsyncIterator[StreamChunk]:
        """Send a chat completion request."""
        client = await self._get_client()

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [self._message_to_dict(m) for m in messages],
            "stream": stream,
            **self.extra_params,
        }

        if tools:
            payload["tools"] = [t.to_openai_format() for t in tools]
            payload["tool_choice"] = "auto"

        if stream:
            return self._stream_response(client, payload)
        else:
            return await self._complete_response(client, payload)

    async def _complete_response(
        self, client: httpx.AsyncClient, payload: dict
    ) -> Message:
        """Get a complete (non-streaming) response."""
        response = await client.post(
            f"{self.base_url}/chat/completions",
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

        choice = data["choices"][0]
        message_data = choice["message"]

        tool_calls = None
        if "tool_calls" in message_data and message_data["tool_calls"]:
            tool_calls = self._parse_tool_calls(message_data["tool_calls"])

        return Message(
            role="assistant",
            content=message_data.get("content"),
            tool_calls=tool_calls,
        )

    async def _stream_response(
        self, client: httpx.AsyncClient, payload: dict
    ) -> AsyncIterator[StreamChunk]:
        """Stream the response."""
        # Track partial tool calls being built up
        tool_call_buffers: dict[int, dict] = {}

        async with client.stream(
            "POST",
            f"{self.base_url}/chat/completions",
            json=payload,
        ) as response:
            response.raise_for_status()

            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue

                data_str = line[6:]  # Remove "data: " prefix
                if data_str == "[DONE]":
                    break

                try:
                    data = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                if not data.get("choices"):
                    continue

                choice = data["choices"][0]
                delta = choice.get("delta", {})
                finish_reason = choice.get("finish_reason")

                content = delta.get("content")

                # Handle streaming tool calls
                tool_calls = None
                if "tool_calls" in delta:
                    for tc_delta in delta["tool_calls"]:
                        idx = tc_delta["index"]
                        if idx not in tool_call_buffers:
                            tool_call_buffers[idx] = {
                                "id": tc_delta.get("id", ""),
                                "name": "",
                                "arguments": "",
                            }

                        if "id" in tc_delta:
                            tool_call_buffers[idx]["id"] = tc_delta["id"]
                        if "function" in tc_delta:
                            if "name" in tc_delta["function"]:
                                tool_call_buffers[idx]["name"] = tc_delta["function"]["name"]
                            if "arguments" in tc_delta["function"]:
                                tool_call_buffers[idx]["arguments"] += tc_delta["function"]["arguments"]

                # When we get a finish_reason, emit any completed tool calls
                if finish_reason and tool_call_buffers:
                    parsed_calls = []
                    for tc_buf in tool_call_buffers.values():
                        try:
                            arguments = json.loads(tc_buf["arguments"])
                        except json.JSONDecodeError:
                            arguments = {}
                        parsed_calls.append(
                            ToolCall(
                                id=tc_buf["id"],
                                name=tc_buf["name"],
                                arguments=arguments,
                            )
                        )
                    tool_calls = parsed_calls

                yield StreamChunk(
                    content=content,
                    tool_calls=tool_calls,
                    finish_reason=finish_reason,
                )

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
