"""Live recall/noise gate for the flow miner (run before comparer).

Not part of the default suite: it needs an LLM key. The user runs it
and reports the output (it prints recall + noise, then asserts the
plan section 7 targets):

    set DRIFT_LIVE_SMOKE=1
    poetry run pytest tests/test_flow_smoke_live.py -s

It mines the fixture at tests/fixtures/flow_calc with the flow engine
(one summarize call per entry, batched whole-doc missing-pass), scores
the mined high-significance rules against flow_calc_golden.json, and
requires recall >= 0.70 with at most 3 noisy rules per entry. The
SKILL.md deliberately omits the guard/retry/default behaviors, so a
working miner must surface them as gaps.
"""

import json
import os
from pathlib import Path

import pytest

from driftwatcher.llm.budget import Budget
from driftwatcher.orchestrator import check as check_flow

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE = "tests/fixtures/flow_calc"
NEEDS_LIVE = pytest.mark.skipif(
    os.environ.get("DRIFT_LIVE_SMOKE") != "1",
    reason="needs DRIFT_LIVE_SMOKE=1 and an LLM key",
)


@NEEDS_LIVE
def test_live_flow_recall_vs_golden() -> None:
    golden = json.loads(
        (REPO_ROOT / "tests/fixtures/flow_calc_golden.json").read_text()
    )
    feature = golden["feature"]
    doc = str(REPO_ROOT / golden["doc"])
    mined: dict[str, list] = {}
    budget = Budget()
    for entry in golden["entries"]:
        outline, line_map = check_flow._build_entry_outline(
            feature, entry, f"{FIXTURE}/calc.py", FIXTURE, str(REPO_ROOT)
        )
        summary = check_flow._flow_summarize(
            feature, entry, outline, line_map,
            budget, "smoke", str(REPO_ROOT),
        )
        assert summary is not None, f"summarize failed for {entry}"
        mined[entry] = summary.rules
        print(f"\nentry {entry}: {len(summary.rules)} rules")
        for rule in summary.rules:
            print(
                f"  [{rule.significance}] {rule.id}: "
                f"when {rule.when} / then {rule.then} "
                f"(lines {rule.lines})"
            )
    score = check_flow._score_recall(mined, golden["entries"])
    print(f"\nrecall={score['recall']:.2f} "
          f"({score['hits']}/{score['total']})")
    for entry, noisy in score["noise"].items():
        print(f"noise {entry} ({len(noisy)}):")
        for line in noisy:
            print(f"  - {line}")
    worst = max(
        (len(v) for v in score["noise"].values()), default=0
    )
    assert score["recall"] >= 0.70, (
        f"recall {score['recall']:.2f} below 0.70 gate"
    )
    assert worst <= 3, f"noisiest entry has {worst} unmatched rules (>3)"
