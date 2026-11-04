"""Process docs never become context files."""

from driftwatcher.agents.non_llm.context_scanner import _denied


def test_contributing_and_conduct_denied() -> None:
    assert _denied("CONTRIBUTING.md", [])
    assert _denied("docs/CONTRIBUTING.md", [])
    assert _denied("CODE_OF_CONDUCT.md", [])


def test_feature_docs_allowed() -> None:
    assert not _denied(".codeboarding/API_Service.md", [])
    assert not _denied("README.md", [])
