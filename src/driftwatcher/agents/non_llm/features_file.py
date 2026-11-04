"""N14 FeaturesFile: human-written `drift.features.json` in, validated spec out.

The input file declares features (name + folder required; folders,
context_files, entry_points, owners, api_spec optional) plus top-level
global context files and ignored docs. Unknown keys are rejected.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ...contracts.mapping import DriftFile


class FeaturesInputFeature(BaseModel):
    model_config = {"extra": "forbid"}

    name: str
    folder: str
    folders: list[str] = Field(default_factory=list)
    context_files: list[str] | None = None
    entry_points: list[str] = Field(default_factory=list)
    owners: list[str] = Field(default_factory=list)
    api_spec: str | None = None


class FeaturesInputGlobal(BaseModel):
    model_config = {"extra": "forbid"}

    context_files: list[str] = Field(default_factory=list)


class FeaturesInput(BaseModel):
    model_config = {"extra": "forbid", "populate_by_name": True}

    version: int = 1
    features: list[FeaturesInputFeature] = Field(default_factory=list)
    global_: FeaturesInputGlobal | None = Field(default=None, alias="global")
    ignored_docs: list[str] | None = None


def _key_error(where: str, message: str) -> ValueError:
    return ValueError(f"features file {where}: {message}")


def load_features_file(path: str | Path, repo_root: str | Path = ".") -> FeaturesInput:
    """Parse and validate; errors name the key path (features[N].folder)."""
    raw_path = Path(path)
    try:
        data = json.loads(raw_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"features file {raw_path}: cannot read ({exc})") from exc
    except ValueError as exc:
        raise ValueError(f"features file {raw_path}: invalid JSON ({exc})") from exc
    if not isinstance(data, dict):
        raise ValueError(f"features file {raw_path}: top level must be an object")
    try:
        spec = FeaturesInput.model_validate(data)
    except Exception as exc:  # noqa: BLE001 - reformatted below
        raise ValueError(f"features file {raw_path}: {exc}") from exc
    root = Path(repo_root)
    try:
        from ... import gitutil

        tracked: set[str] | None = gitutil.list_tracked(root)
    except RuntimeError:
        tracked = None
    names: set[str] = set()
    for i, feat in enumerate(spec.features):
        where = f"features[{i}] ({feat.name or '?'})"
        if not feat.name.strip():
            raise _key_error(where, "name is required")
        if feat.name in names:
            raise _key_error(where, f"duplicate feature name {feat.name!r}")
        names.add(feat.name)
        if not feat.folder.strip():
            raise _key_error(f"features[{i}] ({feat.name})", "folder is required")
        for folder in [feat.folder, *feat.folders]:
            folder = folder.strip().rstrip("/")
            if not folder:
                raise _key_error(where, "folder names must be non-empty")
            if not (root / folder).exists():
                raise _key_error(where, f"folder {folder!r} does not exist")
            if tracked is not None and not any(
                t == folder or t.startswith(folder + "/") for t in tracked
            ):
                raise _key_error(where, f"folder {folder!r} is not tracked in git")
        for doc in feat.context_files or []:
            if not (root / doc).is_file():
                raise _key_error(where, f"context file {doc!r} does not exist")
        if feat.api_spec and not (root / feat.api_spec).is_file():
            raise _key_error(where, f"api_spec {feat.api_spec!r} does not exist")
    if spec.global_ is not None:
        for doc in spec.global_.context_files:
            if not (root / doc).is_file():
                raise _key_error("global.context_files", f"{doc!r} does not exist")
    return spec


def propose_template(proposal: Any, repo_root: str | Path = ".") -> dict:
    """Shape an L1 FeatureProposal into the input-file format for editing."""
    features = []
    for feat in getattr(proposal, "features", []) or []:
        features.append({"name": feat.name, "folder": feat.folder})
    return {"version": 1, "features": features}


def diff_against(
    spec: FeaturesInput, mapping: DriftFile
) -> dict[str, list[str]]:
    """Summarize what applying the file would change (before writing)."""
    old = set(mapping.features)
    new = {f.name for f in spec.features}
    changed: list[str] = []
    for feat in spec.features:
        cur = mapping.features.get(feat.name)
        if cur is None:
            continue
        notes = []
        if cur.folder != feat.folder:
            notes.append(f"folder {cur.folder!r} -> {feat.folder!r}")
        if feat.owners and cur.owners != feat.owners:
            notes.append(f"owners {cur.owners} -> {feat.owners}")
        if feat.context_files is not None and cur.context_files != feat.context_files:
            notes.append(
                f"context_files {cur.context_files} -> {feat.context_files}"
            )
        if notes:
            changed.append(f"{feat.name}: " + "; ".join(notes))
    return {
        "added": sorted(new - old),
        "unonboarded": sorted(old - new),
        "changed": sorted(changed),
    }
