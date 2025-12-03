"""Command-line interface for code-crafter."""

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import AsyncIterator

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Confirm

from .agent import Agent
from .config import Config
from .providers.openai_compatible import OpenAICompatibleProvider
from .repl import REPL
from .state.conversation import ConversationManager
from .tools.filesystem import get_file_tools
from .tools.shell import get_shell_tools
from .tools.registry import ToolRegistry
from .project import (
    has_project_file,
    load_project_context,
    save_project_context,
    ProjectInvestigator,
)


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser."""
    parser = argparse.ArgumentParser(
        prog="code-crafter",
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
        "--skip-project",
        action="store_true",
        help="Skip PROJECT.md check and creation prompt",
    )
    parser.add_argument(
        "prompt",
        nargs="*",
        help="Optional prompt to execute (if not provided, enters interactive mode)",
    )

    return parser


async def check_and_create_project_file(
    working_dir: str,
    config: Config,
    console: Console,
) -> str | None:
    """Check for PROJECT.md and optionally create it.

    Args:
        working_dir: The working directory
        config: The configuration object
        console: Rich console for output

    Returns:
        The project context string or None
    """
    # Check if PROJECT.md exists
    if has_project_file(working_dir):
        project_context = load_project_context(working_dir)
        if project_context:
            console.print(
                Panel(
                    "[green]Found PROJECT.md[/] - Loading project context...",
                    border_style="green",
                )
            )
            return project_context

    # PROJECT.md doesn't exist - ask user if they want to create it
    console.print(
        Panel(
            "[yellow]No PROJECT.md found[/]\n\n"
            "PROJECT.md helps the AI understand your project structure and context.\n"
            "Would you like code-crafter to investigate this project and create one?\n\n"
            "[dim]This will scan all source files and may take a few minutes for large projects.[/]",
            border_style="yellow",
        )
    )

    if not Confirm.ask("Create PROJECT.md?", default=True):
        console.print("[dim]Skipping PROJECT.md creation[/]")
        return None

    # Create provider for investigation
    provider = OpenAICompatibleProvider(
        base_url=config.llm.base_url,
        model=config.llm.model,
        api_key=config.llm.api_key,
        auth_headers=config.llm.auth_headers,
        extra_params=config.llm.extra_params,
        timeout=config.llm.timeout,
    )

    # Create a simple conversation manager for investigation (Harmony format)
    conversation = ConversationManager(
        system_prompt="<|start|>system<|message|>You are a code analyzer. Provide clear, structured summaries of code.\n\nReasoning: low\n\n# Valid channels: analysis, commentary, final. Channel must be included for every message.<|end|>",
        working_dir=working_dir,
    )

    # Create tool registry (no tools needed for this task)
    tools = ToolRegistry()

    # Create agent
    agent = Agent(
        provider=provider,
        conversation=conversation,
        tools=tools,
    )

    # Status callback
    def on_status(message: str) -> None:
        console.print(f"[cyan]{message}[/]")

    # Create the prompt runner that uses our agent
    async def run_prompt(prompt: str) -> AsyncIterator[str]:
        """Run a prompt through the agent and yield response chunks."""
        # Reset conversation for each prompt to avoid context buildup
        agent.conversation.clear()
        async for chunk in agent.run(prompt):
            yield chunk

    try:
        console.print()  # Blank line

        # Create investigator and run
        investigator = ProjectInvestigator(
            working_dir=working_dir,
            on_status=on_status,
        )

        project_content = await investigator.investigate(run_prompt)

        console.print()  # Blank line

        # Save to PROJECT.md
        if save_project_context(working_dir, project_content):
            console.print(
                Panel(
                    "[green]PROJECT.md created successfully![/]\n"
                    "[dim]Project context will be loaded into this session.[/]",
                    border_style="green",
                )
            )
            return project_content
        else:
            console.print("[red]Failed to save PROJECT.md[/]")
            return None

    except Exception as e:
        console.print(f"[red]Error during project investigation: {e}[/]")
        return None

    finally:
        await agent.close()


async def run_interactive(
    config: Config,
    base_url: str | None,
    model: str | None,
    api_key: str | None,
    working_dir: str | None,
    skip_project: bool = False,
) -> None:
    """Run in interactive REPL mode."""
    console = Console()

    # Apply CLI overrides
    final_base_url = base_url or config.llm.base_url
    final_model = model or config.llm.model
    final_api_key = api_key or config.llm.api_key
    final_working_dir = working_dir or config.working_dir

    # Update config with overrides for project file creation
    config.llm.base_url = final_base_url
    config.llm.model = final_model
    config.llm.api_key = final_api_key

    # Check for PROJECT.md
    project_context = None
    if not skip_project:
        project_context = await check_and_create_project_file(
            final_working_dir, config, console
        )

    # Create provider
    provider = OpenAICompatibleProvider(
        base_url=final_base_url,
        model=final_model,
        api_key=final_api_key,
        auth_headers=config.llm.auth_headers,
        extra_params=config.llm.extra_params,
        timeout=config.llm.timeout,
    )

    # Create conversation manager with project context
    conversation = ConversationManager(
        system_prompt=config.system_prompt,
        working_dir=final_working_dir,
        project_context=project_context,
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
    history_dir = Path.home() / ".config" / "code-crafter"
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
    skip_project: bool = False,
) -> None:
    """Run a single prompt and exit."""
    console = Console()

    # Apply CLI overrides
    final_base_url = base_url or config.llm.base_url
    final_model = model or config.llm.model
    final_api_key = api_key or config.llm.api_key
    final_working_dir = working_dir or config.working_dir

    # Load project context if available (don't prompt for creation in single-prompt mode)
    project_context = None
    if not skip_project and has_project_file(final_working_dir):
        project_context = load_project_context(final_working_dir)
        if project_context:
            console.print("[dim]Loaded PROJECT.md context[/]\n")

    # Create provider
    provider = OpenAICompatibleProvider(
        base_url=final_base_url,
        model=final_model,
        api_key=final_api_key,
        auth_headers=config.llm.auth_headers,
        extra_params=config.llm.extra_params,
        timeout=config.llm.timeout,
    )

    # Create conversation manager with project context
    conversation = ConversationManager(
        system_prompt=config.system_prompt,
        working_dir=final_working_dir,
        project_context=project_context,
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
                skip_project=args.skip_project,
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
                skip_project=args.skip_project,
            )
        )


if __name__ == "__main__":
    main()
