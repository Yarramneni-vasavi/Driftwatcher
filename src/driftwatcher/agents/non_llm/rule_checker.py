"""N7 RuleChecker: tier 1 (path/symbol/command exists). Tier 2 sandbox optional.

Returns a Verdict on success, else NeedsJudge for the LLM judge (L4).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import NamedTuple

from ...contracts.claims import Claim
from ...contracts.envelope import Envelope
from ...observability.decorators import logged_step
from ...contracts.verdicts import Evidence, NeedsJudge, Verdict

AGENT_ID = "N7.RuleChecker"

# Directories never worth searching for repo symbols (deps, caches, VCS).
_SKIP_DIR_NAMES = frozenset(
    {
        ".git",
        "__pycache__",
        "node_modules",
        ".venv",
        "venv",
        "env",
        ".tox",
        ".eggs",
        "build",
        "dist",
    }
)

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

class _FileEntry(NamedTuple):
    path: Path
    defs: dict[str, int]  # defined name -> line
    words: dict[str, int]  # identifier word -> first line
    lines: list[str]  # raw lines for exact fallback scans


# Per-repo symbol index, built once per repo instead of re-walking and
# re-parsing the whole tree for every symbol claim.
_INDEX_CACHE: dict[str, list[_FileEntry]] = {}


def _iter_source_files(base: Path):
    for path in sorted(base.rglob("*.py")):
        try:
            parents = path.relative_to(base).parts[:-1]
        except ValueError:
            continue
        if any(part in _SKIP_DIR_NAMES or part.startswith(".") for part in parents):
            continue
        yield path


def _get_file_entries(base: Path) -> list[_FileEntry]:
    key = str(base.resolve())
    cached = _INDEX_CACHE.get(key)
    if cached is not None:
        return cached
    entries: list[_FileEntry] = []
    for path in _iter_source_files(base):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        defs: dict[str, int] = {}
        try:
            tree = ast.parse(text)
        except (SyntaxError, ValueError):
            tree = None
        if tree is not None:
            for node in ast.walk(tree):
                if isinstance(
                    node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
                ):
                    defs.setdefault(node.name, node.lineno)
        words: dict[str, int] = {}
        lines = text.splitlines()
        for i, line in enumerate(lines, start=1):
            for word in _IDENT.findall(line):
                words.setdefault(word, i)
        entries.append(_FileEntry(path, defs, words, lines))
    _INDEX_CACHE[key] = entries
    return entries


def clear_symbol_index() -> None:
    _INDEX_CACHE.clear()


def _symbol_exists(symbol: str, folder: Path) -> Evidence | None:
    if not folder.is_dir():
        return None
    entries = _get_file_entries(folder)
    if _IDENT.fullmatch(symbol):
        for entry in entries:
            if symbol in entry.defs:
                return Evidence(file=str(entry.path), line=entry.defs[symbol])
            if symbol in entry.words:
                return Evidence(file=str(entry.path), line=entry.words[symbol])
        return None
    # Dotted / multi-word symbols (e.g. `a.b:c`, `API Service`): a full match
    # implies every identifier part is present, so skip the exact scan when
    # any part is absent. Verdicts are unchanged; the scan just gets cheaper.
    parts = _IDENT.findall(symbol)
    if parts and not all(
        any(part in entry.words for entry in entries) for part in parts
    ):
        return None
    pattern = re.compile(r"\b" + re.escape(symbol) + r"\b")
    for entry in entries:
        for i, line in enumerate(entry.lines, start=1):
            if pattern.search(line):
                return Evidence(file=str(entry.path), line=i)
    return None


def _command_exists(command: str, repo_root: Path, folder: Path) -> bool:
    if command.startswith("make "):
        target = command[5:].strip()
        for makefile in (folder / "Makefile", repo_root / "Makefile"):
            if makefile.is_file():
                text = makefile.read_text(encoding="utf-8", errors="replace")
                if re.search(rf"^{re.escape(target)}\s*:", text, re.M):
                    return True
        return False
    if command.startswith("npm run "):
        script = command[len("npm run ") :].strip()
        for pkg in (folder / "package.json", repo_root / "package.json"):
            if pkg.is_file() and script in pkg.read_text(
                encoding="utf-8", errors="replace"
            ):
                return True
        return False
    return False


def check(
    claim: Claim, repo_root: str | Path = ".", folder: str = ""
) -> Verdict | NeedsJudge:
    root = Path(repo_root)
    base = root / folder if folder else root
    if claim.kind == "path":
        candidate = root / claim.text.strip("`'\" ")
        if candidate.exists():
            try:
                rel = str(candidate.relative_to(root))
            except ValueError:
                rel = str(candidate)
            return Verdict(
                claim_id=claim.id,
                verdict="supported",
                evidence=[Evidence(file=rel, line=1)],
                reason=f"Path exists: {rel}",
                tier="deterministic",
            )
        return Verdict(
            claim_id=claim.id,
            verdict="contradicted",
            evidence=[],
            reason=f"Path missing: {claim.text}",
            tier="deterministic",
        )
    if claim.kind == "symbol":
        found = _symbol_exists(claim.text.strip("`"), base)
        if found is not None:
            try:
                rel = str((root / found.file).relative_to(root))
            except ValueError:
                rel = found.file
            return Verdict(
                claim_id=claim.id,
                verdict="supported",
                evidence=[Evidence(file=rel, line=found.line)],
                reason=f"Symbol found: {claim.text}",
                tier="deterministic",
            )
        return Verdict(
            claim_id=claim.id,
            verdict="contradicted",
            evidence=[],
            reason=f"Symbol missing: {claim.text}",
            tier="deterministic",
        )
    if claim.kind == "command":
        if _command_exists(claim.text, root, base):
            return Verdict(
                claim_id=claim.id,
                verdict="supported",
                evidence=[Evidence(file=folder or ".", line=1)],
                reason=f"Command target exists: {claim.text}",
                tier="deterministic",
            )
        return Verdict(
            claim_id=claim.id,
            verdict="contradicted",
            evidence=[],
            reason=f"Command target missing: {claim.text}",
            tier="deterministic",
        )
    return NeedsJudge(claim=claim, reason="behavior/convention needs judge")


@logged_step(AGENT_ID)
def handle(env: Envelope[Claim]) -> Envelope[Verdict | NeedsJudge]:
    claim = env.payload if isinstance(env.payload, Claim) else Claim()
    result = check(claim)
    kind = "Verdict" if isinstance(result, Verdict) else "NeedsJudge"
    return Envelope(
        correlation_id=env.correlation_id,
        type=kind,
        sender=AGENT_ID,
        recipient=env.sender or "Orchestrator",
        payload=result,
    )
