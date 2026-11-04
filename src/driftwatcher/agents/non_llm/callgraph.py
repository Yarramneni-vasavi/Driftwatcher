"""B3.1 call graph: follow calls into helpers inside the feature folder.

Deterministic, no LLM. Each file is parsed once into an index of
top-level definitions, imports, and per-function calls. reachable()
walks internal edges to depth 2-3; calls that leave the folder (or
that cannot be resolved to a local definition) become external
side-effect edges. This fixes thin entry points such as `run` that
only call `step_*` helpers.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

from ...contracts.rules import CallEdge
from .rule_checker import _SKIP_DIR_NAMES

MAX_DEPTH = 3
MAX_CODE_CHARS = 12000
TEST_BODY_LINES = 40


@dataclass
class TestHint:
    path: str
    name: str
    body: str


@dataclass
class _ModuleIndex:
    defs: dict[str, tuple[int, int]] = field(default_factory=dict)
    imports: dict[str, str] = field(default_factory=dict)
    calls: dict[str, list[tuple[str, int]]] = field(default_factory=dict)


def _module_name(file: str) -> str:
    stem = Path(file).stem
    parent = Path(file).parent
    if str(parent) in (".", ""):
        return stem
    return f"{str(parent).replace('/', '.')}.{stem}"


class _Indexer(ast.NodeVisitor):
    """Index top-level defs, imports, and per-function call sites."""

    def __init__(self, module: str) -> None:
        self.module = module
        self.index = _ModuleIndex()
        self._class: str | None = None
        self._func: str | None = None

    def _qual(self, name: str) -> str:
        if self._class and not self._func:
            return f"{self._class}.{name}"
        return name

    def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
        for alias in node.names:
            self.index.imports[alias.asname or alias.name] = alias.name
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
        if node.level:
            self.generic_visit(node)
            return
        module = node.module or ""
        for alias in node.names:
            if alias.name == "*":
                continue
            self.index.imports[alias.asname or alias.name] = (
                f"{module}.{alias.name}" if module else alias.name
            )
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        if self._func is None:
            self.index.defs[node.name] = (
                node.lineno, node.end_lineno or node.lineno
            )
            prev, self._class = self._class, node.name
            self.generic_visit(node)
            self._class = prev
        else:
            self.generic_visit(node)

    def _function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        qual = self._qual(node.name)
        if self._func is None:
            self.index.defs.setdefault(
                qual, (node.lineno, node.end_lineno or node.lineno)
            )
            prev, self._func = self._func, qual
            self.generic_visit(node)
            self._func = prev
        else:
            self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        self._function(node)

    def visit_AsyncFunctionDef(  # noqa: N802
        self, node: ast.AsyncFunctionDef
    ) -> None:
        self._function(node)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        if self._func is not None:
            name = _called_name(node.func, self._class)
            if name:
                self.index.calls.setdefault(self._func, []).append(
                    (name, node.lineno)
                )
        self.generic_visit(node)


def _called_name(
    func: ast.AST, current_class: str | None
) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        value = func.value
        if (
            isinstance(value, ast.Name)
            and value.id in ("self", "cls")
            and current_class
        ):
            return f"{current_class}.{func.attr}"
        return func.attr
    return None


def index_folder(folder: str, repo_root: str | Path = ".") -> dict[str, _ModuleIndex]:
    """Parse every .py file once; return {rel_path: index}."""
    root = Path(repo_root)
    base = root / folder if folder else root
    out: dict[str, _ModuleIndex] = {}
    if not base.is_dir():
        return out
    for path in sorted(base.rglob("*.py")):
        try:
            rel = str(path.relative_to(root))
        except ValueError:
            continue
        parts = Path(rel).parts[:-1]
        if any(p in _SKIP_DIR_NAMES or p.startswith(".") for p in parts):
            continue
        try:
            tree = ast.parse(
                path.read_text(encoding="utf-8", errors="replace")
            )
        except (OSError, SyntaxError, ValueError):
            continue
        indexer = _Indexer(_module_name(rel))
        indexer.visit(tree)
        out[rel] = indexer.index
    return out


def _resolve(
    callee: str, from_file: str, index: dict[str, _ModuleIndex]
) -> tuple[str, str] | None:
    """Resolve a called name to (file, qualname) inside the folder."""
    here = index.get(from_file)
    if here is not None:
        if callee in here.defs:
            return from_file, callee
        target = here.imports.get(callee.split(".")[0])
        if target:
            rest = callee.split(".")[1:]
            mod_file = target.replace(".", "/") + ".py"
            for rel, mod in index.items():
                if rel == mod_file or rel.endswith("/" + mod_file):
                    name = rest[0] if rest else callee.split(".")[-1]
                    if name in mod.defs:
                        return rel, name
            dotted = target + ("." + ".".join(rest) if rest else "")
            for rel, mod in index.items():
                for qual in mod.defs:
                    if qual == dotted or qual.endswith("." + dotted):
                        return rel, qual
    short = callee.split(".")[-1]
    for rel, mod in index.items():
        if short in mod.defs:
            return rel, short
    return None


def reachable(
    entry_file: str,
    entry_name: str,
    index: dict[str, _ModuleIndex],
    max_depth: int = MAX_DEPTH,
) -> tuple[dict[str, list[list[int]]], list[CallEdge]]:
    """BFS from an entry point; return (segments, edges).

    segments: {file: [[start, end], ...]} merged line ranges.
    edges: internal CallEdges plus external=True side effects.
    """
    segments: dict[str, set[int]] = {}
    edges: list[CallEdge] = []
    seen: set[tuple[str, str]] = set()
    queue: list[tuple[str, str, int]] = [(entry_file, entry_name, 0)]
    while queue:
        file, qual, depth = queue.pop(0)
        if (file, qual) in seen or depth > max_depth:
            continue
        seen.add((file, qual))
        mod = index.get(file)
        if mod is None or qual not in mod.defs:
            continue
        start, end = mod.defs[qual]
        segments.setdefault(file, set()).update(range(start, end + 1))
        if depth == max_depth:
            continue
        for callee, line in mod.calls.get(qual, []):
            resolved = _resolve(callee, file, index)
            if resolved is None:
                edges.append(
                    CallEdge(
                        caller=qual, callee=callee, file=file,
                        line=line, external=True,
                    )
                )
                continue
            target_file, target_qual = resolved
            edges.append(
                CallEdge(
                    caller=qual, callee=target_qual,
                    file=target_file, line=line, external=False,
                )
            )
            queue.append((target_file, target_qual, depth + 1))
    merged: dict[str, list[list[int]]] = {}
    for file, lines in segments.items():
        ordered = sorted(lines)
        ranges: list[list[int]] = []
        for ln in ordered:
            if ranges and ln == ranges[-1][1] + 1:
                ranges[-1][1] = ln
            else:
                ranges.append([ln, ln])
        merged[file] = ranges
    return merged, edges


def _is_test_file(rel: str) -> bool:
    name = Path(rel).name
    return (
        name.startswith("test_")
        or name.endswith("_test.py")
        or "tests" in Path(rel).parts
    )


def entry_candidates(
    folder: str, repo_root: str | Path = "."
) -> list[tuple[str, str]]:
    """Public top-level defs/classes, skipping tests and privates."""
    index = index_folder(folder, repo_root)
    out: list[tuple[str, str]] = []
    for rel, mod in index.items():
        if _is_test_file(rel):
            continue
        for qual in mod.defs:
            short = qual.split(".")[-1]
            if short.startswith("_"):
                continue
            out.append((qual, rel))
    return sorted(out)


def find_tests(
    folder: str,
    repo_root: str | Path,
    entry_name: str,
    file_stem: str,
) -> list[TestHint]:
    """Deterministic M7-light: test names mentioning the entry or file.

    Tests are hints, never proof. Only matching bodies are returned,
    capped at TEST_BODY_LINES lines each.
    """
    root = Path(repo_root)
    base = root / folder if folder else root
    tokens = {
        t.lower()
        for t in (entry_name.replace(".", " ").replace("_", " ").split()
                  + file_stem.replace("_", " ").split())
        if len(t) > 2
    }
    hints: list[TestHint] = []
    search = [base, root / "tests"] if (root / "tests").is_dir() else [base]
    seen: set[str] = set()
    for top in search:
        if not top.is_dir():
            continue
        for path in sorted(top.rglob("*.py")):
            try:
                rel = str(path.relative_to(root))
            except ValueError:
                continue
            if rel in seen or not _is_test_file(rel):
                continue
            seen.add(rel)
            try:
                tree = ast.parse(
                    path.read_text(encoding="utf-8", errors="replace")
                )
            except (OSError, SyntaxError, ValueError):
                continue
            for node in ast.walk(tree):
                if not isinstance(
                    node, (ast.FunctionDef, ast.AsyncFunctionDef)
                ):
                    continue
                words = set(node.name.lower().replace("_", " ").split())
                if not (tokens & words):
                    continue
                try:
                    lines = path.read_text(
                        encoding="utf-8", errors="replace"
                    ).splitlines()
                except OSError:
                    continue
                body = "\n".join(
                    lines[node.lineno - 1 : node.lineno - 1 + TEST_BODY_LINES]
                )
                hints.append(TestHint(path=rel, name=node.name, body=body))
    return hints
