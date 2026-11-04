"""L2 DocMapper: decide if a doc genuinely explains a feature, with quote."""

from __future__ import annotations

from ...contracts.envelope import Envelope
from ...contracts.features import DocMapRequest, DocMatch
from .base_llm_agent import run_llm

AGENT_ID = "L2.DocMapper"


def force_no_match_without_quote(match: DocMatch) -> DocMatch:
    if not match.quote.strip():
        match.match = False
    return match


def handle(env: Envelope[DocMapRequest]) -> Envelope:
    req = (
        env.payload
        if isinstance(env.payload, DocMapRequest)
        else DocMapRequest(feature_name="", feature_folder="")
    )
    out = run_llm(
        AGENT_ID, "doc_mapper.txt", req, DocMatch,
        env.sender or "Orchestrator", env.correlation_id,
    )
    if out.error is None and isinstance(out.payload, DocMatch):
        out.payload = force_no_match_without_quote(out.payload)
    return out
