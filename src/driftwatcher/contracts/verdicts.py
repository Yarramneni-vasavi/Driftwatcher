"""Verdicts + report (architecture sec. 6.3 and 8, plan sec. 4.4)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .claims import Claim

VerdictLabel = Literal["supported", "contradicted", "unverifiable", "gap"]
VerdictTier = Literal["deterministic", "behavioral", "judge"]


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file: str
    line: int

    def log_summary(self) -> dict:
        return {"evidence": f"{self.file}:{self.line}"}


class Verdict(BaseModel):
    """A checked finding. claim_id and tier are required and non-empty.

    The orchestrator stamps both on every verdict regardless of producer,
    so a verdict reaching the report always carries its source claim and
    the tier that proved it (deterministic, behavioral, or judge).
    """

    model_config = ConfigDict(extra="forbid")

    claim_id: str = Field(min_length=1)
    verdict: VerdictLabel = "unverifiable"
    evidence: list[Evidence] = Field(default_factory=list)
    reason: str = ""
    needs_human: bool = False
    tier: VerdictTier
    feature: str = ""
    entry_point: str = ""

    def log_summary(self) -> dict:
        return {
            "claim_id": self.claim_id,
            "verdict": self.verdict,
            "evidence": [f"{e.file}:{e.line}" for e in self.evidence],
            "needs_human": self.needs_human,
            "tier": self.tier,
        }


class NeedsJudge(BaseModel):
    claim: Claim
    reason: str = ""

    def log_summary(self) -> dict:
        return {"claim_id": self.claim.id, "reason": self.reason}


FeatureState = Literal["clean", "drift", "unverified"]


class FeatureStatus(BaseModel):
    """Per-feature outcome, independent of exit code.

    clean: nothing contradicting or missing. drift: at least one
    contradiction or gap. unverified: findings exist but none proven
    either way.
    """

    name: str
    status: FeatureState = "clean"
    contradicted: int = 0
    supported: int = 0
    unverifiable: int = 0
    gaps: int = 0

    def log_summary(self) -> dict:
        return {
            "name": self.name,
            "status": self.status,
            "contradicted": self.contradicted,
            "gaps": self.gaps,
        }


class DriftReport(BaseModel):
    mode: str = "warn"
    supported: int = 0
    contradicted: int = 0
    unverifiable: int = 0
    gaps: int = 0
    verdicts: list[Verdict] = Field(default_factory=list)
    features: list[FeatureStatus] = Field(default_factory=list)
    unmapped_folders: list[str] = Field(default_factory=list)
    advisory_tier3: bool = True

    def log_summary(self) -> dict:
        return {
            "mode": self.mode,
            "supported": self.supported,
            "contradicted": self.contradicted,
            "unverifiable": self.unverifiable,
            "unmapped_folders": self.unmapped_folders,
        }
