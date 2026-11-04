"""RuleChecker: path, symbol, command checks on the fixture repo."""

from pathlib import Path

from driftwatcher.agents.non_llm.rule_checker import check
from driftwatcher.contracts.claims import Claim
from driftwatcher.contracts.verdicts import Verdict

FIXTURE = Path(__file__).parent / "fixtures" / "demo_repo"


def _claim(text: str, kind: str) -> Claim:
    return Claim(
        id=Claim.make_id("services/auth/SKILL.md", 1, text),
        doc_path="services/auth/SKILL.md",
        line=1,
        text=text,
        kind=kind,  # type: ignore[arg-type]
        feature="auth",
        refs=[text],
    )


def test_existing_symbol_supported() -> None:
    result = check(
        _claim("create_session", "symbol"),
        repo_root=str(FIXTURE),
        folder="services/auth",
    )
    assert isinstance(result, Verdict)
    assert result.verdict == "supported"
    assert result.evidence, "supported verdicts must cite file:line"


def test_missing_symbol_contradicted() -> None:
    result = check(
        _claim("no_such_symbol_xyz", "symbol"),
        repo_root=str(FIXTURE),
        folder="services/auth",
    )
    assert isinstance(result, Verdict)
    assert result.verdict == "contradicted"


def test_missing_path_contradicted() -> None:
    result = check(
        _claim("services/auth/missing.py", "path"), repo_root=str(FIXTURE)
    )
    assert isinstance(result, Verdict)
    assert result.verdict == "contradicted"


def test_existing_path_supported() -> None:
    result = check(
        _claim("services/auth/session.py", "path"), repo_root=str(FIXTURE)
    )
    assert isinstance(result, Verdict)
    assert result.verdict == "supported"


def test_existing_make_target_supported() -> None:
    result = check(_claim("make test-auth", "command"), repo_root=str(FIXTURE))
    assert isinstance(result, Verdict)
    assert result.verdict == "supported"


def test_missing_make_target_contradicted() -> None:
    result = check(_claim("make test-nope", "command"), repo_root=str(FIXTURE))
    assert isinstance(result, Verdict)
    assert result.verdict == "contradicted"


def test_behavior_claim_needs_judge() -> None:
    from driftwatcher.contracts.verdicts import NeedsJudge

    result = check(
        _claim("Sessions use a sliding expiry", "behavior"),
        repo_root=str(FIXTURE),
        folder="services/auth",
    )
    assert isinstance(result, NeedsJudge)
