"""Config loading: file + env + CLI merge (plan sec. 7.2).

Precedence (highest wins): CLI flags > environment variables
(`DRIFT_LLM_PROFILE`, `DRIFT_LOG_LEVEL`) > config file > built-in
defaults. Validated by pydantic; a missing API key is only an error for
a profile that is actually used (raised lazily by the provider).
"""

from __future__ import annotations

import os
import re
from contextvars import ContextVar
from pathlib import Path

from ..observability.logger import LEVELS
from .models import DriftConfig, ProfileConfig, default_config

CONFIG_FILENAME = "driftwatch.config.yaml"

_active: ContextVar[DriftConfig | None] = ContextVar("drift_config", default=None)


def set_active(config: DriftConfig) -> None:
    _active.set(config)


def get_active() -> DriftConfig:
    config = _active.get()
    if config is None:
        config = default_config()
        _active.set(config)
    return config


def find_config_file(start: str | Path = ".") -> Path | None:
    """Target-repo root via git, else the start dir (plan sec. 3)."""
    from .. import gitutil

    try:
        top = gitutil.rev_parse_toplevel(str(start))
        candidate = Path(top) / CONFIG_FILENAME
        if candidate.exists():
            return candidate
    except RuntimeError:
        pass
    candidate = Path(start) / CONFIG_FILENAME
    return candidate if candidate.exists() else None


def _read_yaml(path: Path) -> dict:
    import yaml

    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def normalize_agent_key(agent_id: str) -> str:
    """'L4.Judge' -> 'judge', 'L2.DocMapper' -> 'doc_mapper'."""
    short = re.sub(r"^L\d+\.", "", agent_id)
    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", short).lower()
    return snake


def load_dotenv_file(path: str | Path = ".env") -> int:
    """Load KEY=VALUE lines into os.environ without overriding real env.

    Returns the number of variables set. Missing file counts as zero.
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return 0
    loaded = 0
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("export ") and "=" in line:
            line = line[7:].lstrip()
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        if not key or not key.replace("_", "").isalnum() or key[0].isdigit():
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key not in os.environ:
            os.environ[key] = value
            loaded += 1
    return loaded


def load(
    config_path: str | Path | None = None,
    *,
    profile: str | None = None,
    model: str | None = None,
    log_level: str | None = None,
    log_format: str | None = None,
    quiet: bool = False,
    repo_root: str | Path = ".",
) -> tuple[DriftConfig, dict[str, str]]:
    """Resolve config; sources maps field path -> flag|env|file|default."""
    load_dotenv_file(Path.cwd() / ".env")
    sources: dict[str, str] = {}
    data: dict = {}
    if config_path:
        found = Path(config_path)
        if not found.exists():
            raise FileNotFoundError(f"config file not found: {found}")
        data = _read_yaml(found)
        sources["config_path"] = "flag"
    else:
        found = find_config_file(repo_root)
        if found is not None and found.exists():
            data = _read_yaml(found)
            sources["config_path"] = "file"
    config = DriftConfig.model_validate(_deep_merge(_defaults_dict(), data))
    for field in ("version", "llm", "logging", "scan", "check", "cache"):
        if field in data:
            sources[field] = "file"

    if profile is not None:
        if profile not in config.llm.profiles:
            raise ValueError(
                f"unknown profile {profile!r} "
                f"(have: {sorted(config.llm.profiles)})"
            )
        config.llm.default_profile = profile
        sources["llm.default_profile"] = "flag"
    elif os.environ.get("DRIFT_LLM_PROFILE"):
        name = os.environ["DRIFT_LLM_PROFILE"]
        if name not in config.llm.profiles:
            raise ValueError(f"DRIFT_LLM_PROFILE points at unknown profile {name!r}")
        config.llm.default_profile = name
        sources["llm.default_profile"] = "env"

    model_override = model
    if model_override:
        prof = config.llm.profiles[config.llm.default_profile]
        prof.model = model_override
        sources["llm.profiles.<default>.model"] = "flag"

    if log_level is not None:
        _require_level(log_level)
        config.logging.level = log_level  # type: ignore[assignment]
        sources["logging.level"] = "flag"
    elif os.environ.get("DRIFT_LOG_LEVEL"):
        _require_level(os.environ["DRIFT_LOG_LEVEL"])
        config.logging.level = os.environ["DRIFT_LOG_LEVEL"]  # type: ignore[assignment]
        sources["logging.level"] = "env"

    if log_format is not None:
        config.logging.console.format = log_format  # type: ignore[assignment]
        sources["logging.console.format"] = "flag"
    if quiet:
        config.logging.console.enabled = False
        sources["logging.console.enabled"] = "flag"

    set_active(config)
    return config, sources


def _require_level(level: str) -> None:
    if level not in LEVELS:
        raise ValueError(
            f"invalid log level {level!r} (want one of {sorted(LEVELS)})"
        )


def _defaults_dict() -> dict:
    from .models import DEFAULT_YAML

    import copy

    return copy.deepcopy(DEFAULT_YAML)


def _deep_merge(base: dict, override: dict) -> dict:
    merged = dict(base)
    for key, value in override.items():
        if (
            key in merged
            and isinstance(merged[key], dict)
            and isinstance(value, dict)
        ):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def resolve_profile(
    agent_id: str,
    *,
    profile_override: str | None = None,
    model_override: str | None = None,
) -> tuple[str, ProfileConfig]:
    """flag > DRIFT_LLM_PROFILE env > agents.<id> > default_profile."""
    config = get_active()
    if profile_override:
        name = profile_override
    elif os.environ.get("DRIFT_LLM_PROFILE"):
        name = os.environ["DRIFT_LLM_PROFILE"]
    else:
        name = config.llm.agents.get(
            normalize_agent_key(agent_id), config.llm.default_profile
        )
    if name not in config.llm.profiles:
        raise ValueError(f"unknown profile {name!r} for agent {agent_id}")
    profile = config.llm.profiles[name].model_copy(deep=True)
    if model_override:
        profile.model = model_override
    return name, profile


def redacted_view(config: DriftConfig) -> dict:
    """Resolved config for `config show`: key names plus set/unset, no values."""
    out = config.model_dump(mode="json")
    keys: dict[str, dict] = {}
    for name, prof in config.llm.profiles.items():
        keys[name] = {
            "api_key_env": prof.api_key_env,
            "api_key_set": bool(os.environ.get(prof.api_key_env)),
        }
        out["llm"]["profiles"][name].pop("extra_body", None)
    out["keys"] = keys
    return out
