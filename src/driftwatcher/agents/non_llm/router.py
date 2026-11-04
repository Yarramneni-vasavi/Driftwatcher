"""N4 Router: map changed files to features, pick the change-matrix case.

Architecture sec. 7.2 matrix: none (skip/pass), code_only (main drift
case), doc_only, both. Global context files get deterministic checks only.
Unmapped folders produce a warning, not a failure.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from ...contracts.changes import ChangeSet, CheckPlan, FeatureCheckItem
from ...contracts.envelope import Envelope
from ...observability.decorators import logged_step
from ...contracts.mapping import DriftFile

AGENT_ID = "N4.Router"


def _is_doc(path: str) -> bool:
    return path.endswith(".md")


def _longest_prefix_feature(
    path: str, features: dict
) -> str | None:
    best: str | None = None
    best_len = -1
    for name, feat in features.items():
        folder = (feat.folder or "").strip("/")
        if folder and (path == folder or path.startswith(folder + "/")):
            if len(folder) > best_len:
                best, best_len = name, len(folder)
    return best


def _under(path: str, folder: str) -> bool:
    folder = folder.strip("/")
    return bool(folder) and (path == folder or path.startswith(folder + "/"))


def route_all(mapping: DriftFile, path: str = "") -> CheckPlan:
    """Full or partial check: every feature verified, no diff needed.

    With `path`, only features under that folder are included, but each
    included feature keeps ALL its context files: a doc outside the
    folder can still describe the feature, and the check must verify
    every doc, not just the feature's own SKILL.md. Global docs are
    always included (cheap deterministic checks).
    """
    items: list[FeatureCheckItem] = []
    for name, feat in mapping.features.items():
        if path and not _under(feat.folder, path):
            continue
        docs = list(feat.context_files)
        items.append(
            FeatureCheckItem(
                name=name, case="code_only", code_files=[], doc_files=docs
            )
        )
    return CheckPlan(
        features=items,
        global_docs=sorted(set(mapping.global_.context_files)),
        unmapped_folders=[],
    )


def route(changeset: ChangeSet, mapping: DriftFile) -> CheckPlan:
    per_feature_code: dict[str, list[str]] = {
        name: [] for name in mapping.features
    }
    per_feature_docs: dict[str, list[str]] = {
        name: [] for name in mapping.features
    }
    global_docs: list[str] = []
    unmapped: list[str] = []

    global_files = set(mapping.global_.context_files)
    mapped_doc_files: set[str] = set()
    for feat in mapping.features.values():
        mapped_doc_files.update(feat.context_files)

    for changed in changeset.files:
        path = changed.path
        if path in global_files:
            global_docs.append(path)
            continue
        feature = _longest_prefix_feature(path, mapping.features)
        if feature is None:
            if _is_doc(path):
                if path in mapped_doc_files:
                    for name, feat in mapping.features.items():
                        if path in feat.context_files:
                            per_feature_docs[name].append(path)
                else:
                    parent = str(PurePosixPath(path).parent)
                    if parent not in unmapped:
                        unmapped.append(parent)
            else:
                parent = str(PurePosixPath(path).parent)
                top = path.split("/")[0] if "/" in path else path
                if top not in unmapped:
                    unmapped.append(top)
            continue
        if _is_doc(path):
            per_feature_docs[feature].append(path)
        else:
            per_feature_code[feature].append(path)

    items: list[FeatureCheckItem] = []
    for name in mapping.features:
        code = sorted(set(per_feature_code.get(name, [])))
        docs = sorted(set(per_feature_docs.get(name, [])))
        if code and docs:
            case = "both"
        elif code:
            case = "code_only"
        elif docs:
            case = "doc_only"
        else:
            case = "none"
        items.append(
            FeatureCheckItem(
                name=name, case=case, code_files=code, doc_files=docs
            )
        )
    return CheckPlan(
        features=items,
        global_docs=sorted(set(global_docs)),
        unmapped_folders=sorted(unmapped),
    )


@logged_step(AGENT_ID)
def handle(env: Envelope[ChangeSet]) -> Envelope[CheckPlan]:
    changeset = env.payload if isinstance(env.payload, ChangeSet) else ChangeSet()
    mapping = DriftFile()
    return Envelope[CheckPlan](
        correlation_id=env.correlation_id,
        type="CheckPlan",
        sender=AGENT_ID,
        recipient=env.sender or "Orchestrator",
        payload=route(changeset, mapping),
    )
