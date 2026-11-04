"""L5 SkillAuthor: draft a new SKILL.md for a feature with no doc."""

from __future__ import annotations

from ...contracts.envelope import Envelope
from ...contracts.fixes import AuthorRequest, DocDraft
from .base_llm_agent import run_llm

AGENT_ID = "L5.SkillAuthor"


def handle(env: Envelope[AuthorRequest]) -> Envelope:
    req = (
        env.payload
        if isinstance(env.payload, AuthorRequest)
        else AuthorRequest()
    )
    return run_llm(
        AGENT_ID, "skill_author.txt", req, DocDraft,
        env.sender or "Orchestrator", env.correlation_id,
    )
