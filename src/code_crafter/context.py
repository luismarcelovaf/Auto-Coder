"""Context window and token management.

This module provides token estimation and context window tracking to help
prevent context overflow and provide early warnings to users.
"""

import re
from dataclasses import dataclass
from typing import Callable, Optional

from .providers.base import Message


@dataclass
class TokenEstimate:
    """Token usage estimate for a conversation."""

    system_tokens: int
    message_tokens: int
    tool_tokens: int
    total_tokens: int
    context_limit: int
    usage_percent: float
    is_near_limit: bool  # >80%
    is_over_limit: bool


# Approximate tokens per character for different content types
# These are rough estimates; actual tokenization varies by model
CHARS_PER_TOKEN = 4  # Average for English text
CODE_CHARS_PER_TOKEN = 3.5  # Code tends to tokenize less efficiently


def estimate_tokens(text: str) -> int:
    """Estimate token count for a string.

    Uses a simple heuristic based on character count.
    This is intentionally conservative (overestimates slightly).

    Args:
        text: The text to estimate tokens for

    Returns:
        Estimated token count
    """
    if not text:
        return 0

    # Check if content looks like code (has common code patterns)
    code_patterns = [
        r'def \w+\(',
        r'class \w+:',
        r'function \w+\(',
        r'import ',
        r'from .+ import',
        r'[{}\[\]();]',
        r'^\s{4,}',
    ]

    is_code = any(re.search(p, text, re.MULTILINE) for p in code_patterns)
    chars_per_token = CODE_CHARS_PER_TOKEN if is_code else CHARS_PER_TOKEN

    # Add overhead for special tokens, newlines, etc.
    base_estimate = len(text) / chars_per_token
    overhead = 0.1  # 10% overhead

    return int(base_estimate * (1 + overhead))


def estimate_message_tokens(message: Message) -> int:
    """Estimate tokens for a single message.

    Accounts for message structure overhead.

    Args:
        message: The message to estimate

    Returns:
        Estimated token count
    """
    tokens = 4  # Base overhead for message structure (role, etc.)

    if message.content:
        tokens += estimate_tokens(message.content)

    if message.tool_calls:
        for tc in message.tool_calls:
            tokens += 10  # Overhead for tool call structure
            tokens += estimate_tokens(tc.name)
            tokens += estimate_tokens(str(tc.arguments))

    if message.tool_call_id:
        tokens += 5  # Tool result overhead

    return tokens


