"""N6 CodeRetriever: snippets a claim refers to, changed files first."""

from __future__ import annotations

from pathlib import Path

from ...contracts.claims import Claim, CodeContext, CodeSnippet
from ...contracts.envelope import Envelope
from ...observability.decorators import logged_step

AGENT_ID = "N6.CodeRetriever"
TOKEN_BUDGET_CHARS = 24000


def retrieve(
    claim: Claim,
    folder: str,
    repo_root: str | Path = ".",
    changed_files: list[str] | None = None,
) -> CodeContext:
    root = Path(repo_root)
    base = root / folder if folder else root
    snippets: list[CodeSnippet] = []
    budget = TOKEN_BUDGET_CHARS
    ordered: list[Path] = []
    if changed_files:
        for rel in changed_files:
            p = root / rel
            if p.is_file() and p not in ordered:
                ordered.append(p)
    if base.is_dir():
        for path in sorted(base.rglob("*.py")):
            if path not in ordered:
                ordered.append(path)
    needles = [r for r in claim.refs if r] or [claim.text]
    for path in ordered:
        if budget <= 0:
            break
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lines = text.splitlines()
        hits: list[int] = []
        for i, line in enumerate(lines, start=1):
            for needle in needles:
                if needle and needle in line:
                    hits.append(i)
                    break
            if len(hits) >= 5:
                break
        if not hits and claim.kind == "path":
            continue
        target = hits[:5] if hits else [1]
        for lineno in target:
            start = max(1, lineno - 3)
            end = min(len(lines), lineno + 3)
            chunk = "\n".join(lines[start - 1 : end])
            if len(chunk) > budget:
                chunk = chunk[:budget]
            try:
                rel = str(path.relative_to(root))
            except ValueError:
                rel = str(path)
            snippets.append(
                CodeSnippet(file=rel, start=start, end=end, text=chunk)
            )
            budget -= len(chunk)
            if budget <= 0:
                break
    return CodeContext(claim_id=claim.id, snippets=snippets)


@logged_step(AGENT_ID)
def handle(env: Envelope[Claim]) -> Envelope[CodeContext]:
    claim = env.payload if isinstance(env.payload, Claim) else Claim()
    return Envelope[CodeContext](
        correlation_id=env.correlation_id,
        type="CodeContext",
        sender=AGENT_ID,
        recipient=env.sender or "Orchestrator",
        payload=retrieve(claim, ""),
    )
