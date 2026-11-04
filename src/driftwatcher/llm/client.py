"""Vendor-neutral LLM client (architecture sec. 11, plan sec. 5.2/6).

Resolves the profile for an agent, calls a provider, validates the
reply against the expected payload type, retries once with the
validation errors, and tracks a per-run call budget. Emits the
`llm_call` event so provider/model changes are visible in logs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from ..config.loader import get_active, resolve_profile
from ..observability.logger import active_budget, get_logger
from . import registry
from .budget import Budget, BudgetExceeded, estimate_tokens
from .types import (
    CallMeta,
    LLMRequest,
    LLMResponse,
    ResponseFormatRejected,
    StructuredMode,
)

T = TypeVar("T", bound=BaseModel)

LADDER: list[StructuredMode] = ["json_schema", "json_object", "prompt_only"]
_downgraded_mode: StructuredMode | None = None


def _prompt_path(name: str) -> Path:
    return Path(__file__).parent / "prompts" / name


def load_prompt(name: str) -> str:
    return _prompt_path(name).read_text(encoding="utf-8").strip()


def _request_json(request: BaseModel, schema: dict, mode: StructuredMode) -> str:
    if mode == "json_schema":
        return request.model_dump_json()
    return json.dumps(
        {"request": request.model_dump(mode="json"), "reply_schema": schema}
    )


def call(
    agent_id: str,
    prompt: str,
    request: BaseModel,
    out_type: type[T],
    *,
    profile_name: str | None = None,
    model_override: str | None = None,
    budget: Budget | None = None,
    meta: CallMeta | None = None,
) -> T:
    global _downgraded_mode
    config = get_active()
    name, profile = resolve_profile(
        agent_id, profile_override=profile_name, model_override=model_override
    )
    provider = registry.get(profile)
    schema = out_type.model_json_schema()
    active = budget or active_budget()
    call_meta = meta or CallMeta(agent_id=agent_id)

    mode: StructuredMode = (
        _downgraded_mode or profile.structured_output or "json_schema"
    )
    user_json = _request_json(request, schema, mode)
    if active is not None:
        active.check(estimate_tokens(len(user_json)))

    req = LLMRequest(
        system=prompt,
        user_json=user_json,
        response_schema=schema,
        mode=mode,
        temperature=config.llm.call.temperature,
        max_output_tokens=config.llm.call.max_output_tokens,
        reasoning_effort=config.llm.call.reasoning_effort,
        meta=call_meta,
    )
    try:
        resp = provider.complete(req)
    except ResponseFormatRejected as exc:
        mode = _downgrade(mode, name, str(exc))
        req = req.model_copy(
            update={
                "mode": mode,
                "user_json": _request_json(request, schema, mode),
            }
        )
        resp = provider.complete(req)
    truncated = resp.finish_reason == "length"
    _log_call(name, profile, req, resp, attempt=1, validated=not truncated)
    try:
        if truncated:
            raise ValueError(
                "LLM reply truncated at the output limit "
                "(finish_reason=length): raise max_output_tokens and re-run"
            )
        return _validate(resp.text, out_type)
    except (ValidationError, ValueError) as first_err:
        retry_prompt = load_prompt("retry.txt")
        retry_req = LLMRequest(
            system=retry_prompt,
            user_json=json.dumps({"errors": str(first_err)}),
            response_schema=schema,
            mode=mode,
            temperature=config.llm.call.temperature,
            max_output_tokens=config.llm.call.max_output_tokens,
            reasoning_effort=config.llm.call.reasoning_effort,
            meta=call_meta,
        )
        resp2 = provider.complete(retry_req)
        truncated2 = resp2.finish_reason == "length"
        _log_call(
            name, profile, retry_req, resp2, attempt=2,
            validated=not truncated2,
        )
        try:
            if truncated2:
                raise ValueError(
                    "LLM reply truncated at the output limit "
                    "(finish_reason=length): raise max_output_tokens and re-run"
                )
            return _validate(resp2.text, out_type)
        except (ValidationError, ValueError) as second_err:
            _log_call(
                name, profile, retry_req, resp2, attempt=2, validated=False
            )
            raise second_err


def _downgrade(
    mode: StructuredMode, profile_name: str, detail: str
) -> StructuredMode:
    global _downgraded_mode
    nxt = LADDER[min(LADDER.index(mode) + 1, len(LADDER) - 1)]
    _downgraded_mode = nxt
    logger = get_logger()
    if logger is not None:
        logger.warning(
            "LLM",
            f"structured output downgraded {mode} -> {nxt} "
            f"(profile={profile_name}): {detail[:160]}",
        )
    return nxt


def reset_ladder() -> None:
    global _downgraded_mode
    _downgraded_mode = None


def _validate(text: str, out_type: type[T]) -> T:
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM reply is not JSON: {text[:160]}") from exc
    if not isinstance(raw, dict):
        raise ValueError(
            f"LLM reply must be a JSON object, got {type(raw).__name__}"
        )
    return out_type.model_validate(raw)


def _log_call(
    profile_name: str,
    profile: object,
    req: LLMRequest,
    resp: LLMResponse,
    attempt: int,
    validated: bool,
) -> None:
    logger = get_logger()
    if logger is None:
        return
    model = getattr(profile, "model", "?")
    usage = resp.usage
    tokens = ""
    if usage.input_tokens is not None or usage.output_tokens is not None:
        tokens = f"in={usage.input_tokens} out={usage.output_tokens} tokens "
    logger.llm_call(
        f"profile={profile_name} model={model} mode={req.mode} "
        f"attempt={attempt} {tokens}{resp.latency_ms / 1000:.1f}s "
        f"validated={validated}",
    )
    logger.llm_call(
        "excerpts",
        trace={
            "request": req.user_json[:500],
            "reply": resp.text[:500],
        },
    )


class PingRequest(BaseModel):
    ping: str = "hello"


class PingResult(BaseModel):
    ok: bool = True


def ping(profile_name: str | None = None) -> dict:
    """One tiny structured call to test a provider profile (plan sec. 7.2)."""
    name, profile = resolve_profile("llm.ping", profile_override=profile_name)
    provider = registry.get(profile)
    schema = PingResult.model_json_schema()
    mode: StructuredMode = profile.structured_output or "json_schema"
    req = LLMRequest(
        system="Reply with exactly the JSON the schema asks for.",
        user_json=json.dumps({"request": {"ping": "hello"}, "reply_schema": schema}),
        response_schema=schema,
        mode=mode,
        temperature=0,
        meta=CallMeta(agent_id="llm.ping"),
    )
    try:
        resp = provider.complete(req)
    except ResponseFormatRejected:
        mode = LADDER[min(LADDER.index(mode) + 1, len(LADDER) - 1)]
        req = req.model_copy(update={"mode": mode})
        resp = provider.complete(req)
    result = _validate(resp.text, PingResult)
    return {
        "ok": result.ok,
        "provider": resp.provider,
        "model": resp.model,
        "latency_ms": resp.latency_ms,
        "mode": mode,
    }


__all__ = [
    "BudgetExceeded",
    "PingRequest",
    "PingResult",
    "call",
    "load_prompt",
    "ping",
    "reset_ladder",
]
