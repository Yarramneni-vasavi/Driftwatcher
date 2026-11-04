"""RuleClaimExtractor drops noise tokens, keeps real claims with same kinds."""

from driftwatcher.agents.non_llm.rule_claims import extract
from driftwatcher.contracts.claims import DocText


def _kinds(line: str) -> list[tuple[str, str]]:
    claims = extract(DocText(doc_path="d.md", lines=[line])).claims
    return [(c.kind, c.text) for c in claims]


def test_skips_prose_with_spaces() -> None:
    assert _kinds("The `API Service` and `Output Generation Engine`.") == []


def test_skips_placeholders() -> None:
    assert _kinds("Use `feat/...` or `fix/...` branches.") == []
    assert _kinds("Clone `<repo>` into `[dir]`.") == []


def test_skips_dotfiles_and_tool_names() -> None:
    assert _kinds("Copy `.env` to `.env.example`.") == []
    assert _kinds("Install `npm` and run `pytest`.") == []


def test_skips_non_identifier_symbols() -> None:
    assert _kinds("See `agents.agent:Agent` for details.") == []


def test_keeps_real_claims_with_same_kinds() -> None:
    assert _kinds("Use `MetaAgent` to begin.") == [("symbol", "MetaAgent")]
    assert _kinds("See `repo_utils.clone_repository` here.") == [
        ("symbol", "repo_utils.clone_repository")
    ]
    assert _kinds("Open `services/auth/session.py`.") == [
        ("path", "services/auth/session.py")
    ]
    assert _kinds("Pass `--verbose` for debug.") == [("command", "--verbose")]


def test_make_command_still_found_in_prose() -> None:
    assert _kinds("Run `make test` first.") == [("command", "make test")]
