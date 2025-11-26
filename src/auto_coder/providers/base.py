"""Base classes for LLM providers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, Literal


@dataclass
class Message:
    """A message in the conversation."""

    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    tool_calls: list["ToolCall"] | None = None
    tool_call_id: str | None = None  # For tool result messages
    name: str | None = None  # Tool name for tool results


@dataclass
class ToolCall:
    """A tool call requested by the LLM."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ToolResult:
    """Result from executing a tool."""

    tool_call_id: str
    name: str
    content: str
    is_error: bool = False


@dataclass
class StreamChunk:
    """A chunk from a streaming response."""

    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    finish_reason: str | None = None


@dataclass
class ToolDefinition:
    """Definition of a tool that can be called by the LLM."""

    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[..., Any] = field(repr=False)

    def to_openai_format(self) -> dict[str, Any]:
        """Convert to OpenAI function calling format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            }
        }


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    def __init__(
        self,
        base_url: str,
        model: str,
        auth_headers: dict[str, str] | None = None,
        extra_params: dict[str, Any] | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.auth_headers = auth_headers or {}
        self.extra_params = extra_params or {}

    @abstractmethod
    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition] | None = None,
        stream: bool = False,
    ) -> Message | AsyncIterator[StreamChunk]:
        """Send a chat request to the LLM.

        Args:
            messages: The conversation history
            tools: Available tools for the LLM to use
            stream: Whether to stream the response

        Returns:
            Either a complete Message or an async iterator of StreamChunks
        """
        pass

    @abstractmethod
    async def close(self) -> None:
        """Clean up any resources."""
        pass
