"""L5/L6 fix contracts (plan sec. 4.3)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .claims import Claim
from .features import FolderDigest
from .verdicts import Evidence


class AuthorRequest(BaseModel):
    feature_name: str = ""
    digest: FolderDigest = Field(default_factory=lambda: FolderDigest(folder=""))

    def log_summary(self) -> dict:
        return {"feature": self.feature_name}


class DocDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = ""
    markdown: str = ""

    def log_summary(self) -> dict:
        return {"path": self.path, "lines": len(self.markdown.splitlines())}


class ContradictedClaim(BaseModel):
    claim: Claim
    evidence: list[Evidence] = Field(default_factory=list)

    def log_summary(self) -> dict:
        return {"claim_id": self.claim.id}


class FixRequest(BaseModel):
    doc_path: str = ""
    doc_text: str = ""
    contradicted: list[ContradictedClaim] = Field(default_factory=list)

    def log_summary(self) -> dict:
        return {
            "doc": self.doc_path,
            "contradicted": [c.claim.id for c in self.contradicted],
        }


class FixProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_path: str = ""
    diff: str = ""
    skipped: list[str] = Field(default_factory=list)

    def log_summary(self) -> dict:
        return {
            "doc": self.doc_path,
            "diff_lines": len(self.diff.splitlines()),
            "skipped": self.skipped,
        }
