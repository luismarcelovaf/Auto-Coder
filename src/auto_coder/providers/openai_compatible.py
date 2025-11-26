"""OpenAI-compatible API provider."""

import json
import uuid
from typing import Any, AsyncIterator

import httpx

from .base import LLMProvider, Message, StreamChunk, ToolCall, ToolDefinition
from ..auth import get_certifi_path, is_sso_enabled, get_sso_token, get_sso_headers


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
        correlation_id: str | None = None,
    ):
        # Build auth headers from api_key if provided
        headers = auth_headers or {}
        if api_key and "Authorization" not in headers:
            headers["Authorization"] = f"Bearer {api_key}"

        super().__init__(base_url, model, headers, extra_params)
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None
        self._correlation_id = correlation_id or self._generate_correlation_id()
        self._sso_token: str | None = None

    @staticmethod
    def _generate_correlation_id() -> str:
        """Generate a new correlation ID."""
        return str(uuid.uuid4())

    def get_correlation_id(self) -> str:
        """Get the current correlation ID."""
        return self._correlation_id

    def reset_correlation_id(self) -> str:
        """Reset the correlation ID (e.g., after /clear or /reset).

        Returns:
            The new correlation ID
        """
        self._correlation_id = self._generate_correlation_id()
        return self._correlation_id

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            # Build headers including correlation ID
            headers = {
                "Content-Type": "application/json",
                **self.auth_headers,
            }

            # Handle SSO authentication
            if is_sso_enabled():
                self._sso_token = await get_sso_token()
                if self._sso_token:
                    sso_headers = get_sso_headers(self._sso_token)
                    headers.update(sso_headers)

            # Use certifi for SSL certificate verification
            cert_path = get_certifi_path()

            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout),
                headers=headers,
                verify=cert_path,
            )
        return self._client

    def _get_request_headers(self) -> dict[str, str]:
        """Get headers for a specific request, including correlation ID."""
        return {
            "x-correlation-id": self._correlation_id,
        }

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
        stream: bool = True,  # Default to True - always use streaming
    ) -> AsyncIterator[StreamChunk]:
        """Send a chat completion request.

        Note: This method always uses streaming for consistent behavior.
        The stream parameter is kept for interface compatibility but is ignored.
        """
        client = await self._get_client()

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [self._message_to_dict(m) for m in messages],
            "stream": True,  # Always stream
            **self.extra_params,
        }

        if tools:
            payload["tools"] = [t.to_openai_format() for t in tools]
            payload["tool_choice"] = "auto"

        # Always use streaming
        return self._stream_response(client, payload)

    async def _stream_response(
        self, client: httpx.AsyncClient, payload: dict
    ) -> AsyncIterator[StreamChunk]:
        """Stream the response."""
        # Track partial tool calls being built up
        tool_call_buffers: dict[int, dict] = {}

        # Include correlation ID in request headers
        request_headers = self._get_request_headers()

        async with client.stream(
            "POST",
            f"{self.base_url}/chat/completions",
            json=payload,
            headers=request_headers,
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
