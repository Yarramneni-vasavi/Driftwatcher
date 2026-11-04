"""Claude provider stub (plan sec. 6.3: stub now, implement later)."""

from __future__ import annotations

from ...config.models import ProfileConfig
from ..registry import register_provider
from ..types import Capabilities, LLMRequest, LLMResponse


@register_provider("anthropic")
class AnthropicProvider:
    capabilities = Capabilities(
        json_schema=False, json_object=False, reasoning_effort=False
    )

    def __init__(self, profile: ProfileConfig) -> None:
        self.profile = profile

    def complete(self, req: LLMRequest) -> LLMResponse:
        raise NotImplementedError(
            "anthropic provider is a stub: implement complete() to use it"
        )
