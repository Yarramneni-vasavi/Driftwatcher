"""Deterministic tests for the flow miner pieces (no LLM).

Pins N8 line validation, near-duplicate merging with stable ids,
missing-pass batching at ~15 rules per call, recall scoring vs golden
shape, entry-outline numbering, and the flow cache key.
"""

from driftwatcher.agents.non_llm import callgraph
from driftwatcher.cache import store
from driftwatcher.contracts.envelope import Envelope
from driftwatcher.contracts.rules import (
    FlowRule,
    FlowSummary,
    MissingCheckResult,
)
from driftwatcher.llm.budget import Budget
from driftwatcher.orchestrator import check as check_flow


def _rule(id, when, then, lines, significance="high") -> FlowRule:
    return FlowRule(
        id=id, scenario="positive", when=when, then=then,
        significance=significance, lines=list(lines),
    )


def test_n8_drops_out_of_range_lines_and_empty_rules() -> None:
    summary = FlowSummary(
        feature="f", entry_point="e", file="a.py",
        rules=[
            _rule("r1", "x missing", "returns []", [3, 99]),
            _rule("r2", "never sent", "does y", [98, 99]),
        ],
    )
    out = check_flow._n8_validate(summary, {3: ["a.py"], 4: ["a.py"]})
    assert [r.id for r in out.rules] == ["r1"]
    assert out.rules[0].lines == [3]


def test_merge_flow_rules_unions_lines_prefers_high_assigns_ids() -> None:
    rules = [
        _rule("", "coupon  none", "rate 0.0", [24], "low"),
        _rule("r9", "coupon none", "rate 0.0!", [25], "high"),
        _rule("r9", "other thing", "elsewhere", [40]),
    ]
    merged = check_flow._merge_flow_rules(rules)
    assert len(merged) == 2
    assert merged[0].lines == [24, 25]
    assert merged[0].significance == "high"
    assert merged[0].id == "r1"
    assert merged[1].id == "r9"
    assert merged[1].lines == [40]


def test_flow_missing_pass_batches_and_splits(monkeypatch) -> None:
    calls: list[int] = []

    def fake_check_missing(req, recipient, correlation_id):
        calls.append(len(req.rules))
        ids = [r.id for r in req.rules]
        return Envelope(
            correlation_id=correlation_id,
            type="MissingCheckResult",
            sender="L7",
            recipient=recipient,
            payload=MissingCheckResult(
                covered=ids[:10], missing=ids[10:],
            ),
        )

    monkeypatch.setattr(
        check_flow.l7_miner, "check_missing", fake_check_missing
    )
    rules = [_rule(f"r{i}", f"when {i}", f"then {i}", [i]) for i in range(32)]
    rules.append(_rule("low1", "trivial", "detail", [1], "low"))
    missing, unchecked = check_flow._flow_missing_pass(
        "f", "e", "a.py", rules, {i: ["a.py"] for i in range(32)},
        "doc", Budget(), "c", ".",
    )
    assert calls == [15, 15, 2]
    assert {r.id for r in missing} == (
        {f"r{i}" for i in range(10, 15)} | {f"r{i}" for i in range(25, 30)}
    )
    assert unchecked == []
    assert all(r.id != "low1" for r in missing)


def test_flow_missing_pass_budget_exhaustion_is_unverifiable(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        check_flow.l7_miner, "check_missing",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no call")),
    )
    budget = Budget(max_calls=0)
    rules = [_rule("r1", "w", "t", [1])]
    missing, unchecked = check_flow._flow_missing_pass(
        "f", "e", "a.py", rules, {1: ["a.py"]},
        "doc", budget, "c", ".",
    )
    assert missing == []
    assert [r.id for r in unchecked] == ["r1"]


def test_score_recall_counts_hits_and_noise() -> None:
    mined = {
        "compute_total": [
            _rule("r1", "sku empty", "raises", [9, 10]),
            _rule("r7", "something else", "happens", [50]),
        ],
    }
    golden = {
        "compute_total": [
            {"id": "g1", "significance": "high", "lines": [10]},
            {"id": "g2", "significance": "high", "lines": [20]},
            {"id": "g3", "significance": "low", "lines": [50]},
        ],
    }
    score = check_flow._score_recall(mined, golden)
    assert score["hits"] == 1
    assert score["total"] == 2
    assert score["recall"] == 0.5
    assert list(score["noise"]) == ["compute_total"]


def test_build_entry_outline_numbers_code_and_maps_lines(tmp_path) -> None:
    (tmp_path / "calc.py").write_text(
        "def helper(x):\n"
        "    return x\n"
        "\n"
        "def entry(items):\n"
        "    return helper(items)\n"
    )
    outline, line_map = check_flow._build_entry_outline(
        "f", "entry", "calc.py", "", str(tmp_path)
    )
    assert outline.entry_point == "entry"
    assert "calc.py:4:" in outline.code
    assert "calc.py:1:" in outline.code
    assert line_map[4] == ["calc.py"]
    assert outline.valid_ranges
    flat = [ln for r in outline.valid_ranges for ln in range(r[0], r[1] + 1)]
    assert set(line_map) == set(flat)


def test_flow_key_format() -> None:
    assert store.flow_key("f", "my-entry", "abc") == "flow-f-my-entry-abc.json"


def test_flow_entries_falls_back_to_public_defs(tmp_path) -> None:
    (tmp_path / "mod.py").write_text(
        "def public_fn():\n    return 1\n"
        "\n"
        "def _hidden():\n    return 2\n"
    )
    entries = check_flow._flow_entries("nope", "", str(tmp_path))
    assert ("public_fn", "mod.py") in entries
    assert not any(name == "_hidden" for name, _ in entries)
