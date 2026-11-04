"""L1/L2/L5 + N3 + N11 contracts (architecture sec. 5, plan sec. 4.3)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class FeatureInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    folder: str
    reason: str = ""

    def log_summary(self) -> dict:
        return {"name": self.name, "folder": self.folder}


class FeatureScoutRequest(BaseModel):
    tree: str = ""
    manifests: dict[str, str] = Field(default_factory=dict)
    owners: dict[str, list[str]] = Field(default_factory=dict)

    def log_summary(self) -> dict:
        return {
            "tree_entries": len(self.tree.splitlines()),
            "manifests": sorted(self.manifests),
            "owners": sorted(self.owners),
        }


class FeatureProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    features: list[FeatureInfo] = Field(default_factory=list)

    def log_summary(self) -> dict:
        return {"features": [f.name for f in self.features]}


class DigestRequest(BaseModel):
    folder: str

    def log_summary(self) -> dict:
        return {"folder": self.folder}


class FolderDigest(BaseModel):
    folder: str
    tree: str = ""
    symbols: list[str] = Field(default_factory=list)
    commands: list[str] = Field(default_factory=list)
    file_heads: dict[str, str] = Field(default_factory=dict)

    def log_summary(self) -> dict:
        return {
            "folder": self.folder,
            "files": len(self.tree.splitlines()),
            "symbols": len(self.symbols),
            "commands": self.commands,
        }


class DocCandidate(BaseModel):
    path: str
    excerpt: str = ""

    def log_summary(self) -> dict:
        return {"path": self.path}


class DocMapRequest(BaseModel):
    feature_name: str
    feature_folder: str
    docs: list[DocCandidate] = Field(default_factory=list)

    def log_summary(self) -> dict:
        return {
            "feature": self.feature_name,
            "docs": [d.path for d in self.docs],
        }


class DocMatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feature: str
    doc: str
    match: bool = False
    quote: str = ""
    confidence: float = 0.0

    def log_summary(self) -> dict:
        return {
            "feature": self.feature,
            "doc": self.doc,
            "match": self.match,
            "confidence": self.confidence,
        }


class Question(BaseModel):
    kind: Literal["confirm_features", "pick_duplicate", "approve_diff"]
    prompt: str = ""
    options: list[str] = Field(default_factory=list)
    context: dict[str, str] = Field(default_factory=dict)

    def log_summary(self) -> dict:
        return {"kind": self.kind, "options": self.options}


class Answer(BaseModel):
    kind: Literal["confirm_features", "pick_duplicate", "approve_diff"]
    choice: str = ""
    choices: list[str] = Field(default_factory=list)
    approved: bool = False

    def log_summary(self) -> dict:
        return {
            "kind": self.kind,
            "choice": self.choice,
            "approved": self.approved,
        }
