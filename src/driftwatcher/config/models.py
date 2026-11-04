"""Validated tool settings (plan sec. 7).

Everything lives in committed `driftwatch.config.yaml` except secrets:
a profile names the environment variable holding the key (`api_key_env`).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

StructuredOutput = Literal["json_schema", "json_object", "prompt_only"]
LogLevel = Literal["TRACE", "DEBUG", "INFO", "WARNING", "ERROR"]
ConsoleFormat = Literal["pretty", "plain", "json"]
CheckMode = Literal["warn", "enforce"]


class ProfileConfig(BaseModel):
    provider: str = "openai_compatible"
    base_url: str | None = None
    base_url_env: str | None = None
    api_key_env: str = "BASETEN_API_KEY"
    model: str = "meta-models/muse-spark-open-1026"
    structured_output: StructuredOutput = "json_schema"
    reasoning_effort: str | None = None
    timeout_s: float = 60
    max_retries: int = 2
    extra_body: dict | None = None


class CallConfig(BaseModel):
    temperature: float = 0
    validation_retries: int = 1
    max_output_tokens: int | None = 2000
    reasoning_effort: str | None = "low"


class BudgetConfig(BaseModel):
    max_calls_per_run: int = 200
    max_input_tokens_per_call: int = 6000


class LLMConfig(BaseModel):
    default_profile: str = "meta_api"
    profiles: dict[str, ProfileConfig] = Field(default_factory=dict)
    agents: dict[str, str] = Field(default_factory=dict)
    call: CallConfig = Field(default_factory=CallConfig)
    budget: BudgetConfig = Field(default_factory=BudgetConfig)

    @model_validator(mode="after")
    def _default_profile_exists(self) -> LLMConfig:
        if self.profiles and self.default_profile not in self.profiles:
            raise ValueError(
                f"default_profile {self.default_profile!r} is not in "
                f"llm.profiles ({sorted(self.profiles)})"
            )
        for agent, profile in self.agents.items():
            if profile not in self.profiles:
                raise ValueError(
                    f"llm.agents.{agent} points at unknown profile {profile!r}"
                )
        return self


class ConsoleConfig(BaseModel):
    enabled: bool = True
    format: ConsoleFormat = "pretty"


class FileConfig(BaseModel):
    enabled: bool = True
    dir: str = ".drift/logs"
    keep_last_runs: int = 20


class LoggingConfig(BaseModel):
    level: LogLevel = "INFO"
    console: ConsoleConfig = Field(default_factory=ConsoleConfig)
    file: FileConfig = Field(default_factory=FileConfig)
    max_value_chars: int = 120
    max_list_items: int = 3
    redact_keys: list[str] = Field(
        default_factory=lambda: [
            "api_key", "authorization", "token", "secret", "password",
        ]
    )


class ScanConfig(BaseModel):
    deny_globs: list[str] = Field(
        default_factory=lambda: [
            "**/CHANGELOG.md",
            "**/LICENSE*.md",
            "**/node_modules/**",
            "**/vendor/**",
        ]
    )
    known_context_names: list[str] = Field(
        default_factory=lambda: ["AGENTS.md", "SKILL.md", "CLAUDE.md", "GEMINI.md"]
    )


class CheckConfig(BaseModel):
    default_mode: CheckMode = "warn"


class CacheConfig(BaseModel):
    dir: str = ".drift/cache"


class DriftConfig(BaseModel):
    version: int = 1
    llm: LLMConfig = Field(default_factory=LLMConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    scan: ScanConfig = Field(default_factory=ScanConfig)
    check: CheckConfig = Field(default_factory=CheckConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)


DEFAULT_YAML: dict = {
    "version": 1,
    "llm": {
        "default_profile": "meta_api",
        "profiles": {
            "baseten": {
                "provider": "openai_compatible",
                "base_url": "https://inference.baseten.co/v1",
                "api_key_env": "BASETEN_API_KEY",
                "model": "meta-models/muse-spark-open-1026",
                "structured_output": "json_schema",
                "timeout_s": 60,
            },
            "meta_api": {
                "provider": "openai_compatible",
                "base_url": "https://api.meta.ai/v1",
                "base_url_env": "MODEL_API_BASE_URL",
                "api_key_env": "MODEL_API_KEY",
                "model": "muse-spark-1.3",
                "structured_output": "json_schema",
                "timeout_s": 180,
                "max_retries": 4,
            },
        },
        "agents": {"judge": "meta_api", "doc_mapper": "meta_api"},
        "call": {
            "temperature": 0,
            "validation_retries": 1,
            "max_output_tokens": 2000,
            "reasoning_effort": "low",
        },
        "budget": {"max_calls_per_run": 200, "max_input_tokens_per_call": 6000},
    },
}


def default_config() -> DriftConfig:
    """Built-in defaults used when no config file exists."""
    return DriftConfig.model_validate(DEFAULT_YAML)
