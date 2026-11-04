"""Provider registry: @register_provider + dotted-path plug-ins.

`profile.provider` is either a registered name (`openai_compatible`) or
a dotted path (`my_pkg.my_module:MyProvider`) imported on demand, so a
custom provider needs no core-code change (plan sec. 6.2, 6.6).
Instances are cached per resolved profile.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...config.models import ProfileConfig
    from .providers.base import LLMProvider

_PROVIDERS: dict[str, type[LLMProvider]] = {}
_INSTANCES: dict[str, LLMProvider] = {}

_BUILTIN_MODULES = {
    "openai_compatible": "driftwatcher.llm.providers.openai_compatible",
    "anthropic": "driftwatcher.llm.providers.anthropic",
    "mock": "driftwatcher.llm.providers.mock",
}


def register_provider(name: str):  # noqa: ANN001, ANN202
    def deco(cls):  # noqa: ANN001, ANN202
        _PROVIDERS[name] = cls
        return cls

    return deco


def _load_dotted(path: str) -> type[LLMProvider]:
    if ":" in path:
        module_name, _, attr = path.partition(":")
    else:
        module_name, _, attr = path.rpartition(".")
    module = importlib.import_module(module_name)
    cls = getattr(module, attr)
    if not hasattr(cls, "complete"):
        raise ValueError(f"{path} does not implement LLMProvider.complete()")
    return cls


def _resolve_class(provider: str) -> type[LLMProvider]:
    if provider in _PROVIDERS:
        return _PROVIDERS[provider]
    if provider in _BUILTIN_MODULES:
        importlib.import_module(_BUILTIN_MODULES[provider])
        if provider in _PROVIDERS:
            return _PROVIDERS[provider]
    if "." in provider or ":" in provider:
        return _load_dotted(provider)
    raise ValueError(f"unknown LLM provider: {provider}")


def get(profile: ProfileConfig) -> LLMProvider:
    key = profile.model_dump_json()
    cached = _INSTANCES.get(key)
    if cached is not None:
        return cached
    instance = _resolve_class(profile.provider)(profile)
    _INSTANCES[key] = instance
    return instance


def clear_cache() -> None:
    _INSTANCES.clear()
