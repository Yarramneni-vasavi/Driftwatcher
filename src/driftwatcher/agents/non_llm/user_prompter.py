"""N11 UserPrompter: confirm features, resolve duplicates, approve diffs."""

from __future__ import annotations

import re
from typing import NamedTuple

from ...contracts.envelope import Envelope
from ...observability.decorators import logged_step
from ...contracts.features import Answer, Question

AGENT_ID = "N11.UserPrompter"


class BulkRow(NamedTuple):
    """One tie needing a primary doc: options in display order."""

    feature: str
    options: list[str]
    suggested: int = 0
    confidences: tuple[float, ...] = ()


BULK_ACCEPT_WORDS = frozenset({"all", "accept all", "yes", "y"})


def ask(question: Question, non_interactive_default: str = "") -> Answer:
    print(question.prompt)
    for i, option in enumerate(question.options, start=1):
        print(f"  {i}. {option}")
    if question.kind == "approve_diff":
        print("Approve? [y/N]")
    raw = input("> ").strip() if non_interactive_default == "" else non_interactive_default
    if question.kind == "approve_diff":
        approved = raw.lower() in ("y", "yes")
        return Answer(
            kind=question.kind, choice=raw, choices=[], approved=approved
        )
    if raw.isdigit() and question.options:
        idx = int(raw) - 1
        if 0 <= idx < len(question.options):
            return Answer(
                kind=question.kind,
                choice=question.options[idx],
                choices=[question.options[idx]],
            )
    if raw:
        return Answer(kind=question.kind, choice=raw, choices=[raw])
    return Answer(kind=question.kind, choice="", choices=list(question.options))


def _render_bulk(rows: list[BulkRow]) -> None:
    print(
        "Duplicate docs need one primary each "
        "(Enter = accept all * suggestions, e.g. 2=3):"
    )
    for i, row in enumerate(rows, start=1):
        print(f"  {i}. {row.feature}")
        for j, option in enumerate(row.options):
            mark = " *" if j == row.suggested else ""
            conf = (
                f" ({row.confidences[j]:.1f})"
                if j < len(row.confidences)
                else ""
            )
            print(f"     {j + 1}. {option}{conf}{mark}")


def _parse_bulk(raw: str, rows: list[BulkRow]) -> dict[str, str]:
    """Parse one bulk answer line into {feature: chosen doc}."""
    lowered = raw.strip().lower()
    if not lowered or lowered in BULK_ACCEPT_WORDS:
        return {}
    decisions: dict[str, str] = {}
    for token in [t for t in re.split(r"[,\s]+", raw.strip()) if t]:
        found = re.fullmatch(r"(\d+)=(\d+)", token)
        if found is None:
            raise ValueError(f"bad token {token!r}: want ROW=CHOICE like 2=3")
        row_idx, opt_idx = int(found.group(1)) - 1, int(found.group(2)) - 1
        if not 0 <= row_idx < len(rows) or not (
            0 <= opt_idx < len(rows[row_idx].options)
        ):
            raise ValueError(
                f"bad token {token!r}: row 1-{len(rows)}, "
                "choice within its listed options"
            )
        decisions[rows[row_idx].feature] = rows[row_idx].options[opt_idx]
    return decisions


def ask_bulk(
    rows: list[BulkRow], non_interactive_default: str = ""
) -> dict[str, str]:
    """One bulk duplicate review; {} means every suggestion accepted."""
    if not rows:
        return {}
    if non_interactive_default != "":
        try:
            return _parse_bulk(non_interactive_default, rows)
        except ValueError as exc:
            raise ValueError(f"invalid bulk default: {exc}") from exc
    while True:
        _render_bulk(rows)
        try:
            return _parse_bulk(input("> ").strip(), rows)
        except ValueError as exc:
            print(f"{exc}; nothing saved - try again.")


@logged_step(AGENT_ID)
def handle(env: Envelope[Question]) -> Envelope[Answer]:
    question = env.payload if isinstance(env.payload, Question) else Question(
        kind="confirm_features"
    )
    return Envelope[Answer](
        correlation_id=env.correlation_id,
        type="Answer",
        sender=AGENT_ID,
        recipient=env.sender or "Orchestrator",
        payload=ask(question),
    )
