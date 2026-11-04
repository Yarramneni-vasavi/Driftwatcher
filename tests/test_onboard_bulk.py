"""Golden path: a tied duplicate set is resolved by one bulk answer line."""

from types import SimpleNamespace

from driftwatcher.contracts.features import FeatureInfo
from driftwatcher.contracts.mapping import DriftFile
from driftwatcher.orchestrator import onboard


def test_bulk_answer_resolves_tie_and_is_saved(monkeypatch, tmp_path) -> None:
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
            files=[SimpleNamespace(path="a.md", hash=""), SimpleNamespace(path="b.md", hash="")]
        ),
    )
    monkeypatch.setattr(onboard.mapping_store, "read", lambda *a, **k: DriftFile())
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
        doc = env.payload.docs[0].path
        return SimpleNamespace(
            payload=SimpleNamespace(match=True, quote="q", confidence=0.5)
            if doc in ("a.md", "b.md")
            else SimpleNamespace(match=False, quote="", confidence=0.0)
        )

    monkeypatch.setattr(onboard.l2_doc_mapper, "handle", fake_mapper)
    saved: dict = {}
    monkeypatch.setattr(
        onboard.mapping_store, "write",
        lambda mapping, repo_root=".": saved.setdefault("mapping", mapping),
    )
    answers = iter(["", "1=2"])
    monkeypatch.setattr("builtins.input", lambda *a, **k: next(answers))

    onboard.run_onboard(repo_root=str(tmp_path), yes=False)

    mapping = saved["mapping"]
    assert mapping.features["f1"].context_files == ["b.md", "a.md"]
    assert mapping.resolutions == {"duplicate:f1": "b.md"}


def test_yes_mode_accepts_suggestion_without_prompt(monkeypatch, tmp_path) -> None:
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
            files=[SimpleNamespace(path="a.md", hash=""), SimpleNamespace(path="b.md", hash="")]
        ),
    )
    monkeypatch.setattr(onboard.mapping_store, "read", lambda *a, **k: DriftFile())
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
    monkeypatch.setattr(
        onboard.l2_doc_mapper,
        "handle",
        lambda env: SimpleNamespace(
            payload=SimpleNamespace(match=True, quote="q", confidence=0.5)
        ),
    )
    saved: dict = {}
    monkeypatch.setattr(
        onboard.mapping_store, "write",
        lambda mapping, repo_root=".": saved.setdefault("mapping", mapping),
    )

    def _no_input(*a, **k):
        raise AssertionError("must not prompt in yes mode")

    monkeypatch.setattr("builtins.input", _no_input)
    onboard.run_onboard(repo_root=str(tmp_path), yes=True)

    mapping = saved["mapping"]
    assert mapping.features["f1"].context_files == ["a.md", "b.md"]
    assert mapping.resolutions == {"duplicate:f1": "a.md"}
