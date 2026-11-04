"""RuleChecker symbol index: built once per repo, reused by every claim.

Regression test for slow `scan`: _symbol_exists used to re-walk and re-parse
the whole repo for every symbol claim (O(claims x files)). It must now serve
repeat lookups from a cached index with identical verdicts.
"""

from pathlib import Path

from driftwatcher.agents.non_llm import rule_checker
from driftwatcher.agents.non_llm.rule_checker import check
from driftwatcher.contracts.claims import Claim

FIXTURE = Path(__file__).parent / "fixtures" / "demo_repo"


def _symbol_claim(text: str) -> Claim:
    return Claim(
        id=Claim.make_id("services/auth/SKILL.md", 1, text),
        doc_path="services/auth/SKILL.md",
        line=1,
        text=text,
        kind="symbol",  # type: ignore[arg-type]
        feature="auth",
        refs=[text],
    )


def test_symbol_index_reused_across_checks() -> None:
    rule_checker.clear_symbol_index()
    first = check(_symbol_claim("create_session"), repo_root=str(FIXTURE))
    assert rule_checker._INDEX_CACHE, "index should be built on first symbol check"
    entries_before = len(rule_checker._INDEX_CACHE)
    second = check(_symbol_claim("create_session"), repo_root=str(FIXTURE))
    assert len(rule_checker._INDEX_CACHE) == entries_before
    assert second.verdict == first.verdict == "supported"
    assert [e.file for e in second.evidence] == [e.file for e in first.evidence]


def test_missing_symbol_still_contradicted() -> None:
    rule_checker.clear_symbol_index()
    result = check(_symbol_claim("no_such_symbol_xyz"), repo_root=str(FIXTURE))
    assert result.verdict == "contradicted"
