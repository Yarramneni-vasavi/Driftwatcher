"""load_dotenv_file fills os.environ from .env without overriding real env."""

import os

from driftwatcher.config.loader import load_dotenv_file


def test_loads_quoted_values_and_skips_noise(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("DRIFTWATCH_TEST_KEY", raising=False)
    monkeypatch.delenv("DRIFTWATCH_TEST_OTHER", raising=False)
    f = tmp_path / ".env"
    f.write_text(
        "# comment\n"
        'DRIFTWATCH_TEST_KEY="hello"\n'
        "DRIFTWATCH_TEST_OTHER=plain\n"
        "NOT_A_PAIR\n"
        "1BAD=oops\n"
    )
    assert load_dotenv_file(f) == 2
    assert os.environ["DRIFTWATCH_TEST_KEY"] == "hello"
    assert os.environ["DRIFTWATCH_TEST_OTHER"] == "plain"
    assert "NOT_A_PAIR" not in os.environ


def test_does_not_override_real_env(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DRIFTWATCH_TEST_KEY", "real")
    f = tmp_path / ".env"
    f.write_text("DRIFTWATCH_TEST_KEY=fromfile\n")
    assert load_dotenv_file(f) == 0
    assert os.environ["DRIFTWATCH_TEST_KEY"] == "real"


def test_missing_file_is_zero(tmp_path) -> None:
    assert load_dotenv_file(tmp_path / "nope.env") == 0
