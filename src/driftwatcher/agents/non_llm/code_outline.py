"""N13 CodeOutline: free AST inventory of a feature folder.

Lists every function/class with signature, docstring line, decorators, and
decision points (raise/assert/early-return with their guard conditions).
This is the code equivalent of markdown headings: the miner selects from
it instead of reading whole files.
"""

from __future__ import annotations

import ast
from pathlib import Path

from ...contracts.rules import CodeOutline, Guard, OutlineUnit
from ...contracts.envelope import Envelope
from ...observability.decorators import logged_step
from .rule_checker import _SKIP_DIR_NAMES

AGENT_ID = "N13.CodeOutline"

MAX_CONDITION_CHARS = 120


def _short(node: ast.AST | None) -> str:
    if node is None:
        return ""
    try:
        text = ast.unparse(node)
    except Exception:  # noqa: BLE001 - unparse is best-effort
        return ""
    return " ".join(text.split())[:MAX_CONDITION_CHARS]


class _Visitor(ast.NodeVisitor):
    def __init__(self, file: str) -> None:
        self.file = file
        self.units: list[OutlineUnit] = []
        self._stack: list[OutlineUnit] = []
        self._ifs: list[str] = []

    def _current(self) -> OutlineUnit | None:
        return self._stack[-1] if self._stack else None

    def _guard(self, condition: str, outcome: str, kind: str, line: int) -> None:
        unit = self._current()
        if unit is not None:
            unit.guards.append(
                Guard(condition=condition, outcome=outcome, kind=kind, line=line)
            )

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        self._define(node, "function")

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        self._define(node, "function")

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        self._define(node, "class")

    def _define(self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef, kind: str) -> None:
        if kind == "class":
            params = ", ".join(
                _short(base) for base in getattr(node, "bases", [])
            )
        else:
            params = ", ".join(
                a.arg for a in getattr(node.args, "args", [])
            )
        unit = OutlineUnit(
            file=self.file,
            name=node.name,
            kind=kind,
            line=node.lineno,
            end_line=node.end_lineno or node.lineno,
            signature=f"{node.name}({params})",
            docstring=((ast.get_docstring(node) or "").splitlines() + [""])[0],
        )
        self.units.append(unit)
        self._stack.append(unit)
        self.generic_visit(node)
        self._stack.pop()

    def visit_If(self, node: ast.If) -> None:  # noqa: N802
        self._ifs.append(_short(node.test))
        self.generic_visit(node)
        self._ifs.pop()

    def visit_Raise(self, node: ast.Raise) -> None:  # noqa: N802
        condition = self._ifs[-1] if self._ifs else ""
        self._guard(condition, _short(node.exc) or "raise", "raise", node.lineno)
        self.generic_visit(node)

    def visit_Assert(self, node: ast.Assert) -> None:  # noqa: N802
        self._guard(_short(node.test), _short(node.msg) or "assert", "assert", node.lineno)
        self.generic_visit(node)

    def visit_Return(self, node: ast.Return) -> None:  # noqa: N802
        value = _short(node.value)
        if value in ("None", "False", "[]", "{}", "0", '""', "''"):
            condition = self._ifs[-1] if self._ifs else ""
            self._guard(condition, f"return {value}", "return", node.lineno)
        self.generic_visit(node)


def _iter_source_files(base: Path):
    for path in sorted(base.rglob("*.py")):
        try:
            parents = path.relative_to(base).parts[:-1]
        except ValueError:
            continue
        if any(part in _SKIP_DIR_NAMES or part.startswith(".") for part in parents):
            continue
        yield path


def build(folder: str, repo_root: str | Path = ".") -> CodeOutline:
    root = Path(repo_root)
    base = root / folder if folder else root
    outline = CodeOutline(folder=folder)
    if not base.is_dir():
        return outline
    for path in _iter_source_files(base):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        try:
            tree = ast.parse(text)
        except (SyntaxError, ValueError):
            continue
        try:
            rel = str(path.relative_to(root))
        except ValueError:
            rel = str(path)
        visitor = _Visitor(rel)
        visitor.visit(tree)
        outline.units.extend(visitor.units)
    return outline


@logged_step(AGENT_ID)
def handle(env: Envelope[CodeOutline]) -> Envelope[CodeOutline]:
    outline = build("", ".")
    return Envelope[CodeOutline](
        correlation_id=env.correlation_id,
        type="CodeOutline",
        sender=AGENT_ID,
        recipient=env.sender or "Orchestrator",
        payload=outline,
    )