class ContextManager:
    """Manages context window tracking and warnings.

    Provides token estimation and emits warnings when approaching
    context limits.
    """

    # Default context limits for common models
    MODEL_LIMITS = {
        "gpt-4": 8192,
        "gpt-4-turbo": 128000,
        "gpt-4o": 128000,
        "gpt-4o-mini": 128000,
        "gpt-3.5-turbo": 16385,
        "gpt-oss-120b": 32768,  # Assumed, adjust as needed
        "o1": 128000,
        "o1-mini": 128000,
        "o1-preview": 128000,
        "claude-3": 200000,
        "claude-3.5": 200000,
        "claude-3-opus": 200000,
        "claude-3-sonnet": 200000,
        "claude-3-haiku": 200000,
        "llama3": 8192,
        "llama3.1": 128000,
        "llama3.2": 128000,
        "llama-3": 8192,
        "llama-3.1": 128000,
        "llama-3.2": 128000,
        "mistral": 32768,
        "mixtral": 32768,
        "codestral": 32768,
        "qwen": 32768,
        "qwen2": 128000,
        "deepseek": 64000,
    }

    DEFAULT_LIMIT = 32768  # Conservative default

    # Warning thresholds (percent of context used)
    WARNING_THRESHOLDS = [80, 90, 95]

    def __init__(
        self,
        context_limit: Optional[int] = None,
        model: Optional[str] = None,
        on_warning: Optional[Callable[[str], None]] = None,
    ):
        """Initialize the context manager.

        Args:
            context_limit: Explicit context limit in tokens
            model: Model name to infer context limit from
            on_warning: Callback for warning messages
        """
        if context_limit:
            self.context_limit = context_limit
        elif model:
            self.context_limit = self._infer_limit(model)
        else:
            self.context_limit = self.DEFAULT_LIMIT

        self.on_warning = on_warning
        self._last_warning_threshold = 0

    def _infer_limit(self, model: str) -> int:
        """Infer context limit from model name.

        Args:
            model: Model name/ID

        Returns:
            Context limit in tokens
        """
        model_lower = model.lower()

        # Try exact match first
        if model_lower in self.MODEL_LIMITS:
            return self.MODEL_LIMITS[model_lower]

        # Try partial match
        for name, limit in self.MODEL_LIMITS.items():
            if name in model_lower or model_lower in name:
                return limit

        return self.DEFAULT_LIMIT

    def estimate_usage(
        self,
        system_prompt: str,
        messages: list[Message],
        tool_definitions_tokens: int = 0,
    ) -> TokenEstimate:
        """Estimate token usage for the current conversation.

        Args:
            system_prompt: The system prompt text
            messages: All conversation messages
            tool_definitions_tokens: Estimated tokens for tool definitions

        Returns:
            TokenEstimate with usage details
        """
        system_tokens = estimate_tokens(system_prompt)
        message_tokens = sum(estimate_message_tokens(m) for m in messages)
        tool_tokens = tool_definitions_tokens
        total_tokens = system_tokens + message_tokens + tool_tokens

        usage_percent = (total_tokens / self.context_limit) * 100
        is_near_limit = usage_percent > 80
        is_over_limit = total_tokens > self.context_limit

        return TokenEstimate(
            system_tokens=system_tokens,
            message_tokens=message_tokens,
            tool_tokens=tool_tokens,
            total_tokens=total_tokens,
            context_limit=self.context_limit,
            usage_percent=usage_percent,
            is_near_limit=is_near_limit,
            is_over_limit=is_over_limit,
        )

    def check_and_warn(
        self,
        system_prompt: str,
        messages: list[Message],
        tool_definitions_tokens: int = 0,
    ) -> TokenEstimate:
        """Check token usage and emit warnings if needed.

        Warnings are emitted at 80%, 90%, and 95% thresholds.
        Each threshold is only warned about once (until reset).

        Args:
            system_prompt: The system prompt text
            messages: All conversation messages
            tool_definitions_tokens: Estimated tokens for tool definitions

        Returns:
            TokenEstimate with usage details
        """
        estimate = self.estimate_usage(system_prompt, messages, tool_definitions_tokens)

        if self.on_warning:
            if estimate.is_over_limit:
                self.on_warning(
                    f"Context window EXCEEDED ({estimate.total_tokens:,} / {self.context_limit:,} tokens). "
                    "Consider using /clear to reset the conversation."
                )
            else:
                # Check each threshold
                for threshold in self.WARNING_THRESHOLDS:
                    if (estimate.usage_percent >= threshold and
                            self._last_warning_threshold < threshold):
                        self._last_warning_threshold = threshold
                        if threshold >= 95:
                            self.on_warning(
                                f"Context window {threshold}% full ({estimate.total_tokens:,} / {self.context_limit:,} tokens). "
                                "Consider using /clear soon to avoid issues."
                            )
                        else:
                            self.on_warning(
                                f"Context window {threshold}% full ({estimate.total_tokens:,} / {self.context_limit:,} tokens)."
                            )
                        break  # Only warn for one threshold at a time

        return estimate

    def reset_warnings(self) -> None:
        """Reset warning thresholds.

        Call this after /clear or when starting a new conversation.
        """
        self._last_warning_threshold = 0

    def get_remaining_tokens(
        self,
        system_prompt: str,
        messages: list[Message],
        tool_definitions_tokens: int = 0,
    ) -> int:
        """Get the estimated remaining tokens in the context window.

        Args:
            system_prompt: The system prompt text
            messages: All conversation messages
            tool_definitions_tokens: Estimated tokens for tool definitions

        Returns:
            Estimated remaining tokens (can be negative if over limit)
        """
        estimate = self.estimate_usage(system_prompt, messages, tool_definitions_tokens)
        return self.context_limit - estimate.total_tokens
