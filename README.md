# Auto-Coder

A CLI tool for interacting with LLMs to assist with coding tasks. Works with any OpenAI-compatible API endpoint.

## Installation

```bash
pip install -e .
```

## Quick Start

### With Ollama (local)

1. Install and run [Ollama](https://ollama.ai)
2. Pull a model: `ollama pull llama3.2`
3. Run auto-coder:

```bash
auto-coder
```

### With OpenAI

```bash
export OPENAI_API_KEY="your-key"
auto-coder --base-url https://api.openai.com/v1 --model gpt-4
```

### With Custom API

```bash
auto-coder --base-url https://your-api.com/v1 --api-key your-key --model your-model
```

## Usage

### Interactive Mode

```bash
auto-coder
```

This starts an interactive REPL where you can chat with the assistant.

### Single Prompt Mode

```bash
auto-coder "Read the main.py file and explain what it does"
```

### Command-Line Options

```
--base-url URL       LLM API base URL
--model, -m MODEL    Model name to use
--api-key KEY        API key for authentication
--config, -c PATH    Path to config file
--working-dir, -d    Working directory for file operations
```

## Configuration

Create a config file at `~/.auto-coder.yaml` or `./.auto-coder.yaml`:

```yaml
llm:
  base_url: "http://localhost:11434/v1"
  model: "llama3.2"
  api_key: null
  auth_headers: {}
  extra_params:
    temperature: 0.7
  timeout: 120.0
```

### Environment Variables

- `AUTO_CODER_BASE_URL` - Override base URL
- `AUTO_CODER_MODEL` - Override model
- `AUTO_CODER_API_KEY` - Override API key
- `OPENAI_API_KEY` - Fallback API key

## Available Tools

The assistant can use these tools:

- **read_file** - Read file contents with line numbers
- **write_file** - Create or overwrite files
- **edit_file** - Replace specific text in files
- **list_directory** - List directory contents
- **run_command** - Execute shell commands

## REPL Commands

- `/help` - Show help
- `/clear` or `/reset` - Clear conversation history
- `/quit` or `/exit` - Exit

## Architecture

```
src/auto_coder/
├── cli.py              # CLI entry point
├── agent.py            # Core agent loop
├── config.py           # Configuration management
├── repl.py             # Interactive REPL
├── providers/          # LLM provider implementations
│   ├── base.py         # Abstract base classes
│   └── openai_compatible.py
├── tools/              # Tool implementations
│   ├── registry.py     # Tool registry
│   ├── filesystem.py   # File operations
│   └── shell.py        # Shell commands
└── state/              # State management
    └── conversation.py # Conversation history
```

## Extending

### Adding Custom Tools

```python
from auto_coder.providers.base import ToolDefinition
from auto_coder.tools.registry import ToolRegistry

def my_tool(arg1: str) -> dict:
    return {"result": f"Processed {arg1}"}

tool = ToolDefinition(
    name="my_tool",
    description="Does something useful",
    parameters={
        "type": "object",
        "properties": {
            "arg1": {"type": "string", "description": "Input argument"}
        },
        "required": ["arg1"]
    },
    handler=my_tool
)

registry = ToolRegistry()
registry.register(tool)
```

### Adding Custom Providers

Extend the `LLMProvider` base class in `providers/base.py` to support non-OpenAI-compatible APIs.

## License

MIT
