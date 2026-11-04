"""Match-matrix tiers: multi-feature docs cover everywhere, lead nowhere."""

from types import SimpleNamespace

from driftwatcher.contracts.features import FeatureInfo
from driftwatcher.contracts.mapping import DriftFile
from driftwatcher.orchestrator import onboard
from driftwatcher.orchestrator.onboard import _doc_matrix, _pretty_name


def test_doc_matrix_groups_features_per_doc() -> None:
    matched = {"f1": [("a.md", 0.9)], "f2": [("a.md", 0.7), ("b.md", 0.5)]}
    assert _doc_matrix(matched) == {"a.md": {"f1", "f2"}, "b.md": {"f2"}}


def test_pretty_name() -> None:
    assert _pretty_name("User_Interface_API_Gateway") == "User Interface API Gateway"


def _base_stubs(monkeypatch, docs, table, features=("f1",)):
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
            files=[SimpleNamespace(path=d, hash="") for d in docs]
        ),
    )
    monkeypatch.setattr(
        onboard.l1_feature_scout,
        "handle",
        lambda env: SimpleNamespace(
            payload=SimpleNamespace(
                features=[
                    FeatureInfo(name=name, folder=name) for name in features
                ]
            )
        ),
    )
    monkeypatch.setattr(
        onboard.folder_digester,
        "digest",
        lambda *a, **k: onboard.FolderDigest(folder="test"),
    )

    def fake_mapper(env):
        conf = table.get((env.payload.feature_name, env.payload.docs[0].path))
        if conf is None:
            return SimpleNamespace(
                payload=SimpleNamespace(match=False, quote="", confidence=0.0)
            )
        return SimpleNamespace(
            payload=SimpleNamespace(match=True, quote="q", confidence=conf)
        )

    monkeypatch.setattr(onboard.l2_doc_mapper, "handle", fake_mapper)
    monkeypatch.setattr(onboard.mapping_store, "read", lambda *a, **k: DriftFile())


def _capture_write(monkeypatch):
    saved: dict = {}
    monkeypatch.setattr(
        onboard.mapping_store, "write",
        lambda mapping, repo_root=".": saved.setdefault("mapping", mapping),
    )
    return saved


def test_multi_feature_doc_covers_both_but_leads_neither(
    monkeypatch, tmp_path, capsys
) -> None:
    _base_stubs(
        monkeypatch,
        ["a.md", "b.md", "s.md", "z.md"],
        {("f1", "a.md"): 0.9, ("f1", "b.md"): 0.5,
         ("f1", "s.md"): 0.8, ("f2", "s.md"): 0.7},
        features=("f1", "f2"),
    )
    saved = _capture_write(monkeypatch)
    onboard.run_onboard(repo_root=str(tmp_path), yes=True)

    mapping = saved["mapping"]
    # No primary: every referencing doc is kept, single or covering.
    assert mapping.features["f1"].context_files == ["a.md", "b.md", "s.md"]
    assert mapping.features["f2"].context_files == ["s.md"]
    assert mapping.resolutions == {}
    assert mapping.ignored_docs == ["z.md"]
    assert "0 uncovered" in capsys.readouterr().out


def test_no_matching_doc_maps_empty(monkeypatch, tmp_path, capsys) -> None:
    _base_stubs(monkeypatch, ["a.md"], {})
    saved = _capture_write(monkeypatch)
    onboard.run_onboard(repo_root=str(tmp_path), yes=True)

    mapping = saved["mapping"]
    assert mapping.features["f1"].context_files == []
    assert mapping.resolutions == {}
    assert mapping.ignored_docs == ["a.md"]
    assert not (tmp_path / "skills").exists()
    assert "0 uncovered" in capsys.readouterr().out


def test_all_matching_docs_kept_without_primary(monkeypatch, tmp_path) -> None:
    # Even a near-tie (0.9 vs 0.8) keeps both docs; nothing is picked.
    _base_stubs(
        monkeypatch,
        ["README.md", "overview.md"],
        {("f1", "README.md"): 0.9, ("f1", "overview.md"): 0.8},
    )
    saved = _capture_write(monkeypatch)
    onboard.run_onboard(repo_root=str(tmp_path), yes=True)

    mapping = saved["mapping"]
    assert mapping.features["f1"].context_files == [
        "README.md", "overview.md",
    ]
    assert mapping.resolutions == {}
    assert not (tmp_path / "skills").exists()


