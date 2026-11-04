"""Router: four change cases, global docs, unmapped folders (plan sec. 9)."""

from driftwatcher.agents.non_llm.router import route
from driftwatcher.contracts.changes import ChangeSet, ChangedFile
from driftwatcher.contracts.mapping import DriftFile, FeatureMapping


def _mapping() -> DriftFile:
    return DriftFile(
        verified_at="abc",
        **{
            "global": {"context_files": ["AGENTS.md"]},
            "features": {
                "auth": {
                    "folder": "services/auth",
                    "owners": [],
                    "context_files": ["services/auth/SKILL.md"],
                    "status": "onboarded",
                }
            },
        },
    )


def _by_name(plan, name: str):
    return next(f for f in plan.features if f.name == name)


def test_none_case_skips() -> None:
    plan = route(ChangeSet(files=[]), _mapping())
    assert _by_name(plan, "auth").case == "none"


def test_code_only_is_main_drift_case() -> None:
    cs = ChangeSet(
        files=[ChangedFile(path="services/auth/session.py", status="M")]
    )
    plan = route(cs, _mapping())
    item = _by_name(plan, "auth")
    assert item.case == "code_only"
    assert item.code_files == ["services/auth/session.py"]


def test_doc_only() -> None:
    cs = ChangeSet(
        files=[ChangedFile(path="services/auth/SKILL.md", status="M")]
    )
    plan = route(cs, _mapping())
    item = _by_name(plan, "auth")
    assert item.case == "doc_only"
    assert item.doc_files == ["services/auth/SKILL.md"]


def test_both() -> None:
    cs = ChangeSet(
        files=[
            ChangedFile(path="services/auth/session.py", status="M"),
            ChangedFile(path="services/auth/SKILL.md", status="M"),
        ]
    )
    plan = route(cs, _mapping())
    assert _by_name(plan, "auth").case == "both"


def test_global_docs_deterministic_only() -> None:
    cs = ChangeSet(files=[ChangedFile(path="AGENTS.md", status="M")])
    plan = route(cs, _mapping())
    assert plan.global_docs == ["AGENTS.md"]
    assert _by_name(plan, "auth").case == "none"


def test_unmapped_folder_warns_not_fails() -> None:
    cs = ChangeSet(
        files=[ChangedFile(path="services/billing/app.py", status="A")]
    )
    plan = route(cs, _mapping())
    assert _by_name(plan, "auth").case == "none"
    assert plan.unmapped_folders, "unmapped folder must produce a warning entry"


def test_longest_prefix_wins() -> None:
    mapping = _mapping()
    mapping.features["auth-nested"] = FeatureMapping(
        folder="services/auth/legacy", context_files=[]
    )
    cs = ChangeSet(
        files=[ChangedFile(path="services/auth/legacy/x.py", status="M")]
    )
    plan = route(cs, mapping)
    assert _by_name(plan, "auth-nested").case == "code_only"
    assert _by_name(plan, "auth").case == "none"
