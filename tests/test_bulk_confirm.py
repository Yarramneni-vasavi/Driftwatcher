"""Bulk duplicate review: one table, one answer line, per-row overrides."""

from driftwatcher.agents.non_llm.user_prompter import (
    BulkRow,
    _parse_bulk,
    ask_bulk,
)
from driftwatcher.orchestrator.onboard import _auto_primary, _name_key


def _rows() -> list[BulkRow]:
    return [
        BulkRow(feature="f1", options=["a.md", "b.md"], confidences=(0.7, 0.5)),
        BulkRow(
            feature="f2", options=["c.md", "d.md", "e.md"], suggested=1,
            confidences=(0.4, 0.6, 0.5),
        ),
    ]


def test_empty_and_accept_words_accept_all() -> None:
    assert _parse_bulk("", _rows()) == {}
    assert _parse_bulk("all", _rows()) == {}
    assert _parse_bulk("accept all", _rows()) == {}


def test_row_equals_choice_overrides() -> None:
    assert _parse_bulk("1=2", _rows()) == {"f1": "b.md"}
    assert _parse_bulk("2=3, 1=1", _rows()) == {"f2": "e.md", "f1": "a.md"}


def test_last_token_wins_for_same_row() -> None:
    assert _parse_bulk("1=1, 1=2", _rows()) == {"f1": "b.md"}


def test_ask_bulk_reprompts_on_bad_token(monkeypatch, capsys) -> None:
    answers = iter(["9=9", "bogus", ""])
    monkeypatch.setattr("builtins.input", lambda *a, **k: next(answers))
    assert ask_bulk(_rows()) == {}
    out = capsys.readouterr().out
    assert "bad token '9=9'" in out
    assert "bad token 'bogus'" in out


def test_ask_bulk_non_interactive_default() -> None:
    assert ask_bulk(_rows(), non_interactive_default="2=1") == {"f2": "c.md"}


def test_name_key_normalizes() -> None:
    assert _name_key("Static Analysis Engine") == "static_analysis_engine"
    assert _name_key("static-analysis_engine") == "static_analysis_engine"


def test_auto_primary_prefers_same_name_file() -> None:
    matches = [("docs/architecture.md", 0.9), ("Static_Analysis_Engine.md", 0.4)]
    assert _auto_primary("Static Analysis Engine", matches) == (
        "Static_Analysis_Engine.md"
    )


def test_auto_primary_prefers_clear_confidence_leader() -> None:
    matches = [("a.md", 0.9), ("b.md", 0.5)]
    assert _auto_primary("Something Else", matches) == "a.md"


def test_auto_primary_none_on_close_call() -> None:
    matches = [("a.md", 0.7), ("b.md", 0.6)]
    assert _auto_primary("Something Else", matches) is None
