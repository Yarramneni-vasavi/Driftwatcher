"""Code->doc direction: business rules mined from code (plan: reverse check)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

RuleKind = Literal["positive", "negative"]
Scenario = Literal["positive", "negative", "edge"]
Significance = Literal["high", "low"]


class Guard(BaseModel):
    """One decision point: a guard condition tied to a code outcome."""

    model_config = ConfigDict(extra="forbid")

    condition: str = ""
    outcome: str = ""
    kind: str = "raise"
    line: int = 0


class OutlineUnit(BaseModel):
    """One function/class: the code headings the miner selects from."""

    model_config = ConfigDict(extra="forbid")

    file: str = ""
    name: str = ""
    kind: str = "function"
    line: int = 0
    end_line: int = 0
    signature: str = ""
    docstring: str = ""
    guards: list[Guard] = Field(default_factory=list)


class CodeOutline(BaseModel):
    folder: str = ""
    units: list[OutlineUnit] = Field(default_factory=list)

    def log_summary(self) -> dict:
        return {
            "folder": self.folder,
            "units": len(self.units),
            "guards": sum(len(u.guards) for u in self.units),
        }


class FunctionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file: str = ""
    name: str = ""
    line: int = 0
    text: str = ""


class BusinessRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feature: str = ""
    text: str = ""
    kind: RuleKind = "positive"
    file: str = ""
    line: int = 0

    def log_summary(self) -> dict:
        return {"feature": self.feature, "kind": self.kind, "text": self.text}


class RuleSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feature: str = ""
    rules: list[BusinessRule] = Field(default_factory=list)


class RuleSelectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feature: str = ""
    folder: str = ""
    outline: str = ""


class SelectedFunctions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    names: list[str] = Field(default_factory=list)


class RuleExtractRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feature: str = ""
    folder: str = ""
    functions: list[FunctionBody] = Field(default_factory=list)


class RuleJudgeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feature: str = ""
    rule: str = ""
    docs: list[str] = Field(default_factory=list)


class CallEdge(BaseModel):
    """One static call edge inside a feature folder (plan B3)."""

    model_config = ConfigDict(extra="forbid")

    caller: str = ""
    callee: str = ""
    file: str = ""
    line: int = 0
    external: bool = False


class EntryOutline(BaseModel):
    """Numbered reachable code for one entry point (plan B3)."""

    model_config = ConfigDict(extra="forbid")

    feature: str = ""
    entry_point: str = ""
    file: str = ""
    line: int = 0
    code: str = ""
    valid_ranges: list[list[int]] = Field(default_factory=list)
    calls: list[CallEdge] = Field(default_factory=list)
    tests: list[str] = Field(default_factory=list)
    openapi: str = ""


class FlowRule(BaseModel):
    """One mined behavior with scenario and significance (plan B4)."""

    model_config = ConfigDict(extra="forbid")

    id: str = ""
    scenario: Scenario = "positive"
    when: str = ""
    then: str = ""
    significance: Significance = "high"
    lines: list[int] = Field(default_factory=list)


class FlowSummary(BaseModel):
    """Flow summary for one entry point: one LLM call (plan B4)."""

    model_config = ConfigDict(extra="forbid")

    feature: str = ""
    entry_point: str = ""
    file: str = ""
    purpose: str = ""
    steps: list[str] = Field(default_factory=list)
    rules: list[FlowRule] = Field(default_factory=list)
    limits: list[str] = Field(default_factory=list)
    side_effects: list[str] = Field(default_factory=list)

    def log_summary(self) -> dict:
        return {
            "entry": f"{self.entry_point} ({self.file})",
            "rules": len(self.rules),
        }


class FlowSummarizeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feature: str = ""
    entry_point: str = ""
    file: str = ""
    code: str = ""
    calls: list[CallEdge] = Field(default_factory=list)
    tests: list[str] = Field(default_factory=list)
    openapi: str = ""


class MissingCheckRequest(BaseModel):
    """One batched missing-pass call: ~15 rules against whole doc text."""

    model_config = ConfigDict(extra="forbid")

    feature: str = ""
    entry_point: str = ""
    doc: str = ""
    rules: list[FlowRule] = Field(default_factory=list)


class MissingCheckResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    covered: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
