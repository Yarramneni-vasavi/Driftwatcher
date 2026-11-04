"""N5/L3 claims + N6/L4 code context (architecture sec. 6.3, plan sec. 4.4)."""

from __future__ import annotations

from hashlib import sha256
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ClaimKind = Literal["path", "symbol", "command", "behavior", "convention"]


class Claim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = ""
    doc_path: str = ""
    line: int = 0
    text: str = ""
    kind: ClaimKind = "behavior"
    feature: str = "global"
    refs: list[str] = Field(default_factory=list)

    @staticmethod
    def make_id(doc_path: str, line: int, text: str) -> str:
        return sha256(f"{doc_path}:{line}:{text}".encode()).hexdigest()[:16]

    def log_summary(self) -> dict:
        return {
            "id": self.id,
            "doc": f"{self.doc_path}:{self.line}",
            "kind": self.kind,
            "text": self.text,
        }


class DocText(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_path: str = ""
    feature: str = "global"
    lines: list[str] = Field(default_factory=list)

    def log_summary(self) -> dict:
        return {"doc": self.doc_path, "lines": len(self.lines)}


class ClaimSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_path: str = ""
    claims: list[Claim] = Field(default_factory=list)

    def log_summary(self) -> dict:
        by_kind: dict[str, int] = {}
        for c in self.claims:
            by_kind[c.kind] = by_kind.get(c.kind, 0) + 1
        return {"doc": self.doc_path, "claims": len(self.claims), "by_kind": by_kind}


class ClaimExtractRequest(BaseModel):
    doc_path: str = ""
    feature: str = "global"
    lines: list[str] = Field(default_factory=list)

    def log_summary(self) -> dict:
        return {
            "feature": self.feature,
            "doc": self.doc_path,
            "lines": len(self.lines),
        }


class CodeSnippet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file: str
    start: int = 0
    end: int = 0
    text: str = ""

    def log_summary(self) -> dict:
        return {"file": f"{self.file}:{self.start}-{self.end}"}


class CodeContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str = ""
    snippets: list[CodeSnippet] = Field(default_factory=list)

    def log_summary(self) -> dict:
        return {
            "claim_id": self.claim_id,
            "snippets": len(self.snippets),
            "chars": sum(len(s.text) for s in self.snippets),
            "files": sorted({s.file for s in self.snippets}),
        }


class JudgeRequest(BaseModel):
    claim: Claim
    snippets: list[CodeSnippet] = Field(default_factory=list)

    def log_summary(self) -> dict:
        return {
            "claim_id": self.claim.id,
            "doc": f"{self.claim.doc_path}:{self.claim.line}",
            "snippets": len(self.snippets),
        }
