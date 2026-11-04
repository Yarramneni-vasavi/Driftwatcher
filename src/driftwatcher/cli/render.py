"""Terminal output helpers."""

from __future__ import annotations

from ..contracts.verdicts import DriftReport


def print_report(report: DriftReport) -> None:
    print(
        f"Supported: {report.supported} | Contradicted: "
        f"{report.contradicted} | Unverifiable: {report.unverifiable}"
    )
    for verdict in report.verdicts:
        ev = ", ".join(f"{e.file}:{e.line}" for e in verdict.evidence) or "-"
        flag = " [needs_human]" if verdict.needs_human else ""
        print(f"[{verdict.verdict}] {verdict.claim_id} {ev}{flag}")
        if verdict.reason:
            print(f"  {verdict.reason}")
    if report.unmapped_folders:
        print("Unmapped folders: " + ", ".join(report.unmapped_folders))
