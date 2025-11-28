"""Core agent that orchestrates LLM interactions and tool execution."""

import asyncio
from typing import AsyncIterator, Callable

from .providers.base import LLMProvider, Message, StreamChunk, ToolCall
from .state.conversation import ConversationManager
from .tools.registry import ToolRegistry


class Agent:
    """The main agent that handles conversations and tool execution."""

    def __init__(
        self,
        provider: LLMProvider,
        conversation: ConversationManager,
        tools: ToolRegistry,
        on_tool_start: Callable[[ToolCall], None] | None = None,
        on_tool_end: Callable[[str, str], None] | None = None,
        max_tool_iterations: int = 10,
    ):
        self.provider = provider
        self.conversation = conversation
        self.tools = tools
        self.on_tool_start = on_tool_start
        self.on_tool_end = on_tool_end
        self.max_tool_iterations = max_tool_iterations

    async def run(self, user_input: str) -> AsyncIterator[str]:
        """Process user input and yield response chunks.

        This handles the full agentic loop:
        1. Send user message to LLM
        2. If LLM requests tool calls, execute ALL of them
        3. Send tool results back to LLM (new API request)
        4. Repeat until LLM gives final response (no tool calls)

        Args:
            user_input: The user's message

        Yields:
            Text chunks of the assistant's response
        """
        self.conversation.add_user_message(user_input)

        iteration = 0
        while iteration < self.max_tool_iterations:
            iteration += 1

            # Get streaming response from LLM
            response_content = ""
            tool_calls: list[ToolCall] = []

            stream = await self.provider.chat(
                messages=self.conversation.get_messages(),
                tools=self.tools.list_tools(),
                stream=True,
            )

            # Collect response but DON'T yield yet - wait to see if there's a tool call
            async for chunk in stream:
                if chunk.content:
                    response_content += chunk.content

                if chunk.tool_calls:
                    tool_calls = chunk.tool_calls

            # If no tool calls, we're done - yield the response and exit
            if not tool_calls:
                if response_content:
                    yield response_content
                    self.conversation.add_assistant_message(content=response_content)
                break

            # Tool calls detected - DISCARD any text response (it's premature reasoning)
            # Add assistant message with ALL tool calls
            self.conversation.add_assistant_message(
                content=None,  # Discard text when there's a tool call
                tool_calls=tool_calls,
            )

            # Execute ALL tool calls and collect results
            for tool_call in tool_calls:
                if self.on_tool_start:
                    self.on_tool_start(tool_call)

                result = await self.tools.execute_async(tool_call)
                self.conversation.add_tool_result(result)

                if self.on_tool_end:
                    self.on_tool_end(tool_call.name, result.content)

            # Loop continues - will make a new API request with all tool results

        if iteration >= self.max_tool_iterations:
            yield "\n\n[Reached maximum tool iterations]"

    async def run_sync(self, user_input: str) -> str:
        """Run and return complete response (non-streaming)."""
        chunks = []
        async for chunk in self.run(user_input):
            chunks.append(chunk)
        return "".join(chunks)

    def reset(self) -> str:
        """Reset the conversation state and correlation ID.

        Returns:
            The new correlation ID
        """
        self.conversation.clear()
        # Reset correlation ID when conversation is cleared
        return self.provider.reset_correlation_id()

    def get_correlation_id(self) -> str:
        """Get the current correlation ID."""
        return self.provider.get_correlation_id()

    async def close(self) -> None:
        """Clean up resources."""
        await self.provider.close()
