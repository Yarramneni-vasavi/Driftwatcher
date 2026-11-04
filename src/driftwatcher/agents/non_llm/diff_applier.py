"""N12 DiffApplier: apply an approved unified diff to docs only, re-run check."""

from __future__ import annotations

from pathlib import Path

from ...contracts.envelope import Envelope
from ...observability.decorators import logged_step
from ...contracts.features import Answer
from ...contracts.fixes import FixProposal

AGENT_ID = "N12.DiffApplier"


def _is_doc_only(diff: str, repo_root: Path) -> bool:
    files = [
        line[4:].split(" ", 1)[0]
        for line in diff.splitlines()
        if line.startswith("+++ ") or line.startswith("--- ")
    ]
    targets = [f for f in files if f not in ("/dev/null", "b/dev/null")]
    if not targets:
        return False
    for target in targets:
        cleaned = target[2:] if target.startswith(("a/", "b/")) else target
        if not cleaned.endswith(".md"):
            return False
        resolved = (repo_root / cleaned).resolve()
        try:
            resolved.relative_to(repo_root.resolve())
        except ValueError:
            return False
    return True


def apply(
    proposal: FixProposal, answer: Answer, repo_root: str | Path = "."
) -> Path | None:
    if not answer.approved:
        return None
    root = Path(repo_root)
    if not _is_doc_only(proposal.diff, root):
        raise ValueError("FixProposal must touch doc (.md) files only.")
    target = root / proposal.doc_path
    target.parent.mkdir(parents=True, exist_ok=True)
    import subprocess

    proc = subprocess.run(
        ["patch", "-p1", "--forward", str(target)],
        input=proposal.diff,
        text=True,
        capture_output=True,
        cwd=str(root),
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"patch failed: {proc.stderr.strip()}")
    return target


@logged_step(AGENT_ID)
def handle(env: Envelope[FixProposal]) -> Envelope[FixProposal]:
    proposal = (
        env.payload if isinstance(env.payload, FixProposal) else FixProposal()
    )
    return Envelope[FixProposal](
        correlation_id=env.correlation_id,
        type="FixProposal",
        sender=AGENT_ID,
        recipient=env.sender or "Orchestrator",
        payload=proposal,
    )
