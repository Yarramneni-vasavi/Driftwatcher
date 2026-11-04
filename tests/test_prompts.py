"""Every file in llm/prompts/ is 500 characters or fewer (plan sec. 5.1)."""

from pathlib import Path

PROMPTS = Path(__file__).resolve().parent.parent / "src" / "driftwatcher" / "llm" / "prompts"

EXPECTED = {
    "feature_scout.txt",
    "doc_mapper.txt",
    "claim_extractor.txt",
    "judge.txt",
    "skill_author.txt",
    "doc_fixer.txt",
    "retry.txt",
    "flow_summarize.txt",
    "flow_missing.txt",
}


def test_all_prompts_present_and_short() -> None:
    files = {p.name for p in PROMPTS.glob("*.txt")}
    assert EXPECTED <= files, f"missing prompts: {EXPECTED - files}"
    for name in sorted(EXPECTED):
        text = (PROMPTS / name).read_text(encoding="utf-8").strip()
        assert text, f"{name} must not be empty"
        assert len(text) <= 500, f"{name} is {len(text)} chars, limit is 500"


def test_skill_author_teaches_skill_structure() -> None:
    text = (PROMPTS / "skill_author.txt").read_text(encoding="utf-8")
    for section in (
        "Entry points",
        "Behavior",
        "Limits and defaults",
        "Conventions",
    ):
        assert section in text, f"skill_author.txt must require {section}"
    assert "No X" in text, "skill_author.txt must forbid 'No X' filler lines"
