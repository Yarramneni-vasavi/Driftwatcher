"""map --features: locked docs skip the LLM, merge keeps user data."""

import json
from types import SimpleNamespace

from driftwatcher.contracts.features import FeatureInfo
from driftwatcher.contracts.mapping import DriftFile, FeatureMapping
from driftwatcher.orchestrator import onboard


def _base_stubs(monkeypatch, tmp_path, inv_docs, scout_features):
    monkeypatch.setattr(
        onboard,
        "get_active",
        lambda: SimpleNamespace(
            scan=SimpleNamespace(deny_globs=[], known_context_names=[])
        ),
    )
    monkeypatch.setattr(
        onboard.context_scanner,
        "scan",
        lambda *a, **k: SimpleNamespace(
            files=[SimpleNamespace(path=d, hash="") for d in inv_docs]
        ),
    )
    monkeypatch.setattr(
        onboard.l1_feature_scout,
        "handle",
        lambda env: (_ for _ in ()).throw(
            AssertionError("scout must not run with --features")
        ),
    )
    monkeypatch.setattr(
        onboard.folder_digester,
        "digest",
        lambda *a, **k: onboard.FolderDigest(folder="f1"),
    )
    return scout_features


def _mapper_counter(monkeypatch):
    calls = {"n": 0}

    def fake_mapper(env):
        calls["n"] += 1
        return SimpleNamespace(
            payload=SimpleNamespace(match=True, quote="q", confidence=0.9)
        )

    monkeypatch.setattr(onboard.l2_doc_mapper, "handle", fake_mapper)
    return calls


def _capture_write(monkeypatch):
    saved: dict = {}
    monkeypatch.setattr(
        onboard.mapping_store, "write",
        lambda mapping, repo_root=".": saved.setdefault("mapping", mapping),
    )
    return saved


def _features_file(tmp_path, payload) -> str:
    path = tmp_path / "drift.features.json"
    path.write_text(json.dumps(payload))
    return str(path)


def test_locked_docs_skip_mapper_and_keep_user_data(
    monkeypatch, tmp_path, capsys
) -> None:
    (tmp_path / "agents").mkdir()
    (tmp_path / "a.md").write_text("# A\n")
    _base_stubs(monkeypatch, tmp_path, ["a.md"], None)
    stored = DriftFile()
    stored.features["agents"] = FeatureMapping(
        folder="agents", owners=["team-a"], context_files=["old.md"],
        status="onboarded", entry_points=["run"],
    )
    stored.resolutions["duplicate:agents"] = "old.md"
    monkeypatch.setattr(onboard.mapping_store, "read", lambda *a, **k: stored)
    mapper_calls = _mapper_counter(monkeypatch)
    saved = _capture_write(monkeypatch)
    monkeypatch.setattr("builtins.input", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("must not prompt with all docs locked")
    ))

    features_path = _features_file(tmp_path, {
        "features": [{
            "name": "agents", "folder": "agents",
            "context_files": ["a.md"],
        }],
    })
    onboard.run_onboard(repo_root=str(tmp_path), yes=True, features_path=features_path)

    assert mapper_calls["n"] == 0
    mapping = saved["mapping"]
    assert mapping.features["agents"].context_files == ["a.md"]
    assert mapping.features["agents"].owners == ["team-a"]
    assert mapping.features["agents"].entry_points == ["run"]
    assert mapping.features["agents"].origin == "user"
    assert mapping.resolutions["duplicate:agents"] == "old.md"
    out = capsys.readouterr().out
    assert "features file:" in out


def test_missing_docs_trigger_mapper(monkeypatch, tmp_path) -> None:
    (tmp_path / "agents").mkdir()
    (tmp_path / "a.md").write_text("# A\n")
    _base_stubs(monkeypatch, tmp_path, ["a.md"], None)
    monkeypatch.setattr(onboard.mapping_store, "read", lambda *a, **k: DriftFile())
    mapper_calls = _mapper_counter(monkeypatch)
    saved = _capture_write(monkeypatch)

    features_path = _features_file(tmp_path, {
        "features": [{"name": "agents", "folder": "agents"}],
    })
    onboard.run_onboard(repo_root=str(tmp_path), yes=True, features_path=features_path)

    assert mapper_calls["n"] == 1
    mapping = saved["mapping"]
    assert mapping.features["agents"].context_files == ["a.md"]
    assert mapping.features["agents"].origin == "auto"


def test_removed_feature_becomes_unonboarded(monkeypatch, tmp_path) -> None:
    (tmp_path / "agents").mkdir()
    (tmp_path / "a.md").write_text("# A\n")
    _base_stubs(monkeypatch, tmp_path, ["a.md"], None)
    stored = DriftFile()
    stored.features["gone"] = FeatureMapping(
        folder="gone", context_files=["a.md"], status="onboarded",
    )
    monkeypatch.setattr(onboard.mapping_store, "read", lambda *a, **k: stored)
    _mapper_counter(monkeypatch)
    saved = _capture_write(monkeypatch)

    features_path = _features_file(tmp_path, {
        "features": [{"name": "agents", "folder": "agents",
                      "context_files": ["a.md"]}],
    })
    onboard.run_onboard(repo_root=str(tmp_path), yes=True, features_path=features_path)

    mapping = saved["mapping"]
    assert mapping.features["gone"].status == "unonboarded"
    assert mapping.features["gone"].context_files == ["a.md"]


def test_refresh_rediscovers_auto_docs_only(monkeypatch, tmp_path) -> None:
    (tmp_path / "auto").mkdir()
    (tmp_path / "user").mkdir()
    (tmp_path / "a.md").write_text("# A\n")
    _base_stubs(monkeypatch, tmp_path, ["a.md"], None)
    stored = DriftFile()
    stored.features["auto"] = FeatureMapping(
        folder="auto", context_files=["a.md"], status="onboarded", origin="auto",
    )
    stored.features["user"] = FeatureMapping(
        folder="user", context_files=["a.md"], status="onboarded", origin="user",
    )
    monkeypatch.setattr(onboard.mapping_store, "read", lambda *a, **k: stored)
    mapper_calls = _mapper_counter(monkeypatch)
    saved = _capture_write(monkeypatch)

    features_path = _features_file(tmp_path, {
        "features": [
            {"name": "auto", "folder": "auto"},
            {"name": "user", "folder": "user"},
        ],
    })
    onboard.run_onboard(
        repo_root=str(tmp_path), yes=True,
        features_path=features_path, refresh=True,
    )

    assert mapper_calls["n"] == 1
    mapping = saved["mapping"]
    assert mapping.features["auto"].origin == "auto"
    assert mapping.features["user"].origin == "user"


def test_bad_features_file_is_runtime_error(monkeypatch, tmp_path) -> None:
    import pytest

    _base_stubs(monkeypatch, tmp_path, [], None)
    monkeypatch.setattr(onboard.mapping_store, "read", lambda *a, **k: DriftFile())
    features_path = _features_file(tmp_path, {
        "features": [{"name": "a", "folder": "agents", "bogus": 1}],
    })
    (tmp_path / "agents").mkdir()
    with pytest.raises(RuntimeError, match="features file"):
        onboard.run_onboard(
            repo_root=str(tmp_path), yes=True, features_path=features_path
        )
