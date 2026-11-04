"""L1 FeatureScout: propose feature folders (plan sec. 2, 5.3)."""

from __future__ import annotations

from ...contracts.envelope import Envelope
from ...contracts.features import FeatureScoutRequest, FeatureProposal
from .base_llm_agent import run_llm

AGENT_ID = "L1.FeatureScout"


def handle(env: Envelope[FeatureScoutRequest]) -> Envelope:
    req = (
        env.payload
        if isinstance(env.payload, FeatureScoutRequest)
        else FeatureScoutRequest()
    )
    return run_llm(
        AGENT_ID, "feature_scout.txt", req, FeatureProposal,
        env.sender or "Orchestrator", env.correlation_id,
    )
