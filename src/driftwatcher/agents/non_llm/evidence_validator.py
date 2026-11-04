"""N8 EvidenceValidator: every cited file:line must exist in provided context."""

from __future__ import annotations

from pathlib import Path

from ...contracts.claims import CodeContext
from ...contracts.envelope import Envelope
from ...observability.decorators import logged_step
from ...contracts.verdicts import Verdict

AGENT_ID = "N8.EvidenceValidator"


def validate(
    verdict: Verdict, context: CodeContext, repo_root: str | Path = "."
) -> Verdict | None:
    if verdict.verdict in ("supported", "contradicted"):
        if not verdict.evidence:
            verdict.verdict = "unverifiable"
            verdict.reason += " (no evidence)"
            return verdict
        allowed: set[tuple[str, int]] = set()
        for snippet in context.snippets:
            for lineno in range(snippet.start, snippet.end + 1):
                allowed.add((snippet.file, lineno))
        for ev in verdict.evidence:
            if (ev.file, ev.line) not in allowed:
                return None
            candidate = Path(repo_root) / ev.file
            if not candidate.exists():
                return None
    return verdict


@logged_step(AGENT_ID)
def handle(env: Envelope[Verdict]) -> Envelope[Verdict]:
    # model_construct(): no validation, so required claim_id/tier can't
    # mask a real payload problem the way a bare Verdict() used to.
    verdict = (
        env.payload
        if isinstance(env.payload, Verdict)
        else Verdict.model_construct()
    )
    return Envelope[Verdict](
        correlation_id=env.correlation_id,
        type="Verdict",
        sender=AGENT_ID,
        recipient=env.sender or "Orchestrator",
        payload=verdict,
    )
