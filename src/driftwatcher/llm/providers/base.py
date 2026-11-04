"""LLMProvider protocol (plan sec. 6.2)."""

from __future__ import annotations

from typing import Protocol

from ...config.models import ProfileConfig
from ..types import Capabilities, LLMRequest, LLMResponse


class LLMProvider(Protocol):
    capabilities: Capabilities

    def __init__(self, profile: ProfileConfig) -> None: ...

    def complete(self, req: LLMRequest) -> LLMResponse: ...
