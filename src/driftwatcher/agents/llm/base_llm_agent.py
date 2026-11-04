"""Shared base for LLM agents: prompt + JSON request + schema validation."""

from __future__ import annotations

from time import perf_counter

from pydantic import BaseModel

from ...contracts.envelope import Envelope, ErrorInfo
from ...llm import client
from ...observability.logger import get_logger
from ...observability.summarize import summarize


def run_llm(
    agent_id: str,
    prompt_file: str,
    request: BaseModel,
    out_type: type[BaseModel],
    recipient: str,
    correlation_id: str,
) -> Envelope:
    from ...llm.types import CallMeta

    logger = get_logger()
    if logger is not None:
        logger.step_start(agent_id, summarize(request))
    t0 = perf_counter()
    try:
        prompt = client.load_prompt(prompt_file)
        out = client.call(
            agent_id,
            prompt,
            request,
            out_type,
            meta=CallMeta(agent_id=agent_id, correlation_id=correlation_id),
        )
        if logger is not None:
            logger.step_end(
                agent_id,
                summarize(out),
                int((perf_counter() - t0) * 1000),
            )
        return Envelope(
            correlation_id=correlation_id,
            type=out_type.__name__,
            sender=agent_id,
            recipient=recipient,
            payload=out,
        )
    except Exception as exc:  # noqa: BLE001 - surfaced as envelope error
        if logger is not None:
            logger.step_error(
                agent_id, exc, int((perf_counter() - t0) * 1000)
            )
        # model_construct(): no validation, so schemas with required fields
        # can't mask the real error with a ValidationError.
        return Envelope(
            correlation_id=correlation_id,
            type=out_type.__name__,
            sender=agent_id,
            recipient=recipient,
            payload=out_type.model_construct(),
            error=ErrorInfo(
                code="llm_error", message=str(exc)[:500], detail=agent_id
            ),
        )
