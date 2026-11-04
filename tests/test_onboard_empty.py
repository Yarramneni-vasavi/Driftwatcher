"""Empty scout proposal exits instead of confirming an empty list."""

from types import SimpleNamespace

import pytest

from driftwatcher.contracts.mapping import DriftFile
from driftwatcher.orchestrator import onboard


def test_run_onboard_exits_when_scout_finds_nothing(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        onboard,
        "get_active",
        lambda: SimpleNamespace(
            scan=SimpleNamespace(deny_globs=[], known_context_names=[])
        ),
    )
    monkeypatch.setattr(
        onboard.context_scanner, "scan", lambda *a, **k: SimpleNamespace(files=[])
    )
    monkeypatch.setattr(onboard.mapping_store, "read", lambda *a, **k: DriftFile())
    monkeypatch.setattr(
        onboard.l1_feature_scout,
        "handle",
        lambda env: SimpleNamespace(payload=SimpleNamespace(features=[])),
    )

    def _no_write(*a, **k):
        raise AssertionError("write must not run with zero features")

    monkeypatch.setattr(onboard.mapping_store, "write", _no_write)
    with pytest.raises(RuntimeError, match="no features"):
        onboard.run_onboard(repo_root=str(tmp_path), yes=True)
