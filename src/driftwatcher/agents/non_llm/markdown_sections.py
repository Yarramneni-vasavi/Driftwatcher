"""Heading-aware markdown excerpts for LLM judges (stdlib only).

Reusable piece: takes markdown text plus a relevance query (feature name and
folder), returns the most relevant sections within a line budget. Falls back
to the head of the file when nothing relevant is found, so callers never get
less than a plain head excerpt.
"""

from __future__ import annotations

import re

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*$")

# Generic heading prior: behavioral prose outranks logs and process docs.
_GENERIC_PRIOR: tuple[tuple[str, int], ...] = (
    ("detail", 3), ("overview", 3), ("description", 3), ("summary", 3),
    ("guide", 2), ("usage", 2), ("example", 1),
    ("test", -2), ("changelog", -3), ("faq", -2), ("license", -3),
    ("contributing", -3), ("appendix", -1),
)

MAX_LINES = 120
TOP_SECTIONS = 2
FALLBACK_LINES = 40


def _tokens(value: str) -> set[str]:
    return set(re.sub(r"[^a-z0-9]+", " ", value.lower()).split())


def parse_sections(lines: list[str]) -> list[tuple[int, str, list[str]]]:
    """Split lines into (level, title, body) sections; preamble first."""
    sections: list[tuple[int, str, list[str]]] = []
    level, title, body = 0, "", []
    for line in lines:
        found = _HEADING.match(line)
        if found is not None:
            sections.append((level, title, body))
            level, title, body = len(found.group(1)), found.group(2), []
        else:
            body.append(line)
    sections.append((level, title, body))
    return sections


def score_section(
    title: str, feature_name: str, feature_folder: str
) -> int:
    """Overlap with the query plus a small generic heading prior."""
    heading = _tokens(title)
    score = 10 * len(heading & _tokens(feature_name))
    score += 5 * len(heading & _tokens(feature_folder))
    lowered = title.lower()
    for word, prior in _GENERIC_PRIOR:
        if word in lowered:
            score += prior
    return score


def excerpt_for(
    text: str,
    feature_name: str,
    feature_folder: str,
    doc_path: str = "",
    max_lines: int = MAX_LINES,
    top_sections: int = TOP_SECTIONS,
) -> str:
    """Most relevant sections within budget, else the file head."""
    lines = text.splitlines()
    sections = [
        (level, title, body)
        for level, title, body in parse_sections(lines)
        if title or body
    ]
    ranked = sorted(
        (
            (score_section(title, feature_name, feature_folder), idx)
            for idx, (_, title, _) in enumerate(sections)
        ),
        key=lambda scored: (-scored[0], scored[1]),
    )
    picked = [sections[idx] for score, idx in ranked[:top_sections] if score > 0]
    if not picked:
        return "\n".join(lines[:FALLBACK_LINES])
    out: list[str] = []
    for _, title, body in picked:
        chunk = ([f"# {title}"] if title else []) + body
        out.extend(chunk)
        if len(out) >= max_lines:
            break
    excerpt = "\n".join(out[:max_lines])
    try:
        from ...observability.logger import get_logger

        logger = get_logger()
        if logger is not None:
            logger.cache(
                f"sections doc={doc_path} "
                + ", ".join(
                    f"{title!r}:{score}"
                    for score, idx in ranked[:top_sections]
                    for _, title, _ in [sections[idx]]
                )
            )
    except Exception:  # noqa: BLE001 - logging never breaks excerpts
        pass
    return excerpt
