"""N1 ContextScanner contracts (architecture sec. 5.1, plan sec. 4.3)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ScanRequest(BaseModel):
    repo_root: str = "."
    deny_globs: list[str] = Field(
        default_factory=lambda: [
            "CHANGELOG*",
            "LICENSE*",
            "node_modules/**",
            "vendor/**",
            "venv/**",
            ".venv/**",
        ]
    )

    def log_summary(self) -> dict:
        return {"repo_root": self.repo_root, "deny_globs": self.deny_globs}


class ContextFile(BaseModel):
    path: str
    hash: str = ""
    kind: Literal["known", "candidate"] = "candidate"

    def log_summary(self) -> dict:
        return {"path": self.path, "kind": self.kind}


class ContextInventory(BaseModel):
    files: list[ContextFile] = Field(default_factory=list)

    def log_summary(self) -> dict:
        known = sum(1 for f in self.files if f.kind == "known")
        return {
            "found": len(self.files),
            "known": known,
            "candidate": len(self.files) - known,
            "files": [f.path for f in self.files],
        }
