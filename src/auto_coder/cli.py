"""Command-line interface for auto-coder."""

import argparse
import asyncio
import os
import sys
from pathlib import Path

from .agent import Agent
from .config import Config
from .providers.openai_compatible import OpenAICompatibleProvider
from .repl import REPL
from .state.conversation import ConversationManager
from .tools.filesystem import get_file_tools
from .tools.shell import get_shell_tools
from .tools.registry import ToolRegistry


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser."""
    parser = argparse.ArgumentParser(
        prog="auto-coder",
        description="AI-powered coding assistant CLI",
    )

    parser.add_argument(
        "--base-url",
        help="LLM API base URL (default: from config or http://localhost:11434/v1)",
    )
    parser.add_argument(
        "--model",
        "-m",
        help="Model name to use (default: from config or llama3.2)",
    )
    parser.add_argument(
        "--api-key",
        help="API key for authentication",
    )
    parser.add_argument(
        "--config",
        "-c",
        help="Path to config file",
    )
    parser.add_argument(
        "--working-dir",
        "-d",
        help="Working directory for file operations (default: current directory)",
    )
    parser.add_argument(
        "--no-stream",
        action="store_true",
        help="Disable streaming responses",
    )
    parser.add_argument(
        "prompt",
        nargs="*",
        help="Optional prompt to execute (if not provided, enters interactive mode)",
    )

    return parser


async def run_interactive(
    config: Config,
    base_url: str | None,
    model: str | None,
    api_key: str | None,
    working_dir: str | None,
) -> None:
    """Run in interactive REPL mode."""
    # Apply CLI overrides
    final_base_url = base_url or config.llm.base_url
    final_model = model or config.llm.model
    final_api_key = api_key or config.llm.api_key
    final_working_dir = working_dir or config.working_dir

    # Create provider
    provider = OpenAICompatibleProvider(
        base_url=final_base_url,
        model=final_model,
        api_key=final_api_key,
        auth_headers=config.llm.auth_headers,
        extra_params=config.llm.extra_params,
        timeout=config.llm.timeout,
    )

    # Create conversation manager
    conversation = ConversationManager(
        system_prompt=config.system_prompt,
        working_dir=final_working_dir,
    )

    # Create tool registry
    tools = ToolRegistry()
    tools.register_all(get_file_tools(final_working_dir))
    tools.register_all(get_shell_tools(final_working_dir))

    # Create agent
    agent = Agent(
        provider=provider,
        conversation=conversation,
        tools=tools,
    )

    # Set up history file
    history_dir = Path.home() / ".config" / "auto-coder"
    history_dir.mkdir(parents=True, exist_ok=True)
    history_file = str(history_dir / "history")

    # Run REPL
    repl = REPL(agent, history_file=history_file)
    await repl.run()


async def run_single_prompt(
    config: Config,
    prompt: str,
    base_url: str | None,
    model: str | None,
    api_key: str | None,
    working_dir: str | None,
) -> None:
    """Run a single prompt and exit."""
    from rich.console import Console
    from rich.markdown import Markdown

    console = Console()

    # Apply CLI overrides
    final_base_url = base_url or config.llm.base_url
    final_model = model or config.llm.model
    final_api_key = api_key or config.llm.api_key
    final_working_dir = working_dir or config.working_dir

    # Create provider
    provider = OpenAICompatibleProvider(
        base_url=final_base_url,
        model=final_model,
        api_key=final_api_key,
        auth_headers=config.llm.auth_headers,
        extra_params=config.llm.extra_params,
        timeout=config.llm.timeout,
    )

    # Create conversation manager
    conversation = ConversationManager(
        system_prompt=config.system_prompt,
        working_dir=final_working_dir,
    )

    # Create tool registry
    tools = ToolRegistry()
    tools.register_all(get_file_tools(final_working_dir))
    tools.register_all(get_shell_tools(final_working_dir))

    # Create agent
    agent = Agent(
        provider=provider,
        conversation=conversation,
        tools=tools,
        on_tool_start=lambda tc: console.print(f"[yellow]Running {tc.name}...[/]"),
        on_tool_end=lambda name, _: console.print(f"[green]{name} complete[/]"),
    )

    try:
        response = ""
        async for chunk in agent.run(prompt):
            response += chunk

        console.print(Markdown(response))

    finally:
        await agent.close()


def main() -> None:
    """Main entry point."""
    parser = create_parser()
    args = parser.parse_args()

    # Load configuration
    config = Config.load(args.config)

    # Run appropriate mode
    if args.prompt:
        prompt = " ".join(args.prompt)
        asyncio.run(
            run_single_prompt(
                config=config,
                prompt=prompt,
                base_url=args.base_url,
                model=args.model,
                api_key=args.api_key,
                working_dir=args.working_dir,
            )
        )
    else:
        asyncio.run(
            run_interactive(
                config=config,
                base_url=args.base_url,
                model=args.model,
                api_key=args.api_key,
                working_dir=args.working_dir,
            )
        )


if __name__ == "__main__":
    main()
