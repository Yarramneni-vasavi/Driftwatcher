"""Heading-aware excerpts: relevant sections win, fallback keeps the head."""

from driftwatcher.agents.non_llm.markdown_sections import (
    excerpt_for,
    parse_sections,
    score_section,
)

AI_DOC = """```mermaid
graph LR
    A["App"] --> B["Store"]
```

# AI_Interpretation_Layer

## Details

The system is structured around a Retrieval Augmented Generation pattern,
orchestrated by the Application Orchestrator.

## Testcases

Run pytest to verify nothing broke.
"""


def test_parse_sections_splits_preamble_and_headings() -> None:
    sections = parse_sections(AI_DOC.splitlines())
    titles = [title for _, title, _ in sections]
    assert titles[0] == ""
    assert "Details" in titles
    assert "Testcases" in titles


def test_feature_overlap_beats_generic_prior() -> None:
    assert score_section("QueryProcessor", "Query Processor", "agents") > (
        score_section("Details", "Query Processor", "agents")
    )


def test_details_beats_testcases_without_overlap() -> None:
    assert score_section("Details", "Unrelated Thing", "misc") > (
        score_section("Testcases", "Unrelated Thing", "misc")
    )


def test_excerpt_prefers_relevant_sections_over_diagram() -> None:
    excerpt = excerpt_for(AI_DOC, "AI Interpretation Layer", "agents", "a.md")
    assert "Retrieval Augmented Generation" in excerpt
    assert "graph LR" not in excerpt
    assert "pytest" not in excerpt


def test_excerpt_falls_back_to_head() -> None:
    text = "\n".join(f"line {i}" for i in range(100))
    assert excerpt_for(text, "Nope", "missing", "b.md") == (
        "\n".join(f"line {i}" for i in range(40))
    )


def test_excerpt_respects_line_budget() -> None:
    big = "\n".join(
        ["# Details"] + [f"body {i}" for i in range(500)]
    )
    assert len(excerpt_for(big, "Details", "x", "c.md").splitlines()) <= 120
