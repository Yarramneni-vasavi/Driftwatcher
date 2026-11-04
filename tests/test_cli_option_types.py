"""CLI option types must stay compatible with the pinned Typer.

Typer 0.9.x cannot parse PEP 604 unions (``str | None``) in
``Annotated[..., typer.Option(...)]`` and aborts every command with::

    RuntimeError: Type not yet supported: str | None

This test statically guards ``src/driftwatcher/cli/main.py`` against
reintroducing a ``X | Y`` union inside any ``Annotated`` typer option, so the
CLI keeps working on the pinned Typer. Optional[...] is the compatible form.
"""

import ast
from pathlib import Path

CLI_MAIN = Path(__file__).parent.parent / "src" / "driftwatcher" / "cli" / "main.py"


def _pep604_unions_in_annotated(tree: ast.AST) -> list[int]:
    """Return line numbers of ``X | Y`` unions nested inside ``Annotated``."""
    hits: list[int] = []

    class Visitor(ast.NodeVisitor):
        def visit_Subscript(self, node: ast.Subscript) -> None:
            if isinstance(node.value, ast.Name) and node.value.id == "Annotated":
                for child in ast.walk(node.slice):
                    if isinstance(child, ast.BinOp) and isinstance(child.op, ast.BitOr):
                        hits.append(child.lineno)
            self.generic_visit(node)

    Visitor().visit(tree)
    return hits


def test_cli_options_avoid_pep604_unions() -> None:
    tree = ast.parse(CLI_MAIN.read_text(encoding="utf-8"))
    hits = _pep604_unions_in_annotated(tree)
    assert not hits, (
        "PEP 604 unions (X | None) inside Annotated typer options are not "
        f"supported by the pinned Typer 0.9.x (lines {hits}); "
        "use Optional[...] instead."
    )
