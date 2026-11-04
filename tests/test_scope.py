"""Check scopes: committed/uncommitted diffs, full and partial baselines."""

import pytest

from driftwatcher.agents.non_llm import change_detector, router
from driftwatcher.agents.non_llm.router import route_all
from driftwatcher.contracts.changes import ChangeRequest, ChangeSet, ChangedFile
from driftwatcher.contracts.mapping import DriftFile
from driftwatcher.orchestrator import check as check_flow


def _mapping() -> DriftFile:
    return DriftFile(
        **{
            "global": {"context_files": ["AGENTS.md"]},
            "features": {
                "auth": {
                    "folder": "services/auth",
                    "owners": [],
                    "context_files": [
                        "services/auth/SKILL.md",
                        "overview.md",
                    ],
                    "status": "onboarded",
                },
                "billing": {
                    "folder": "services/billing",
                    "owners": [],
                    "context_files": ["services/billing/SKILL.md"],
                    "status": "onboarded",
                },
            },
        },
    )


def test_detect_uncommitted_uses_worktree_status(monkeypatch) -> None:
    monkeypatch.setattr(
        change_detector.gitutil,
        "worktree_status",
        lambda repo_root=".": [("modified", "a.py"), ("untracked", "b.md")],
    )
    changeset = change_detector.detect(
        ChangeRequest(repo_root=".", scope="uncommitted")
    )
    assert [(f.path, f.status) for f in changeset.files] == [
        ("a.py", "modified"),
        ("b.md", "untracked"),
    ]


def test_detect_committed_uses_base_diff(monkeypatch) -> None:
    monkeypatch.setattr(
        change_detector.gitutil,
        "diff_name_status",
        lambda base, head, repo_root=".": [("M", "a.py")],
    )
    monkeypatch.setattr(
        change_detector.gitutil, "hash_object", lambda *a, **k: ""
    )
    changeset = change_detector.detect(
        ChangeRequest(base="origin/main", scope="committed")
    )
    assert [f.path for f in changeset.files] == ["a.py"]


def test_detect_full_raises() -> None:
    with pytest.raises(ValueError, match="no change detection"):
        change_detector.detect(ChangeRequest(scope="full"))


def test_route_all_full_covers_everything() -> None:
    plan = route_all(_mapping())
    assert sorted(f.name for f in plan.features) == ["auth", "billing"]
    assert all(f.case == "code_only" for f in plan.features)
    assert plan.global_docs == ["AGENTS.md"]


def test_route_all_partial_filters_by_folder() -> None:
    plan = route_all(_mapping(), "services/auth")
    assert [f.name for f in plan.features] == ["auth"]
    auth = plan.features[0]
    assert plan.global_docs == ["AGENTS.md"]


def test_route_all_partial_keeps_all_feature_docs() -> None:
    # --path scopes which features are checked, not which docs verify
    # them: overview.md lives outside services/auth but still describes
    # auth, so the check must verify it too.
    plan = route_all(_mapping(), "services/auth")
    auth = plan.features[0]
    assert auth.doc_files == ["services/auth/SKILL.md", "overview.md"]


def test_run_check_rejects_bad_scope_combos(tmp_path) -> None:
    with pytest.raises(ValueError, match="unknown scope"):
        check_flow.run_check(repo_root=str(tmp_path), scope="bogus")
    with pytest.raises(ValueError, match="requires --path"):
        check_flow.run_check(repo_root=str(tmp_path), scope="partial")
    with pytest.raises(ValueError, match="only applies to"):
        check_flow.run_check(
            repo_root=str(tmp_path), scope="full", path="x"
        )


def test_committed_routing_unchanged() -> None:
    plan = router.route(
        ChangeSet(files=[ChangedFile(path="services/auth/x.py")]), _mapping()
    )
    auth = next(f for f in plan.features if f.name == "auth")
    assert (auth.case, auth.code_files) == ("code_only", ["services/auth/x.py"])
