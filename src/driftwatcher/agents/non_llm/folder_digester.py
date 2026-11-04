"""N3 FolderDigester: size-capped digest (tree, symbols, commands, heads)."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from ...contracts.envelope import Envelope
from ...observability.decorators import logged_step
from ...contracts.features import DigestRequest, FolderDigest

AGENT_ID = "N3.FolderDigester"
MAX_TREE_ENTRIES = 200
MAX_SYMBOLS = 200
MAX_HEAD_CHARS = 2000
MAX_FILES_HEADS = 10


def _tree(folder: Path, repo_root: Path) -> list[str]:
    entries: list[str] = []
    for path in sorted(folder.rglob("*")):
        if len(entries) >= MAX_TREE_ENTRIES:
            break
        if path.is_dir():
            continue
        entries.append(str(path.relative_to(repo_root)))
    return entries


def _symbols(path: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (SyntaxError, ValueError):
        return []
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not node.name.startswith("_"):
                names.append(node.name)
    return names


def _commands(folder: Path) -> list[str]:
    cmds: list[str] = []
    makefile = folder / "Makefile"
    if makefile.exists():
        text = makefile.read_text(encoding="utf-8", errors="replace")
        cmds += [f"make {m}" for m in re.findall(r"^([\w][\w.-]*)\s*:", text, re.M)]
    pkg = folder / "package.json"
    if pkg.exists():
        text = pkg.read_text(encoding="utf-8", errors="replace")
        cmds += [f"npm run {m}" for m in re.findall(r'"([\w:.-]+)"\s*:', text)]
    root_make = folder.parent / "Makefile" if folder.parent != folder else None
    if root_make is not None and root_make.exists() and makefile != root_make:
        text = root_make.read_text(encoding="utf-8", errors="replace")
        cmds += [f"make {m}" for m in re.findall(r"^([\w][\w.-]*)\s*:", text, re.M)]
    seen: list[str] = []
    for cmd in cmds:
        if cmd not in seen:
            seen.append(cmd)
    return seen[:50]


def digest(req: DigestRequest, repo_root: str | Path = ".") -> FolderDigest:
    root = Path(repo_root)
    folder = root / req.folder
    tree = _tree(folder, root) if folder.exists() else []
    symbols: list[str] = []
    heads: dict[str, str] = {}
    if folder.exists():
        py_files = sorted(folder.rglob("*.py"))[:MAX_FILES_HEADS]
        for path in py_files:
            for name in _symbols(path):
                if len(symbols) < MAX_SYMBOLS and name not in symbols:
                    symbols.append(name)
            rel = str(path.relative_to(root))
            heads[rel] = path.read_text(
                encoding="utf-8", errors="replace"
            )[:MAX_HEAD_CHARS]
    return FolderDigest(
        folder=req.folder,
        tree="\n".join(tree),
        symbols=symbols,
        commands=_commands(folder) if folder.exists() else [],
        file_heads=heads,
    )


@logged_step(AGENT_ID)
def handle(env: Envelope[DigestRequest]) -> Envelope[FolderDigest]:
    req = env.payload if isinstance(env.payload, DigestRequest) else DigestRequest(folder="")
    return Envelope[FolderDigest](
        correlation_id=env.correlation_id,
        type="FolderDigest",
        sender=AGENT_ID,
        recipient=env.sender or "Orchestrator",
        payload=digest(req),
    )