def test_global_stem_orphan_tracked_and_other_onboarded(
    monkeypatch, tmp_path
) -> None:
    _base_stubs(
        monkeypatch,
        ["a.md", "README.md", "User_Interface_API_Gateway.md"],
        {("f1", "a.md"): 0.9},
    )
    saved = _capture_write(monkeypatch)
    answers = iter(["", "1=1, 2=1"])
    monkeypatch.setattr("builtins.input", lambda *a, **k: next(answers))
    onboard.run_onboard(repo_root=str(tmp_path), yes=False)

    mapping = saved["mapping"]
    assert mapping.global_.context_files == ["README.md"]
    assert mapping.features["f1"].context_files == ["a.md"]
    adopted = "User Interface API Gateway"
    assert adopted in mapping.features
    # Adopted from an orphan doc with no dedicated doc of its own:
    # nothing is drafted, the feature keeps no docs.
    assert mapping.features[adopted].context_files == []
    assert f"nodoc:{adopted}" not in mapping.resolutions
    assert mapping.ignored_docs == []


def test_duplicate_review_keeps_chosen_doc(monkeypatch, tmp_path) -> None:
    # Identical docs go to bulk review; "1=2" keeps "a.md only", so b.md
    # is ignored. Saved duplicate:/nodoc: resolutions are inert and left
    # untouched — there is no primary to re-resolve.
    _base_stubs(
        monkeypatch, ["a.md", "b.md"],
        {("f1", "a.md"): 0.5, ("f1", "b.md"): 0.5},
    )
    stale = DriftFile()
    stale.resolutions["duplicate:f1"] = "a.md"
    monkeypatch.setattr(onboard.mapping_store, "read", lambda *a, **k: stale)
    saved = _capture_write(monkeypatch)
    answers = iter(["", "1=2"])
    monkeypatch.setattr("builtins.input", lambda *a, **k: next(answers))
    onboard.run_onboard(repo_root=str(tmp_path), yes=False)

    mapping = saved["mapping"]
    assert mapping.features["f1"].context_files == ["a.md"]
    assert mapping.ignored_docs == ["b.md"]
    assert mapping.resolutions["duplicate:f1"] == "a.md"


def test_identical_docs_deduped_and_orphan_ignored(
    monkeypatch, tmp_path
) -> None:
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
        lambda *a, **k: SimpleNamespace(files=[
            SimpleNamespace(path="d1.md", hash="h1"),
            SimpleNamespace(path="d2.md", hash="h1"),
            SimpleNamespace(path="z.md", hash="hz"),
        ]),
    )
    monkeypatch.setattr(
        onboard.l1_feature_scout,
        "handle",
        lambda env: SimpleNamespace(
            payload=SimpleNamespace(
                features=[FeatureInfo(name="f1", folder="f1")]
            )
        ),
    )
    monkeypatch.setattr(
        onboard.folder_digester,
        "digest",
        lambda *a, **k: onboard.FolderDigest(folder="test"),
    )
    def fake_mapper(env):
        if env.payload.docs[0].path == "z.md":
            return SimpleNamespace(
                payload=SimpleNamespace(match=False, quote="", confidence=0.0)
            )
        return SimpleNamespace(
            payload=SimpleNamespace(match=True, quote="q", confidence=0.9)
        )

    monkeypatch.setattr(onboard.l2_doc_mapper, "handle", fake_mapper)
    monkeypatch.setattr(onboard.mapping_store, "read", lambda *a, **k: DriftFile())
    saved = _capture_write(monkeypatch)
    answers = iter(["", "1=2, 2=2"])
    monkeypatch.setattr("builtins.input", lambda *a, **k: next(answers))
    onboard.run_onboard(repo_root=str(tmp_path), yes=False)

    mapping = saved["mapping"]
    assert mapping.features["f1"].context_files == ["d1.md"]
    assert sorted(mapping.ignored_docs) == ["d2.md", "z.md"]
