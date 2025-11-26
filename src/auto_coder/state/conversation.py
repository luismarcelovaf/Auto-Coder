"""Conversation state management."""

import os
from typing import Any

from ..providers.base import Message, ToolCall, ToolResult


DEFAULT_SYSTEM_PROMPT = """You are an AI coding assistant. You help users with software development tasks including:
- Reading and understanding code
- Writing and editing files
- Running shell commands
- Debugging and fixing issues
- Explaining code and concepts

You have access to tools for file operations and shell commands. Use them when needed to help the user.

Guidelines:
- Be concise and direct in your responses
- When editing files, show what changes you're making
- Explain your reasoning when making decisions
- Ask clarifying questions if the user's request is ambiguous
- Be careful with destructive operations (deleting files, force pushing, etc.)

Current working directory: {cwd}
"""


class ConversationManager:
    """Manages conversation history and state."""

    def __init__(
        self,
        system_prompt: str | None = None,
        working_dir: str | None = None,
    ):
        self.working_dir = working_dir or os.getcwd()
        self.system_prompt = (system_prompt or DEFAULT_SYSTEM_PROMPT).format(
            cwd=self.working_dir
        )
        self._messages: list[Message] = []
        self._initialize()

    def _initialize(self) -> None:
        """Initialize the conversation with a system message."""
        self._messages = [
            Message(role="system", content=self.system_prompt)
        ]

    def add_user_message(self, content: str) -> None:
        """Add a user message to the conversation."""
        self._messages.append(Message(role="user", content=content))

    def add_assistant_message(
        self,
        content: str | None = None,
        tool_calls: list[ToolCall] | None = None,
    ) -> None:
        """Add an assistant message to the conversation."""
        self._messages.append(
            Message(role="assistant", content=content, tool_calls=tool_calls)
        )

    def add_tool_result(self, result: ToolResult) -> None:
        """Add a tool result message to the conversation."""
        self._messages.append(
            Message(
                role="tool",
                content=result.content,
                tool_call_id=result.tool_call_id,
                name=result.name,
            )
        )

    def get_messages(self) -> list[Message]:
        """Get all messages in the conversation."""
        return self._messages.copy()

    def clear(self) -> None:
        """Clear the conversation and start fresh."""
        self._initialize()

    def get_last_assistant_message(self) -> Message | None:
        """Get the most recent assistant message."""
        for msg in reversed(self._messages):
            if msg.role == "assistant":
                return msg
        return None

    def message_count(self) -> int:
        """Get the number of messages (excluding system)."""
        return len(self._messages) - 1  # Exclude system message

    def to_dict(self) -> dict[str, Any]:
        """Serialize conversation to a dictionary."""
        return {
            "system_prompt": self.system_prompt,
            "working_dir": self.working_dir,
            "messages": [
                {
                    "role": msg.role,
                    "content": msg.content,
                    "tool_calls": (
                        [
                            {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                            for tc in msg.tool_calls
                        ]
                        if msg.tool_calls
                        else None
                    ),
                    "tool_call_id": msg.tool_call_id,
                    "name": msg.name,
                }
                for msg in self._messages
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ConversationManager":
        """Deserialize conversation from a dictionary."""
        manager = cls(
            system_prompt=data["system_prompt"],
            working_dir=data["working_dir"],
        )
        manager._messages = []

        for msg_data in data["messages"]:
            tool_calls = None
            if msg_data.get("tool_calls"):
                tool_calls = [
                    ToolCall(
                        id=tc["id"],
                        name=tc["name"],
                        arguments=tc["arguments"],
                    )
                    for tc in msg_data["tool_calls"]
                ]

            manager._messages.append(
                Message(
                    role=msg_data["role"],
                    content=msg_data.get("content"),
                    tool_calls=tool_calls,
                    tool_call_id=msg_data.get("tool_call_id"),
                    name=msg_data.get("name"),
                )
            )

        return manager
