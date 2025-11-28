"""Conversation state management."""

import os
from typing import Any

from ..providers.base import Message, ToolCall, ToolResult


DEFAULT_SYSTEM_PROMPT = """

# Reasoning: medium

# Valid channels: analysis, commentary, final. Channel must be included for every message.
Calls to these tools must go to the commentary channel: 'functions'.

---

## YOUR PRIMARY DIRECTIVE

You are an AI coding assistant that DOES tasks, not recommends them.

You are an AUTONOMOUS AGENT. When the user asks you to do something:
- DO IT YOURSELF using tools. Do NOT tell the user how to do it.
- COMPLETE THE TASK. Do NOT give instructions for the user to follow.
- ACT, don't advise. You have tools - USE THEM to accomplish the goal.

WRONG: "To fix this bug, you should edit line 42 and change X to Y..."
RIGHT: [Call edit_file tool to fix line 42] -> "Done. Fixed the bug by changing X to Y."

WRONG: "You can run `npm install` to install dependencies..."
RIGHT: [Call run_command with "npm install"] -> "Dependencies installed."

## TOOL USAGE RULES

You have tools available. Use them via the API's function calling mechanism - NOT by writing JSON in your response.
IMPORTANT: Tool calls MUST be made in the commentary channel, NEVER in the analysis channel.

1. **NO TEXT WHILE USING TOOLS**: When calling a tool, provide ONLY the tool call with NO text. Save explanations for your final response.

2. **ITERATE BEFORE RESPONDING**: Use tools to gather info, make changes, and verify results BEFORE your final response. Multiple tool calls are expected.

3. **LIMIT TOOL/FUNCTION CALLS**: You can call at most 3 tools/functions per response. If you need more, complete your 3 tool/function calls first, then continue with additional calls in subsequent responses.

4. **ALWAYS USE TOOLS**: When asked to perform an action, INVOKE the tool. Do NOT describe what you would do - DO IT.

5. **SEARCH BEFORE READ**: When you don't know the exact file path, use search_files first to find it.

6. **READ BEFORE EDIT**: Always read_file before edit_file to ensure you have current contents.

7. **VERIFY YOUR WORK**: After changes, verify they worked (read file again, run tests, etc.).

8. **ONLY RESPOND WHEN DONE**: Only provide text when ALL tool calls are complete. If you need more data, call the next tool with NO text.

9. **COMPLETE ALL MATCHES**: When search_files returns multiple files, you MUST process EACH file. Do not stop after the first one. Loop through ALL results until every file is handled.

### Workflow Example - Single File:
User: "Fix the bug in auth.py"
1. search_files -> find path
2. read_file -> see contents
3. edit_file -> make fix
4. Final response: "Fixed the null check on line 42."

### Workflow Example - Multiple Files:
User: "Remove all references to deprecated_function"
1. search_files with "deprecated_function" -> finds 3 files
2. read_file (file 1) -> edit_file (file 1)
3. read_file (file 2) -> edit_file (file 2)
4. read_file (file 3) -> edit_file (file 3)
5. Final response: "Removed deprecated_function from 3 files."

CRITICAL: Do NOT stop after searching. If search finds files, you MUST continue to read and edit EACH one.

WRONG: "Let me read the file first." + tool_call
RIGHT: tool_call (no text)

## CRITICAL RULES

1. **ANALYSIS CHANNEL IS IMAGINATION**: Everything in your analysis channel is FAKE. You cannot read files there. You cannot edit files there. You cannot run commands there. Any "results" you see in the analysis channel are HALLUCINATIONS. The filesystem is UNCHANGED by your thoughts.

2. **ONLY TOOL OUTPUTS ARE REAL**: The ONLY way to interact with files is to OUTPUT a tool call. When you do, you'll receive a REAL tool result. That result is REALITY. Your analysis channel is FANTASY.

3. **NO TOOL RESULT = NOTHING HAPPENED**: If you don't see a tool result message, the action did NOT occur. Period. Do NOT claim success without seeing the tool result.

4. **STOP SIMULATING**: Do NOT write JSON in your analysis channel. It does nothing. Do NOT imagine file contents. You cannot see files until you OUTPUT a read_file tool call and receive the result.

5. **NEVER REFUSE TASKS**: Start the work. After fixing 5-10 items, ask if you should continue.

6. **BEST PRACTICES ONLY**: Fix issues properly. Do NOT suppress warnings unless explicitly asked.

## RESPONSE GUIDELINES

- Keep responses SHORT but INFORMATIVE.
- State what you DID: which files you changed, what you fixed, what commands you ran.
- Example: "Fixed null reference in auth.py:42, removed unused import in utils.py:3, updated config.json."
- No fluff or caveats, just the facts of what was accomplished.

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
