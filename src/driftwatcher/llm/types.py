"""Normalized LLM types (plan sec. 6.1).

Agents and the client only see these types, never a vendor response
object.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

StructuredMode = Literal["json_schema", "json_object", "prompt_only"]


class CallMeta(BaseModel):
    """For logging only, never sent to the model."""

    agent_id: str = ""
    correlation_id: str | None = None
    claim_id: str | None = None
    feature: str | None = None


class LLMRequest(BaseModel):
    system: str = ""
    user_json: str = ""
    response_schema: dict | None = None
    mode: StructuredMode = "json_schema"
    temperature: float = 0
    max_output_tokens: int | None = None
    reasoning_effort: str | None = None
    meta: CallMeta = Field(default_factory=CallMeta)


class Usage(BaseModel):
    input_tokens: int | None = None
    output_tokens: int | None = None


class LLMResponse(BaseModel):
    text: str = ""
    provider: str = ""
    model: str = ""
    usage: Usage = Field(default_factory=Usage)
    latency_ms: int = 0
    response_id: str | None = None
    finish_reason: str | None = None


class Capabilities(BaseModel):
    json_schema: bool = False
    json_object: bool = False
    reasoning_effort: bool = False


class ResponseFormatRejected(Exception):
    """Endpoint rejected the structured-output parameter (retry lower)."""
