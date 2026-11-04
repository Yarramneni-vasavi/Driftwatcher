"""L3 ClaimExtractor: behavior/convention claims rules cannot find."""

from __future__ import annotations

from ...contracts.claims import ClaimExtractRequest, ClaimSet
from ...contracts.envelope import Envelope
from .base_llm_agent import run_llm

AGENT_ID = "L3.ClaimExtractor"


def handle(env: Envelope[ClaimExtractRequest]) -> Envelope:
    req = (
        env.payload
        if isinstance(env.payload, ClaimExtractRequest)
        else ClaimExtractRequest()
    )
    return run_llm(
        AGENT_ID, "claim_extractor.txt", req, ClaimSet,
        env.sender or "Orchestrator", env.correlation_id,
    )
