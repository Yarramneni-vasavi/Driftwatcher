"""Fix workflow: contradictions -> L6 DocFixer -> approval -> N12 (arch 7.3).

Sources: local run (default) or `--pr N` reading the embedded JSON block
via `gh pr view --comments`. Claims with `needs_human` are skipped and
listed. After apply, re-run check on touched features.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from ..agents.llm import doc_fixer as l6_doc_fixer
from ..agents.non_llm import diff_applier, reporter, user_prompter
from ..contracts.claims import Claim
from ..contracts.envelope import Envelope
from ..contracts.features import Question
from ..contracts.fixes import ContradictedClaim, FixRequest
from ..contracts.verdicts import DriftReport, Evidence, Verdict
from ..observability.logger import StepTracker, get_logger
from .check import run_check

STEPS = ["L6.DocFixer", "N12.DiffApplier"]


def report_from_pr(pr: int) -> DriftReport | None:
    proc = subprocess.run(
        ["gh", "pr", "view", str(pr), "--comments"],
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        return None
    for block in re.findall(
        r"<!-- driftwatch:report (.*?) -->", proc.stdout, re.S
    ):
        parsed = reporter.parse_report_comment(
            "<!-- driftwatch:report " + block + " -->"
        )
        if parsed is not None:
            return parsed
    return None


def run_fix(
    repo_root: str = ".",
    pr: int | None = None,
    base: str = "origin/main",
    yes: bool = False,
) -> DriftReport:
    root = Path(repo_root)
    if pr is not None:
        report = report_from_pr(pr)
        if report is None:
            raise RuntimeError(f"Could not read DriftReport for PR {pr}.")
    else:
        report = run_check(repo_root=repo_root, base=base)

    from ..agents.non_llm import mapping_store as _store
    from ..agents.non_llm import rule_claims as _rules
    from ..contracts.claims import DocText as _DocText

    mapping = _store.read(repo_root)
    claim_index: dict[str, Claim] = {}
    for feat in mapping.features.values():
        for doc in feat.context_files:
            p = root / doc
            if not p.exists():
                continue
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
            for claim in _rules.extract(
                _DocText(doc_path=doc, lines=lines)
            ).claims:
                claim_index[claim.id] = claim

    claims_by_doc: dict[str, list[tuple[Claim, Verdict]]] = {}
    skipped: list[str] = []
    for verdict in report.verdicts:
        if verdict.verdict != "contradicted":
            continue
        if verdict.needs_human:
            skipped.append(verdict.claim_id)
            continue
        claim = claim_index.get(verdict.claim_id)
        if claim is None:
            skipped.append(verdict.claim_id)
            continue
        claims_by_doc.setdefault(claim.doc_path, []).append((claim, verdict))

    tracker = StepTracker(get_logger(), STEPS)
    for doc_path, pairs in claims_by_doc.items():
        tracker.use_feature(None)
        doc_text = (root / doc_path).read_text(
            encoding="utf-8", errors="replace"
        ) if (root / doc_path).exists() else ""
        req = FixRequest(
            doc_path=doc_path,
            doc_text=doc_text,
            contradicted=[
                ContradictedClaim(
                    claim=claim,
                    evidence=list(v.evidence or [Evidence(file=doc_path, line=1)]),
                )
                for claim, v in pairs
            ],
        )
        env: Envelope[FixRequest] = Envelope(
            correlation_id="fix", type="FixRequest",
            sender="Orchestrator", recipient="L6.DocFixer", payload=req,
        )
        with tracker.step("L6.DocFixer", {"doc": doc_path}) as span:
            out = l6_doc_fixer.handle(env)
            if out.error is not None:
                span.skip(f"fixer error: {out.error.message}")
                continue
            span.ok(out.payload)
        proposal = out.payload
        if not yes:
            answer = user_prompter.ask(
                Question(
                    kind="approve_diff",
                    prompt=f"Apply fix to {doc_path}?\n{proposal.diff}",
                    options=[doc_path],
                )
            )
        else:
            from ..contracts.features import Answer

            answer = Answer(kind="approve_diff", approved=True)
        with tracker.step("N12.DiffApplier", {"doc": doc_path}) as span:
            try:
                applied = diff_applier.apply(proposal, answer, repo_root)
            except (ValueError, RuntimeError) as exc:
                span.skip(str(exc))
                continue
            span.ok({"doc": doc_path, "applied": bool(applied)})

    result = run_check(repo_root=repo_root, base=base)
    if skipped:
        print("Skipped (needs_human): " + ", ".join(skipped))
        logger = get_logger()
        if logger is not None:
            logger.warning("L6.DocFixer", f"skipped needs_human: {skipped}")
    return result
