"""Mock provider: canned replies for unit tests (plan sec. 6.3).

Tests enqueue reply texts (JSON strings or objects); each `complete()`
pops the next one. `reject_modes` simulates endpoints that reject a
structured-output mode with a 400-type error.
"""

from __future__ import annotations

import json
from time import perf_counter

from ...config.models import ProfileConfig
from ..registry import register_provider
from ..types import (
    Capabilities,
    LLMRequest,
    LLMResponse,
    ResponseFormatRejected,
    Usage,
)


@register_provider("mock")
class MockProvider:
    capabilities = Capabilities(json_schema=True, json_object=True)

    replies: list[str] = []
    reject_modes: set[str] = set()

    def __init__(self, profile: ProfileConfig) -> None:
        self.profile = profile
        self.calls: list[LLMRequest] = []

    def complete(self, req: LLMRequest) -> LLMResponse:
        t0 = perf_counter()
        self.calls.append(req)
        if req.mode in MockProvider.reject_modes:
            raise ResponseFormatRejected(
                f"mock endpoint rejects mode {req.mode}"
            )
        if not MockProvider.replies:
            raise RuntimeError("mock provider has no canned replies left")
        text = MockProvider.replies.pop(0)
        if not isinstance(text, str):
            text = json.dumps(text)
        return LLMResponse(
            text=text,
            provider="mock",
            model=self.profile.model,
            usage=Usage(input_tokens=len(req.user_json) // 4, output_tokens=1),
            latency_ms=int((perf_counter() - t0) * 1000),
            response_id="mock-1",
        )

    @classmethod
    def enqueue(cls, reply: str | dict) -> None:
        cls.replies.append(reply if isinstance(reply, str) else json.dumps(reply))

    @classmethod
    def reset(cls) -> None:
        cls.replies = []
        cls.reject_modes = set()
