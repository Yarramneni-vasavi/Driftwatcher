"""EvidenceValidator rejects citations not in the provided snippets."""

from driftwatcher.agents.non_llm.evidence_validator import validate
from driftwatcher.contracts.claims import CodeContext, CodeSnippet
from driftwatcher.contracts.verdicts import Evidence, Verdict


def _ctx() -> CodeContext:
    return CodeContext(
        claim_id="c1",
        snippets=[
            CodeSnippet(
                file="services/auth/session.py",
                start=1,
                end=6,
                text="session_expiry = 'sliding'",
            )
        ],
    )


def test_accepts_citation_inside_context(tmp_path) -> None:
    target = tmp_path / "services" / "auth"
    target.mkdir(parents=True)
    (target / "session.py").write_text("x = 1\n")
    ctx = CodeContext(
        claim_id="c1",
        snippets=[
            CodeSnippet(file="services/auth/session.py", start=1, end=1, text="x = 1")
        ],
    )
    verdict = Verdict(
        claim_id="c1", verdict="supported",
        evidence=[Evidence(file="services/auth/session.py", line=1)],
        tier="deterministic",
    )
    assert validate(verdict, ctx, tmp_path) is not None


def test_rejects_citation_outside_context(tmp_path) -> None:
    verdict = Verdict(
        claim_id="c1", verdict="supported",
        evidence=[Evidence(file="services/auth/other.py", line=99)],
        tier="deterministic",
    )
    assert validate(verdict, _ctx(), tmp_path) is None


def test_empty_evidence_becomes_unverifiable(tmp_path) -> None:
    verdict = Verdict(
        claim_id="c1", verdict="supported", evidence=[],
        tier="deterministic",
    )
    out = validate(verdict, _ctx(), tmp_path)
    assert out is not None
    assert out.verdict == "unverifiable"
