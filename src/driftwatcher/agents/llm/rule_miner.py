"""L7 RuleMiner: business rules from code, then coverage against docs."""

from __future__ import annotations

from ...contracts.envelope import Envelope
from ...contracts.rules import (
    FlowSummarizeRequest,
    FlowSummary,
    MissingCheckRequest,
    MissingCheckResult,
    RuleExtractRequest,
    RuleJudgeRequest,
    RuleSelectRequest,
    RuleSet,
    SelectedFunctions,
)
from ...contracts.features import DocMatch
from .base_llm_agent import run_llm

AGENT_ID = "L7.RuleMiner"


def select(
    req: RuleSelectRequest, recipient: str, correlation_id: str
) -> Envelope:
    if not req.outline.strip():
        req = req.model_copy(update={"outline": "(empty outline)"})
    return run_llm(
        AGENT_ID, "rule_select.txt", req, SelectedFunctions,
        recipient, correlation_id,
    )


def extract(
    req: RuleExtractRequest, recipient: str, correlation_id: str
) -> Envelope:
    return run_llm(
        AGENT_ID, "rule_extract.txt", req, RuleSet,
        recipient, correlation_id,
    )


def judge(
    req: RuleJudgeRequest, recipient: str, correlation_id: str
) -> Envelope:
    return run_llm(
        AGENT_ID, "rule_judge.txt", req, DocMatch,
        recipient, correlation_id,
    )


def summarize_flow(
    req: FlowSummarizeRequest, recipient: str, correlation_id: str
) -> Envelope:
    """B4: one structured call per entry point. No validation here;
    the orchestrator runs N8 line validation on the payload."""
    return run_llm(
        AGENT_ID, "flow_summarize.txt", req, FlowSummary,
        recipient, correlation_id,
    )


def check_missing(
    req: MissingCheckRequest, recipient: str, correlation_id: str
) -> Envelope:
    """B6 second pass: batched whole-doc coverage check (~15 rules)."""
    return run_llm(
        AGENT_ID, "flow_missing.txt", req, MissingCheckResult,
        recipient, correlation_id,
    )
