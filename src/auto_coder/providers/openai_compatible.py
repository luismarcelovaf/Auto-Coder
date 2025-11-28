"""OpenAI-compatible API provider."""

import json
import os
import uuid
from typing import Any, AsyncIterator

import httpx

from .base import LLMProvider, Message, StreamChunk, ToolCall, ToolDefinition
from ..auth import get_certifi_path, update_certifi, get_authentication

# Set AUTO_CODER_DEBUG=1 to enable debug logging
DEBUG = os.environ.get("AUTO_CODER_DEBUG", "").lower() in ("1", "true", "yes")


class OpenAICompatibleProvider(LLMProvider):
    """Provider for OpenAI-compatible APIs (OpenAI, Ollama, vLLM, etc.)."""

    def __init__(
        self,
        base_url: str = "https://<URL>/genai/dev/v1",
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
        self._httpx_auth: httpx.Auth | None = None

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
            # Update certificates before creating client
            update_certifi()

            # Build headers including correlation ID
            headers = {
                "Content-Type": "application/json",
                **self.auth_headers,
            }

            # Get authentication based on configuration:
            # 1. USE_SSO=true -> Bearer token from AuthenticationProvider
            # 2. SERVER_SIDE_TOKEN_REFRESH=true -> Basic credentials from AuthenticationProvider
            # 3. Otherwise -> httpx.Auth from AuthenticationProviderWithClientSideTokenRefresh
            auth_headers, self._httpx_auth = get_authentication()
            headers.update(auth_headers)

            # Use certifi for SSL certificate verification
            cert_path = get_certifi_path()

            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout),
                headers=headers,
                verify=cert_path,
                auth=self._httpx_auth,
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

        # Handle tool result messages specially
        if msg.role == "tool":
            # Tool messages MUST have tool_call_id and content
            result["tool_call_id"] = msg.tool_call_id
            # Content must always be present for tool messages (use empty string if None)
            result["content"] = msg.content if msg.content is not None else ""
            return result

        # For non-tool messages
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

        formatted_messages = [self._message_to_dict(m) for m in messages]

        # Build tools description to embed in system message
        tools_description = ""
        if tools:
            tools_description = "\n\n## TOOL DEFINITIONS (use these exact names and parameters):\n\n"
            for t in tools:
                tools_description += f"### {t.name}\n"
                tools_description += f"{t.description}\n"
                tools_description += f"Parameters: {json.dumps(t.parameters, indent=2)}\n\n"

        # Inject tools into the system message so it comes AFTER our "IGNORE PREVIOUS" instruction
        if formatted_messages and formatted_messages[0].get("role") == "system" and tools_description:
            formatted_messages[0]["content"] = formatted_messages[0].get("content", "") + tools_description

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": formatted_messages,
            "stream": True,  # Always stream
            **self.extra_params,
        }

        # Still include tools in API format for proper function calling
        if tools:
            payload["tools"] = [t.to_openai_format() for t in tools]
            payload["tool_choice"] = "auto"

        # Debug: print the payload being sent
        if DEBUG:
            print("\n=== DEBUG: API Request ===")
            print(f"URL: {self.base_url}/chat/completions")
            print(f"Model: {self.model}")
            if payload.get("tools"):
                print(f"Tools ({len(payload['tools'])}):")
                for t in payload["tools"]:
                    print(f"  - {t['function']['name']}: {t['function']['description'][:80]}...")
            print(f"Messages ({len(formatted_messages)}):")
            for i, msg in enumerate(formatted_messages):
                print(f"  [{i}] role={msg.get('role')}, tool_call_id={msg.get('tool_call_id')}")
                if msg.get('content'):
                    content_preview = msg['content'][:200] + "..." if len(msg.get('content', '')) > 200 else msg.get('content')
                    print(f"       content: {content_preview}")
                if msg.get('tool_calls'):
                    print(f"       tool_calls: {msg['tool_calls']}")
            print("=== END DEBUG ===\n")

        # Always use streaming
        return self._stream_response(client, payload)

    def _debug_response(self, content: str | None, tool_calls: list[ToolCall] | None, finish_reason: str | None, reasoning: str | None = None) -> None:
        """Print debug info for response chunks."""
        if not DEBUG:
            return
        parts = []
        if reasoning:
            print(f"  [REASONING] {reasoning}")
        if content:
            preview = content[:50].replace('\n', '\\n')
            parts.append(f"content=\"{preview}{'...' if len(content) > 50 else ''}\"")
        if tool_calls:
            parts.append(f"tools={[tc.name for tc in tool_calls]}")
        if finish_reason:
            parts.append(f"finish={finish_reason}")
        if parts:
            print(f"  [RECV] {', '.join(parts)}")

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
                reasoning_content = delta.get("reasoning_content")

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

                self._debug_response(content, tool_calls, finish_reason, reasoning_content)

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
