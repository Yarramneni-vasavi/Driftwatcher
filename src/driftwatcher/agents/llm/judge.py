"""L4 Judge: judge one claim against code (plan sec. 5.3)."""

from __future__ import annotations

from ...contracts.claims import JudgeRequest
from ...contracts.envelope import Envelope
from ...contracts.verdicts import Verdict
from .base_llm_agent import run_llm

AGENT_ID = "L4.Judge"


def handle(env: Envelope[JudgeRequest]) -> Envelope:
    from ...contracts.claims import Claim

    req = (
        env.payload
        if isinstance(env.payload, JudgeRequest)
        else JudgeRequest(claim=Claim())
    )
    return run_llm(
        AGENT_ID, "judge.txt", req, Verdict,
        env.sender or "Orchestrator", env.correlation_id,
    )
