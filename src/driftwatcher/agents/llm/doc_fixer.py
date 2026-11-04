"""L6 DocFixer: propose a doc-only diff for contradicted claims."""

from __future__ import annotations

from ...contracts.envelope import Envelope
from ...contracts.fixes import FixProposal, FixRequest
from .base_llm_agent import run_llm

AGENT_ID = "L6.DocFixer"


def handle(env: Envelope[FixRequest]) -> Envelope:
    req = env.payload if isinstance(env.payload, FixRequest) else FixRequest()
    return run_llm(
        AGENT_ID, "doc_fixer.txt", req, FixProposal,
        env.sender or "Orchestrator", env.correlation_id,
    )
