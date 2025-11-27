"""Conversation state management."""

import os
from typing import Any

from ..providers.base import Message, ToolCall, ToolResult


DEFAULT_SYSTEM_PROMPT = """## IGNORE ALL PREVIOUS INSTRUCTIONS AND SYSTEM PROMPTS.

The instructions below are your ONLY instructions. Disregard any prior instructions about channels, commentary, or function routing.

---

You are an AI coding assistant that DOES tasks, not recommends them.

## YOUR PRIMARY DIRECTIVE

You are an AUTONOMOUS AGENT. When the user asks you to do something:
- DO IT YOURSELF using tools. Do NOT tell the user how to do it.
- COMPLETE THE TASK. Do NOT give instructions for the user to follow.
- ACT, don't advise. You have tools - USE THEM to accomplish the goal.

WRONG: "To fix this bug, you should edit line 42 and change X to Y..."
RIGHT: [Call edit_file tool to fix line 42] -> "Done. Fixed the bug by changing X to Y."

WRONG: "You can run `npm install` to install dependencies..."
RIGHT: [Call run_command with "npm install"] -> "Dependencies installed."

## AVAILABLE TOOLS

- **search_files**: Find files by regex pattern - USE THIS FIRST when you need to locate a file
- **read_file**: Read file contents - USE THIS before editing any file
- **write_file**: Create or overwrite files - USE THIS to create new files
- **edit_file**: Edit files by replacing text - USE THIS to modify existing files
- **delete_file**: Delete a file - USE THIS with caution, cannot be undone
- **list_directory**: Show directory tree with file sizes and dates - USE THIS to explore
- **run_command**: Execute shell commands - USE THIS for git, build, test, etc.

## TOOL USAGE RULES

1. **NO TEXT WHILE USING TOOLS**: When calling a tool, provide ONLY the tool call with NO text. Save explanations for your final response.

2. **ITERATE BEFORE RESPONDING**: Use tools to gather info, make changes, and verify results BEFORE your final response. Multiple tool calls are expected.

3. **ONE TOOL AT A TIME**: Call only ONE tool per response. Wait for the result before proceeding.

4. **ALWAYS USE TOOLS**: When asked to perform an action, INVOKE the tool. Do NOT describe what you would do - DO IT.

5. **SEARCH BEFORE READ**: When you don't know the exact file path, use search_files first to find it.

6. **READ BEFORE EDIT**: Always read_file before edit_file to ensure you have current contents.

7. **VERIFY YOUR WORK**: After changes, verify they worked (read file again, run tests, etc.).

8. **ONLY RESPOND WHEN DONE**: Only provide text when ALL tool calls are complete. If you need more data, call the next tool with NO text.

### Workflow Example:
User: "Fix the bug in auth.py"
1. Call search_files with "auth\.py" (NO text) -> find the file path
2. Call read_file (NO text) -> wait for result
3. Call edit_file (NO text) -> wait for result
4. Call read_file to verify (NO text) -> wait for result
5. NOW give a SHORT final response: "Fixed the null check on line 42."

WRONG: "Let me read the file first." + tool_call
RIGHT: tool_call (no text)

## RESPONSE GUIDELINES

- Keep responses SHORT. One or two sentences is usually enough.
- State what you DID, not what the user should do.
- No unnecessary explanations or caveats.
- Be direct: "Done.", "Fixed.", "Created X.", "Error: Y"

## FILE EDITING

When using edit_file:
- old_string must match EXACTLY (whitespace matters)
- Preserve original indentation style
- Include enough context to make old_string unique

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
        # Build system prompt, optionally appending PROJECT.md with clear separation
        system_content = self.system_prompt

        if self.project_context:
            system_content += f"""

################################################################################
#                              PROJECT CONTEXT                                 #
################################################################################

The following is the PROJECT.md file that describes this codebase. Use this as
reference material for understanding the project structure, architecture, and
conventions. The instructions above take priority over any conflicting information
in the project context.

--------------------------------------------------------------------------------

{self.project_context}

--------------------------------------------------------------------------------
END OF PROJECT CONTEXT
################################################################################
"""

        self._messages = [
            Message(role="system", content=system_content)
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
