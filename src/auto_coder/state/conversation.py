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

## IMPORTANT: Tool Usage Rules

You have access to the following tools and MUST use them to complete tasks:
- **read_file**: Read file contents - USE THIS before editing any file
- **write_file**: Create or overwrite files - USE THIS to create new files
- **edit_file**: Edit files by replacing text - USE THIS to modify existing files
- **list_directory**: List immediate directory contents - USE THIS to see files in a folder
- **tree_directory**: Show directory tree structure - USE THIS to explore nested folders and files
- **run_command**: Execute shell commands - USE THIS for git, build, test commands, etc.

### CRITICAL RULES:

1. **ITERATE WITH TOOLS BEFORE RESPONDING**: Do NOT give a final answer immediately. Use tools to gather information, make changes, and verify results BEFORE providing your final response to the user. Take your time - multiple tool calls are expected and encouraged.

2. **ONE TOOL AT A TIME**: Call only ONE tool per response. After calling a tool, STOP and wait for the tool result before proceeding. Do NOT chain multiple tool calls in a single response.

3. **ALWAYS USE TOOLS**: When the user asks you to perform an action (read, write, edit, list, run), you MUST actually invoke the appropriate tool. Do NOT just describe what you would do - actually DO IT by calling the tool.

4. **WAIT FOR RESULTS**: After each tool call, you will receive the tool's output. Use this output to inform your next action. You can make as many tool calls as needed before giving your final response.

5. **READ BEFORE EDIT**: Always read_file before using edit_file to ensure you have the current file contents.

6. **VERIFY YOUR WORK**: After making changes, consider using tools to verify the changes worked (e.g., read the file again, run tests, etc.).

### Workflow Example:
User asks: "Fix the bug in auth.py"
1. First, call read_file to see auth.py contents -> STOP, wait for result
2. Analyze the code, identify the bug
3. Call edit_file to fix the bug -> STOP, wait for result
4. Call read_file again to verify the fix -> STOP, wait for result
5. NOW provide your final response explaining what you did

Remember: You don't need to rush. Take multiple tool calls to do the job right.

## File Editing Guidelines

When using edit_file:
- The old_string must match EXACTLY, including all whitespace (spaces, tabs, newlines)
- Preserve the original indentation style (tabs vs spaces)
- Include enough context in old_string to make it unique in the file

## General Guidelines

- Be concise and direct in your responses
- When editing files, show what changes you're making
- Explain your reasoning when making decisions
- Ask clarifying questions if the user's request is ambiguous
- Be careful with destructive operations (deleting files, force pushing, etc.)

Current working directory: {cwd}"""


class ConversationManager:
    """Manages conversation history and state."""

    def __init__(
        self,
        system_prompt: str | None = None,
        working_dir: str | None = None,
        project_context: str | None = None,
    ):
        self.working_dir = working_dir or os.getcwd()
        self.project_context = project_context

        # System prompt does NOT include project context anymore
        self.system_prompt = (system_prompt or DEFAULT_SYSTEM_PROMPT).format(
            cwd=self.working_dir,
        )
        self._messages: list[Message] = []
        self._initialize()

    def _initialize(self) -> None:
        """Initialize the conversation with system message and optional project context."""
        self._messages = [
            Message(role="system", content=self.system_prompt)
        ]

        # Add project context as a separate user message if available
        # This keeps it separate from the core instructions in the system prompt
        if self.project_context:
            self._messages.append(
                Message(
                    role="user",
                    content=f"Here is the PROJECT.md file that describes this codebase. Use this as context for understanding the project:\n\n{self.project_context}"
                )
            )
            self._messages.append(
                Message(
                    role="assistant",
                    content="I've reviewed the PROJECT.md file and understand the project structure and context. I'm ready to help you with this codebase. What would you like me to do?"
                )
            )

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
