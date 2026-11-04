"""N2 ChangeDetector + N4 Router contracts (plan sec. 4.3)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

CheckCase = Literal["none", "code_only", "doc_only", "both"]

CheckScope = Literal["committed", "uncommitted", "full", "partial"]

SCOPES: tuple[str, ...] = ("committed", "uncommitted", "full", "partial")


class ChangeRequest(BaseModel):
    base: str = "origin/main"
    head: str = "HEAD"
    repo_root: str = "."
    scope: str = "committed"

    def log_summary(self) -> dict:
        return {"base": self.base, "head": self.head, "scope": self.scope}


class ChangedFile(BaseModel):
    path: str
    status: str = "M"
    hash: str = ""

    def log_summary(self) -> dict:
        return {"path": self.path, "status": self.status}


class ChangeSet(BaseModel):
    base: str = "origin/main"
    head: str = "HEAD"
    files: list[ChangedFile] = Field(default_factory=list)

    def log_summary(self) -> dict:
        by_status: dict[str, int] = {}
        for f in self.files:
            by_status[f.status] = by_status.get(f.status, 0) + 1
        return {
            "base": self.base,
            "files": len(self.files),
            "by_status": by_status,
            "paths": [f.path for f in self.files],
        }


class FeatureCheckItem(BaseModel):
    name: str
    case: CheckCase = "none"
    code_files: list[str] = Field(default_factory=list)
    doc_files: list[str] = Field(default_factory=list)

    def log_summary(self) -> dict:
        return {
            "name": self.name,
            "case": self.case,
            "code_files": self.code_files,
            "doc_files": self.doc_files,
        }


class CheckPlan(BaseModel):
    features: list[FeatureCheckItem] = Field(default_factory=list)
    global_docs: list[str] = Field(default_factory=list)
    unmapped_folders: list[str] = Field(default_factory=list)

    def log_summary(self) -> dict:
        return {
            "cases": {f.name: f.case for f in self.features},
            "global_docs": self.global_docs,
            "unmapped_folders": self.unmapped_folders,
        }
