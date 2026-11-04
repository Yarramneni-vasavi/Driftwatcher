"""OpenAI-compatible provider: Baseten, Meta Model API, GPT, others.

Uses the `openai` library. SDK-level retries cover timeouts, 429, and
5xx up to the profile's `max_retries`; there is no second retry loop on
top (plan sec. 6.7).
"""

from __future__ import annotations

import os
from time import perf_counter

from ...config.models import ProfileConfig
from ..registry import register_provider
from ..types import Capabilities, LLMRequest, LLMResponse, Usage


class MissingKeyError(RuntimeError):
    pass


def _is_bad_request(exc: Exception) -> bool:
    name = type(exc).__name__
    if name in ("BadRequestError", "UnprocessableEntityError"):
        return True
    status = getattr(exc, "status_code", None)
    return status == 400


@register_provider("openai_compatible")
class OpenAICompatibleProvider:
    capabilities = Capabilities(
        json_schema=True, json_object=True, reasoning_effort=True
    )

    def __init__(self, profile: ProfileConfig) -> None:
        from openai import OpenAI

        self.profile = profile
        key = os.environ.get(profile.api_key_env, "")
        if not key:
            raise MissingKeyError(
                f"{profile.api_key_env} is not set: add it to .env"
            )
        base_url = (
            os.environ.get(profile.base_url_env or "") or profile.base_url
        )
        self.client = OpenAI(
            api_key=key,
            base_url=base_url,
            max_retries=profile.max_retries,
            timeout=profile.timeout_s,
        )

    def complete(self, req: LLMRequest) -> LLMResponse:
        from openai import APIStatusError

        kwargs: dict = {}
        if req.mode == "json_schema":
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "reply",
                    "schema": req.response_schema,
                    "strict": True,
                },
            }
        elif req.mode == "json_object":
            kwargs["response_format"] = {"type": "json_object"}
        effort = req.reasoning_effort or self.profile.reasoning_effort
        if effort and self.capabilities.reasoning_effort:
            kwargs["reasoning_effort"] = effort
        if req.max_output_tokens:
            kwargs["max_completion_tokens"] = req.max_output_tokens
        if self.profile.extra_body:
            kwargs["extra_body"] = self.profile.extra_body
        t0 = perf_counter()
        try:
            r = self.client.chat.completions.create(
                model=self.profile.model,
                temperature=req.temperature,
                messages=[
                    {"role": "system", "content": req.system},
                    {"role": "user", "content": req.user_json},
                ],
                **kwargs,
            )
        except APIStatusError as exc:
            if _is_bad_request(exc) and req.mode != "prompt_only":
                from ..types import ResponseFormatRejected

                raise ResponseFormatRejected(str(exc)) from exc
            raise
        latency_ms = int((perf_counter() - t0) * 1000)
        return to_llm_response(r, self.profile, latency_ms)


def to_llm_response(
    r: object, profile: ProfileConfig, latency_ms: int
) -> LLMResponse:
    choice = r.choices[0]  # type: ignore[attr-defined]
    content = choice.message.content
    if content is None:
        content = ""
    if not isinstance(content, str):
        parts = [
            p.text for p in content
            if getattr(p, "type", "") == "text" and getattr(p, "text", None)
        ]
        content = "\n".join(parts)
    usage = getattr(r, "usage", None)
    return LLMResponse(
        text=content,
        provider="openai_compatible",
        model=getattr(r, "model", profile.model),
        usage=Usage(
            input_tokens=getattr(usage, "prompt_tokens", None),
            output_tokens=getattr(usage, "completion_tokens", None),
        ),
        latency_ms=latency_ms,
        response_id=getattr(r, "id", None),
        finish_reason=getattr(choice, "finish_reason", None),
    )
