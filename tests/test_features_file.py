"""Features file: validation with key paths, propose template, diff."""

import json

import pytest

from driftwatcher.agents.non_llm import features_file
from driftwatcher.agents.non_llm.features_file import (
    diff_against,
    load_features_file,
    propose_template,
)
from driftwatcher.contracts.mapping import DriftFile, FeatureMapping


def _write(tmp_path, payload) -> str:
    path = tmp_path / "drift.features.json"
    path.write_text(json.dumps(payload))
    return str(path)


def test_valid_file_loads(tmp_path, monkeypatch) -> None:
    (tmp_path / "agents").mkdir()
    (tmp_path / "a.md").write_text("# A\n")
    monkeypatch.setattr(
        features_file.gitutil, "list_tracked",
        lambda repo_root=".": {"agents/x.py", "a.md"},
    )
    spec = load_features_file(
        _write(tmp_path, {
            "version": 1,
            "features": [{
                "name": "agents", "folder": "agents",
                "context_files": ["a.md"], "entry_points": ["run"],
                "owners": ["team-a"],
            }],
            "global": {"context_files": ["a.md"]},
            "ignored_docs": ["old.md"],
        }),
        tmp_path,
    )
    assert spec.features[0].entry_points == ["run"]
    assert spec.global_.context_files == ["a.md"]
    assert spec.ignored_docs == ["old.md"]


def test_unknown_key_rejected_with_path(tmp_path) -> None:
    (tmp_path / "agents").mkdir()
    with pytest.raises(ValueError, match="features file"):
        load_features_file(
            _write(tmp_path, {
                "features": [
                    {"name": "a", "folder": "agents", "bogus": 1},
                ],
            }),
            tmp_path,
        )


def test_duplicate_names_rejected(tmp_path, monkeypatch) -> None:
    (tmp_path / "agents").mkdir()
    monkeypatch.setattr(
        features_file.gitutil, "list_tracked", lambda repo_root=".": {"agents/x.py"}
    )
    with pytest.raises(ValueError, match="duplicate feature name"):
        load_features_file(
            _write(tmp_path, {
                "features": [
                    {"name": "a", "folder": "agents"},
                    {"name": "a", "folder": "agents"},
                ],
            }),
            tmp_path,
        )


def test_missing_folder_names_key_path(tmp_path) -> None:
    with pytest.raises(ValueError, match="features\\[0\\].*folder"):
        load_features_file(
            _write(tmp_path, {"features": [{"name": "a", "folder": "nope"}]}),
            tmp_path,
        )


def test_untracked_folder_rejected(tmp_path, monkeypatch) -> None:
    (tmp_path / "agents").mkdir()
    monkeypatch.setattr(
        features_file.gitutil, "list_tracked", lambda repo_root=".": set()
    )
    with pytest.raises(ValueError, match="not tracked in git"):
        load_features_file(
            _write(tmp_path, {"features": [{"name": "a", "folder": "agents"}]}),
            tmp_path,
        )


def test_missing_doc_names_key_path(tmp_path, monkeypatch) -> None:
    (tmp_path / "agents").mkdir()
    monkeypatch.setattr(
        features_file.gitutil, "list_tracked", lambda repo_root=".": {"agents/x.py"}
    )
    with pytest.raises(ValueError, match="context file"):
        load_features_file(
            _write(tmp_path, {
                "features": [{
                    "name": "a", "folder": "agents",
                    "context_files": ["gone.md"],
                }],
            }),
            tmp_path,
        )


def test_propose_template_shape() -> None:
    proposal = type("P", (), {})()
    f1 = type("F", (), {})()
    f1.name, f1.folder = "agents", "agents"
    proposal.features = [f1]
    assert propose_template(proposal) == {
        "version": 1,
        "features": [{"name": "agents", "folder": "agents"}],
    }


def test_diff_against() -> None:
    mapping = DriftFile()
    mapping.features["keep"] = FeatureMapping(
        folder="a", owners=[], context_files=["a.md"], status="onboarded",
    )
    mapping.features["gone"] = FeatureMapping(
        folder="g", owners=[], context_files=[], status="onboarded",
    )
    from driftwatcher.agents.non_llm.features_file import FeaturesInput

    spec = FeaturesInput.model_validate({
        "features": [
            {"name": "keep", "folder": "b"},
            {"name": "new", "folder": "n"},
        ],
    })
    diff = diff_against(spec, mapping)
    assert diff["added"] == ["new"]
    assert diff["unonboarded"] == ["gone"]
    assert diff["changed"] == ["keep: folder 'a' -> 'b'"]
