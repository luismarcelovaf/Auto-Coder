"""Configuration management for code-crafter."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class LLMConfig:
    """Configuration for the LLM provider."""

    base_url: str = "https://<URL>/genai/dev/v1"
    model: str = "llama3.2"
    api_key: str | None = None
    auth_headers: dict[str, str] = field(default_factory=dict)
    extra_params: dict[str, Any] = field(default_factory=dict)
    timeout: float = 120.0


@dataclass
class Config:
    """Main configuration for code-crafter."""

    llm: LLMConfig = field(default_factory=LLMConfig)
    working_dir: str = field(default_factory=os.getcwd)
    system_prompt: str | None = None

    @classmethod
    def load(cls, config_path: str | Path | None = None) -> "Config":
        """Load configuration from file and environment.

        Priority (highest to lowest):
        1. Environment variables
        2. Config file
        3. Defaults
        """
        config = cls()

        # Try to load config file
        if config_path:
            config_file = Path(config_path)
        else:
            # Look for config in standard locations
            config_file = None
            search_paths = [
                Path.cwd() / ".code-crafter.yaml",
                Path.cwd() / ".code-crafter.yml",
                Path.home() / ".config" / "code-crafter" / "config.yaml",
                Path.home() / ".code-crafter.yaml",
            ]
            for path in search_paths:
                if path.exists():
                    config_file = path
                    break

        if config_file and config_file.exists():
            with open(config_file) as f:
                data = yaml.safe_load(f) or {}

            if "llm" in data:
                llm_data = data["llm"]
                config.llm = LLMConfig(
                    base_url=llm_data.get("base_url", config.llm.base_url),
                    model=llm_data.get("model", config.llm.model),
                    api_key=llm_data.get("api_key", config.llm.api_key),
                    auth_headers=llm_data.get("auth_headers", {}),
                    extra_params=llm_data.get("extra_params", {}),
                    timeout=llm_data.get("timeout", config.llm.timeout),
                )

            if "working_dir" in data:
                config.working_dir = data["working_dir"]

            if "system_prompt" in data:
                config.system_prompt = data["system_prompt"]

        # Override with environment variables
        if os.environ.get("CODE_CRAFTER_BASE_URL"):
            config.llm.base_url = os.environ["CODE_CRAFTER_BASE_URL"]

        if os.environ.get("CODE_CRAFTER_MODEL"):
            config.llm.model = os.environ["CODE_CRAFTER_MODEL"]

        if os.environ.get("CODE_CRAFTER_API_KEY"):
            config.llm.api_key = os.environ["CODE_CRAFTER_API_KEY"]

        if os.environ.get("OPENAI_API_KEY") and not config.llm.api_key:
            config.llm.api_key = os.environ["OPENAI_API_KEY"]

        return config

    def save(self, config_path: str | Path) -> None:
        """Save configuration to a file."""
        data = {
            "llm": {
                "base_url": self.llm.base_url,
                "model": self.llm.model,
                "api_key": self.llm.api_key,
                "auth_headers": self.llm.auth_headers,
                "extra_params": self.llm.extra_params,
                "timeout": self.llm.timeout,
            },
            "working_dir": self.working_dir,
        }

        if self.system_prompt:
            data["system_prompt"] = self.system_prompt

        path = Path(config_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "w") as f:
            yaml.dump(data, f, default_flow_style=False)
