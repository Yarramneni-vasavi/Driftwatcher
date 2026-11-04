"""`.drift.json` schema — mapping only, no hashes (architecture sec. 6.1)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

FeatureStatus = Literal["unonboarded", "onboarded", "enforced"]
MappingOpKind = Literal[
    "add_feature", "set_docs", "set_status", "resolve_duplicate"
]


class FeatureMapping(BaseModel):
    folder: str = ""
    owners: list[str] = Field(default_factory=list)
    context_files: list[str] = Field(default_factory=list)
    status: FeatureStatus = "onboarded"
    entry_points: list[str] = Field(default_factory=list)
    api_spec: str = ""
    origin: Literal["auto", "user"] = "auto"

    def log_summary(self) -> dict:
        return {
            "folder": self.folder,
            "status": self.status,
            "context_files": self.context_files,
        }


class GlobalMapping(BaseModel):
    context_files: list[str] = Field(default_factory=list)

    def log_summary(self) -> dict:
        return {"context_files": self.context_files}


class DriftFile(BaseModel):
    version: int = 1
    verified_at: str = ""
    global_: GlobalMapping = Field(default_factory=GlobalMapping, alias="global")
    features: dict[str, FeatureMapping] = Field(default_factory=dict)
    ignored_docs: list[str] = Field(default_factory=list)
    resolutions: dict[str, str] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}

    def log_summary(self) -> dict:
        return {
            "features": sorted(self.features),
            "statuses": {n: f.status for n, f in self.features.items()},
        }


class MappingOp(BaseModel):
    op: MappingOpKind = "add_feature"
    feature: str = ""
    folder: str = ""
    owners: list[str] = Field(default_factory=list)
    context_files: list[str] = Field(default_factory=list)
    status: FeatureStatus = "onboarded"
    entry_points: list[str] = Field(default_factory=list)
    api_spec: str = ""
    origin: str = "auto"
    key: str = ""
    value: str = ""

    def log_summary(self) -> dict:
        return {"op": self.op, "feature": self.feature, "key": self.key}
