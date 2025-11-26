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

### With SSO Authentication

```bash
export USE_SSO=true
export SSO_TOKEN="your-sso-token"  # Or implement token acquisition in auth.py
auto-coder --base-url https://your-api.com/v1 --model your-model
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
- `USE_SSO` - Set to "true" to enable SSO authentication (uses bearer token)
- `SERVER_SIDE_TOKEN_REFRESH` - Set to "true" to use basic credentials for server-side token refresh

## Authentication

### API Key Authentication

The simplest method - provide an API key via:
- `--api-key` command line argument
- `AUTO_CODER_API_KEY` environment variable
- `api_key` in config file

### SSO Authentication

Set `USE_SSO=true` to enable Single Sign-On. This uses `AuthenticationProvider.generate_auth_token()` to obtain a bearer token.

### Server-Side Token Refresh

Set `SERVER_SIDE_TOKEN_REFRESH=true` to use basic credentials. This uses `AuthenticationProvider.get_basic_credentials()` to obtain credentials.

### Client-Side Token Refresh

When neither `USE_SSO` nor `SERVER_SIDE_TOKEN_REFRESH` is enabled, the tool uses `AuthenticationProviderWithClientSideTokenRefresh` which implements `httpx.Auth` to handle authentication and token refresh automatically during requests.

### Authentication Provider

Create `src/auto_coder/authentication_provider.py` with your authentication logic:

```python
import httpx

class AuthenticationProvider:
    def generate_auth_token(self) -> str | None:
        """Generate a bearer token for SSO authentication."""
        # Implement your SSO token logic
        pass

    def get_basic_credentials(self) -> str | None:
        """Get base64-encoded basic credentials for server-side token refresh."""
        # Implement your basic auth logic
        pass

class AuthenticationProviderWithClientSideTokenRefresh(httpx.Auth):
    def auth_flow(self, request: httpx.Request):
        """Handle authentication flow with client-side token refresh."""
        token = self.get_bearer_token()
        request.headers["Authorization"] = f"Bearer {token}"
        yield request

    def get_bearer_token(self) -> str:
        """Get or refresh the bearer token."""
        # Implement your token refresh logic
        pass
```

### Custom Headers

For APIs requiring custom authentication headers:

```yaml
llm:
  auth_headers:
    X-Custom-Auth: "your-token"
    X-API-Version: "2024-01"
```

### Certificate Management

The tool uses `certifi` for SSL certificate verification. To update or customize certificates, implement the `update_certifi()` function in `src/auto_coder/auth.py`.

## Correlation ID

Each conversation session has a unique correlation ID (`x-correlation-id`) that is sent with all API requests. This helps track related operations on the API platform.

- The correlation ID is generated when the session starts
- It resets when you use `/clear` or `/reset`
- Use `/id` to view the current correlation ID

## Available Tools

The assistant can use these tools:

- **read_file** - Read file contents with line numbers
- **write_file** - Create or overwrite files
- **edit_file** - Replace specific text in files
- **list_directory** - List directory contents
- **run_command** - Execute shell commands

## REPL Commands

- `/help` - Show help
- `/clear` or `/reset` - Clear conversation history and reset correlation ID
- `/id` - Show current correlation ID
- `/quit` or `/exit` - Exit

## Architecture

```
src/auto_coder/
├── cli.py              # CLI entry point
├── agent.py            # Core agent loop
├── auth.py             # Authentication (SSO, certificates)
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

### Implementing SSO

Edit `src/auto_coder/auth.py` to implement your SSO provider:

```python
async def get_sso_token() -> str | None:
    if not is_sso_enabled():
        return None

    # Example: OAuth2 device flow
    # 1. Request device code
    # 2. Display user code and verification URL
    # 3. Poll for token
    # 4. Return access token

    return access_token
```

## License

MIT
