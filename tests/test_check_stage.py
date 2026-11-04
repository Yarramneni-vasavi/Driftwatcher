"""CHECK stage: B1 noise filters, entry points, endpoint gate, exit codes."""

from driftwatcher.agents.non_llm import rule_claims
from driftwatcher.agents.non_llm.reporter import build as build_report
from driftwatcher.agents.non_llm.reporter import exit_code, render_markdown
from driftwatcher.contracts.claims import DocText
from driftwatcher.contracts.envelope import Envelope
from driftwatcher.contracts.mapping import DriftFile, FeatureMapping
from driftwatcher.contracts.rules import (
    BusinessRule,
    RuleSet,
    SelectedFunctions,
)
from driftwatcher.contracts.verdicts import Verdict
from driftwatcher.orchestrator import check as check_flow


def _doc(lines):
    return DocText(doc_path="d.md", feature="f1", lines=lines)


def test_import_line_tokens_skipped() -> None:
    claims = rule_claims.extract(
        _doc(["import `os` and `sys`", "from `agents.agent` import X"])
    ).claims
    assert [c.text for c in claims] == []


def test_teardown_and_spec_paths_skipped() -> None:
    claims = rule_claims.extract(
        _doc(["see `conftest.py`", "run `teardown.sh`", "open `x.spec.ts`"])
    ).claims
    assert claims == []


def test_near_duplicate_claims_merged() -> None:
    claims = rule_claims.extract(
        _doc(["Use `create-session` today", "Use `create session` again"])
    ).claims
    assert [c.text for c in claims] == ["create-session"]


def test_entry_points_resolve_and_missing_reported(
    monkeypatch, tmp_path
) -> None:
    (tmp_path / "a.py").write_text("def run():\n    return 1\n")
    mapping = DriftFile()
    mapping.features["f1"] = FeatureMapping(
        folder="", entry_points=["run()", "ghost()"]
    )
    monkeypatch.setattr(
        check_flow.mapping_store, "read", lambda *a, **k: mapping
    )
    found, missing = check_flow._entry_points_for("f1", "", str(tmp_path))
    assert found == {"run()": "a.py"}
    assert missing == ["ghost()"]


def test_endpoint_claim_detection() -> None:
    from driftwatcher.contracts.claims import Claim

    assert check_flow._endpoint_claim(
        Claim(text="GET https://x/api/v1/items returns 200")
    )
    assert check_flow._endpoint_claim(Claim(text="the /api/items endpoint"))
    assert not check_flow._endpoint_claim(Claim(text="saves the file"))


def test_parallel_preserves_order() -> None:
    out = check_flow._run_parallel([1, 2, 3], lambda i, x: x * 10)
    assert out == [10, 20, 30]
    assert check_flow._run_parallel([], lambda i, x: x) == []


def test_gap_dedupe_in_miner(monkeypatch, tmp_path) -> None:
    rules = RuleSet(rules=[
        BusinessRule(feature="f", kind="negative", text="Fails when x is null",
                     file="a.py", line=1),
        BusinessRule(feature="f", kind="negative", text="Fails when X is NULL!",
                     file="a.py", line=5),
    ])
    monkeypatch.setattr(
        check_flow.l7_miner, "select",
        lambda req, r, c: Envelope(
            correlation_id="c", type="T",
            payload=SelectedFunctions(names=["f"]),
        ),
    )
    monkeypatch.setattr(
        check_flow.l7_miner, "extract",
        lambda req, r, c: Envelope(
            correlation_id="c", type="T", payload=rules
        ),
    )
    (tmp_path / "a.py").write_text("def f(x):\n    return x\n")
    got = check_flow._mine_rules(
        "f", "", check_flow.Budget(), "c", str(tmp_path)
    )
    assert len(got.rules) == 1


def test_exit_code_section_10() -> None:
    """Impl plan sec. 10: warn-only is 0 even with many unverifiable;
    only enforce + contradiction is 1."""
    many = build_report(
        [
            Verdict(
                claim_id=f"c{i}", verdict="unverifiable",
                tier="judge",
            )
            for i in range(10)
        ],
        mode="warn",
    )
    assert many.unverifiable == 10
    assert exit_code(many) == 0
    enforced = build_report(
        [Verdict(
            claim_id="c1", verdict="contradicted", tier="judge"
        )],
        mode="enforce",
    )
    assert exit_code(enforced) == 1
    no_finding = build_report(
        [Verdict(
            claim_id="c1", verdict="contradicted", tier="judge"
        )],
        mode="warn",
    )
    assert exit_code(no_finding) == 0


def test_feature_status_independent_of_exit_code() -> None:
    drift = build_report(
        [Verdict(
            claim_id="g1", verdict="gap", feature="a",
            reason="missing thing", tier="judge",
        )],
        mode="warn", feature_names=["a"],
    )
    assert drift.features[0].status == "drift"
    assert exit_code(drift) == 0
    unknown = build_report(
        [Verdict(
            claim_id="c1", verdict="unverifiable", feature="a",
            tier="judge",
        )],
        mode="warn", feature_names=["a"],
    )
    assert unknown.features[0].status == "unverified"
    assert exit_code(unknown) == 0


def test_report_groups_by_feature() -> None:
    report = build_report(
        [
            Verdict(
                claim_id="c2", verdict="supported", feature="b",
                tier="deterministic",
            ),
            Verdict(
                claim_id="c1", verdict="supported", feature="a",
                tier="deterministic",
            ),
            Verdict(
                claim_id="g1", verdict="gap", feature="a",
                reason="missing thing", tier="judge",
            ),
        ],
        feature_names=["a", "b"],
    )
    assert report.gaps == 1
    by_name = {f.name: f for f in report.features}
    assert by_name["a"].status == "drift"
    assert by_name["a"].gaps == 1
    assert by_name["b"].status == "clean"
    assert by_name["b"].supported == 1
    text = render_markdown(report)
    assert "| Feature | Claim | Verdict | Evidence |" in text
    assert "|---|---|---|---|" in text
    assert text.index("| a | c1 |") < text.index("| b | c2 |")
    assert "Undocumented behaviors" in text
    assert "gap-abcdef" not in text
