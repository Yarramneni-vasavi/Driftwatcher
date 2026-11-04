"""Scan emits per-document progress events (no more silent long runs)."""

from types import SimpleNamespace

from driftwatcher.cli import main as cli_main
from driftwatcher.contracts.verdicts import Evidence, Verdict


class _FakeLogger:
    def __init__(self) -> None:
        self.events: list[tuple] = []

    def step_start(self, agent, params=None) -> None:
        self.events.append(("start", agent, params))

    def step_end(self, agent, result=None, *args) -> None:
        self.events.append(("end", agent, result))

    def step_skip(self, agent, reason) -> None:
        self.events.append(("skip", agent, reason))

    def run_end(self, message) -> None:
        self.events.append(("run_end", message))


def _stub_setup(monkeypatch, logger):
    monkeypatch.setattr(
        cli_main, "_setup", lambda *args, **kwargs: (None, "run-test", logger)
    )
    monkeypatch.setattr(
        cli_main.config_loader,
        "get_active",
        lambda: SimpleNamespace(
            scan=SimpleNamespace(deny_globs=[], known_context_names=[])
        ),
    )


def test_scan_logs_each_document(monkeypatch, tmp_path, capsys) -> None:
    logger = _FakeLogger()
    _stub_setup(monkeypatch, logger)
    (tmp_path / "doc.md").write_text("Use `create_session` to begin.\n")
    inv = SimpleNamespace(files=[SimpleNamespace(path="doc.md")])
    monkeypatch.setattr(
        cli_main.context_scanner, "scan", lambda *args, **kwargs: inv
    )
    monkeypatch.setattr(
        cli_main.rule_checker,
        "check",
        lambda claim, repo_root=".", folder="": Verdict(
            claim_id=claim.id,
            verdict="supported",
            evidence=[Evidence(file="x.py", line=1)],
            reason="ok",
            tier="deterministic",
        ),
    )
    cli_main.scan(repo=str(tmp_path))
    out = capsys.readouterr().out
    assert "Found 1 context files." in out
    starts = [e for e in logger.events if e[0] == "start"]
    ends = [e for e in logger.events if e[0] == "end"]
    assert len(starts) == 1 and starts[0][2]["doc"] == "doc.md"
    assert starts[0][2] == {"doc": "doc.md", "index": 1, "total": 1}
    assert len(ends) == 1 and ends[0][2] == {"doc": "doc.md", "claims": 1}


def test_scan_logs_skipped_missing_doc(monkeypatch, tmp_path) -> None:
    logger = _FakeLogger()
    _stub_setup(monkeypatch, logger)
    inv = SimpleNamespace(files=[SimpleNamespace(path="gone.md")])
    monkeypatch.setattr(
        cli_main.context_scanner, "scan", lambda *args, **kwargs: inv
    )
    cli_main.scan(repo=str(tmp_path))
    assert ("skip", "scan", "gone.md missing") in logger.events
