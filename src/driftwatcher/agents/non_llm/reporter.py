"""N10 Reporter: DriftReport as Markdown + embedded JSON, exit code, MR comment."""

from __future__ import annotations

import json

from ...contracts.envelope import Envelope
from ...observability.decorators import logged_step
from ...contracts.verdicts import DriftReport, FeatureStatus, Verdict

AGENT_ID = "N10.Reporter"


def feature_state(
    contradicted: int, gaps: int, unverifiable: int, supported: int
) -> str:
    """clean|drift|unverified from findings alone, never from exit code."""
    if contradicted or gaps:
        return "drift"
    if unverifiable:
        return "unverified"
    return "clean"


def per_feature(name: str, verdicts: list[Verdict]) -> FeatureStatus:
    own = [v for v in verdicts if v.feature == name]
    contradicted = sum(1 for v in own if v.verdict == "contradicted")
    supported = sum(1 for v in own if v.verdict == "supported")
    unverifiable = sum(1 for v in own if v.verdict == "unverifiable")
    gaps = sum(1 for v in own if v.verdict == "gap")
    return FeatureStatus(
        name=name,
        status=feature_state(contradicted, gaps, unverifiable, supported),
        contradicted=contradicted,
        supported=supported,
        unverifiable=unverifiable,
        gaps=gaps,
    )


def build(
    verdicts: list[Verdict],
    mode: str = "warn",
    unmapped: list[str] | None = None,
    feature_names: list[str] | None = None,
) -> DriftReport:
    supported = sum(1 for v in verdicts if v.verdict == "supported")
    contradicted = sum(1 for v in verdicts if v.verdict == "contradicted")
    unverifiable = sum(1 for v in verdicts if v.verdict == "unverifiable")
    gaps = sum(1 for v in verdicts if v.verdict == "gap")
    names = feature_names or []
    features = [per_feature(name, verdicts) for name in names]
    return DriftReport(
        mode=mode,
        supported=supported,
        contradicted=contradicted,
        unverifiable=unverifiable,
        gaps=gaps,
        verdicts=verdicts,
        features=features,
        unmapped_folders=list(unmapped or []),
        advisory_tier3=True,
    )


def render_markdown(report: DriftReport) -> str:
    lines = [
        "## Driftwatch report",
        "",
        f"Supported: {report.supported} | Contradicted: "
        f"{report.contradicted} | Unverifiable: {report.unverifiable} "
        f"| Gaps: {report.gaps}",
        "",
    ]
    gap_rows = [v for v in report.verdicts if v.verdict == "gap"]
    if gap_rows:
        lines += ["### Undocumented behaviors", "",
                  "| Feature | Missing behavior | Code |", "|---|---|---|"]
        for v in sorted(gap_rows, key=lambda v: (v.feature, v.claim_id)):
            ev = ", ".join(f"{e.file}:{e.line}" for e in v.evidence) or "-"
            lines.append(f"| {v.feature} | {v.reason} | {ev} |")
        lines.append("")
    if report.verdicts:
        lines += ["| Feature | Claim | Verdict | Evidence |",
                  "|---|---|---|---|"]
        for v in sorted(report.verdicts, key=lambda v: (v.feature, v.claim_id)):
            if v.verdict == "gap":
                continue
            ev = ", ".join(f"{e.file}:{e.line}" for e in v.evidence) or "-"
            feat = v.feature or "-"
            lines.append(f"| {feat} | {v.claim_id} | {v.verdict} | {ev} |")
        lines.append("")
    if report.unmapped_folders:
        lines.append(
            "Unmapped folders: " + ", ".join(report.unmapped_folders)
        )
        lines.append("")
    lines.append("<!-- driftwatch:report " + report.model_dump_json() + " -->")
    return "\n".join(lines) + "\n"


def render_json_block(report: DriftReport) -> str:
    return "<!-- driftwatch:report " + report.model_dump_json() + " -->"


def parse_report_comment(body: str) -> DriftReport | None:
    marker = "<!-- driftwatch:report "
    start = body.find(marker)
    if start < 0:
        return None
    end = body.rfind("-->")
    if end < 0:
        return None
    raw = body[start + len(marker) : end].strip()
    try:
        return DriftReport.model_validate_json(raw)
    except ValueError:
        try:
            return DriftReport.model_validate(json.loads(raw))
        except ValueError:
            return None


def exit_code(report: DriftReport) -> int:
    """Impl plan sec. 10: 0 pass or warn-only; 1 contradiction in an
    enforced feature; 2 tool error (raised by the CLI, never here)."""
    if report.mode == "enforce" and report.contradicted:
        return 1
    return 0


@logged_step(AGENT_ID)
def handle(env: Envelope[DriftReport]) -> Envelope[DriftReport]:
    report = env.payload if isinstance(env.payload, DriftReport) else DriftReport()
    return Envelope[DriftReport](
        correlation_id=env.correlation_id,
        type="DriftReport",
        sender=AGENT_ID,
        recipient=env.sender or "Orchestrator",
        payload=report,
    )
