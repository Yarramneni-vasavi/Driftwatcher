"""Deterministic recall tests for the code->doc direction.

Run-2 regression: the legacy miner never saw diff_analyzer.py because the
select-input outline was one truncated string and alphabetically late
files fell past the cut. These tests pin both layers without any LLM:

1. code_outline.build() reaches late-alphabet units.
2. _outline_text() spends its char budget round-robin, so every file is
   represented even under a tight budget.
3. Low-value gap patterns and cross-file grouping behave.
4. stamp_verdict() backfills claim_id/tier/feature.
"""

from driftwatcher.agents.non_llm import code_outline
from driftwatcher.contracts.rules import BusinessRule
from driftwatcher.contracts.verdicts import Evidence, Verdict
from driftwatcher.orchestrator import check as check_flow


def _write_agents_like(root) -> None:
    """Six files in sorted order; the target lives in the 6th, like
    diff_analyzer.py after abstraction/agent/agent_responses/details."""
    bodies = {
        "aa_first.py": "def step_cfg(ctx):\n    return ctx\n",
        "ab_second.py": "def run(ctx):\n    return step_cfg(ctx)\n",
        "ac_third.py": "def classify_files(files):\n    out = []\n    for f in files:\n        out.append(f)\n    return out\n",
        "ad_fourth.py": "def apply_feedback(a):\n    return a\n",
        "ae_fifth.py": "def generate_analysis(x):\n    return x\n",
        "az_target.py": (
            "def get_diff_data(store):\n"
            "    if not store.exists():\n"
            "        return []\n"
            "    return store.diff()\n"
            "\n"
            "def filter_diff(files):\n"
            "    return [f for f in files if f.endswith('.py')]\n"
        ),
    }
    for name, text in bodies.items():
        (root / name).write_text(text)


def test_outline_build_reaches_late_file(tmp_path) -> None:
    _write_agents_like(tmp_path)
    outline = code_outline.build("", str(tmp_path))
    names = {u.name for u in outline.units}
    assert "get_diff_data" in names
    assert "filter_diff" in names


def test_outline_text_covers_every_file_under_tight_budget(
    tmp_path, monkeypatch
) -> None:
    _write_agents_like(tmp_path)
    outline = code_outline.build("", str(tmp_path))
    monkeypatch.setattr(check_flow, "OUTLINE_CHARS", 200)
    text = check_flow._outline_text(outline)
    assert len(text) <= 200
    for stem in ("aa_first", "ab_second", "ac_third",
                 "ad_fourth", "ae_fifth", "az_target"):
        assert stem in text, f"{stem} starved out of select input"


def test_outline_text_full_budget_keeps_guard_detail(tmp_path) -> None:
    _write_agents_like(tmp_path)
    outline = code_outline.build("", str(tmp_path))
    text = check_flow._outline_text(outline)
    assert "get_diff_data" in text
    assert "filter_diff" in text
    assert "return []" in text


def test_low_value_patterns() -> None:
    assert check_flow.is_low_value(
        "run executes step_cfg then step_source then generate_analysis"
    )
    assert check_flow.is_low_value(
        "step_cfg stores parsed result in context['cfg_insight']"
    )
    assert check_flow.is_low_value(
        "generate_analysis uses 'No project context available' fallback"
    )
    assert check_flow.is_low_value(
        "step_cfg adds 'No programming languages detected.' marker"
    )
    assert not check_flow.is_low_value(
        "classify_files skips file when component is unknown"
    )
    assert not check_flow.is_low_value(
        "_parse_response sleeps 60 seconds then retries on ResourceExhausted"
    )


def test_group_rules_merges_cross_file_members() -> None:
    rules = [
        BusinessRule(
            feature="f", text="Apply feedback fixes source references",
            kind="positive", file="a.py", line=10,
        ),
        BusinessRule(
            feature="f", text="apply  feedback  FIXES source references!",
            kind="positive", file="b.py", line=20,
        ),
        BusinessRule(
            feature="f", text="Something else entirely",
            kind="negative", file="a.py", line=30,
        ),
    ]
    groups = check_flow._group_rules(rules)
    assert len(groups) == 2
    head, members = groups[0]
    assert head.file == "a.py"
    assert [m.file for m in members] == ["a.py", "b.py"]


def test_stamp_verdict_backfills() -> None:
    stamped = check_flow.stamp_verdict(
        Verdict.model_construct(
            verdict="unverifiable", reason="r",
            evidence=[Evidence(file="a.py", line=1)],
        ),
        tier="judge", feature="f",
    )
    assert stamped.claim_id.startswith("auto-")
    assert stamped.tier == "judge"
    assert stamped.feature == "f"


def test_stamp_verdict_keeps_producer_values() -> None:
    verdict = Verdict(
        claim_id="c1", verdict="supported", tier="deterministic",
        feature="a",
    )
    out = check_flow.stamp_verdict(
        verdict, claim_id="other", tier="judge", feature="b"
    )
    assert out.claim_id == "c1"
    assert out.tier == "deterministic"
    assert out.feature == "a"
