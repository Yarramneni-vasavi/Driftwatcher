"""Reverse direction: outline mining, gaps, budget behavior."""

from driftwatcher.agents.non_llm.code_outline import build
from driftwatcher.contracts.envelope import Envelope
from driftwatcher.contracts.features import DocMatch
from driftwatcher.contracts.rules import BusinessRule, RuleSet, SelectedFunctions
from driftwatcher.llm.budget import Budget
from driftwatcher.orchestrator import check as check_flow


SAMPLE = '''"""Auth service."""


def create_session(user_id):
    """Create a session for a user."""
    if user_id is None:
        raise SessionError("user_id required")
    assert isinstance(user_id, str), "must be text"
    return _store(user_id)


def helper(items):
    return [x for x in items]
'''


def _env(payload):
    return Envelope(correlation_id="c", type="T", payload=payload)


def _rules():
    return RuleSet(feature="auth", rules=[
        BusinessRule(
            feature="auth", kind="negative",
            text="create_session throws SessionError when user_id is null",
            file="session.py", line=7,
        ),
        BusinessRule(
            feature="auth", kind="positive",
            text="sessions need a user",
            file="session.py", line=5,
        ),
    ])


def _stub_miner(monkeypatch, judge_replies):
    monkeypatch.setattr(
        check_flow.l7_miner, "select",
        lambda req, recipient, correlation: _env(
            SelectedFunctions(names=["create_session"])
        ),
    )
    monkeypatch.setattr(
        check_flow.l7_miner, "extract",
        lambda req, recipient, correlation: _env(_rules()),
    )
    calls = {"n": 0}

    def fake_judge(req, recipient, correlation):
        reply = judge_replies[min(calls["n"], len(judge_replies) - 1)]
        calls["n"] += 1
        return _env(reply)

    monkeypatch.setattr(check_flow.l7_miner, "judge", fake_judge)
    return calls


def _repo(tmp_path) -> str:
    (tmp_path / "session.py").write_text(SAMPLE)
    (tmp_path / "SKILL.md").write_text("# Auth\nSessions need a user.\n")
    return str(tmp_path)


def test_outline_finds_guards(tmp_path) -> None:
    (tmp_path / "session.py").write_text(SAMPLE)
    outline = build("", str(tmp_path))
    by_name = {u.name: u for u in outline.units}
    assert set(by_name) >= {"create_session", "helper"}
    guards = {(g.kind, g.line) for g in by_name["create_session"].guards}
    assert ("raise", 7) in guards
    assert ("assert", 8) in guards
    assert by_name["create_session"].signature == "create_session(user_id)"
    assert by_name["helper"].guards == []


def test_outline_skips_broken_files(tmp_path) -> None:
    (tmp_path / "broken.py").write_text("def oops(:\n")
    assert build("", str(tmp_path)).units == []


def test_outline_handles_classes(tmp_path) -> None:
    (tmp_path / "m.py").write_text(
        "class MetaAgent(BaseAgent):\n"
        '    """Coordinates agents."""\n'
        "    def run(self):\n"
        "        if not self.ready:\n"
        '            raise RuntimeError("not ready")\n'
    )
    by_name = {u.name: u for u in build("", str(tmp_path)).units}
    assert by_name["MetaAgent"].kind == "class"
    assert by_name["MetaAgent"].signature == "MetaAgent(BaseAgent)"
    assert by_name["MetaAgent"].docstring == "Coordinates agents."
    assert by_name["run"].signature == "run(self)"
    assert {(g.kind, g.line) for g in by_name["run"].guards} == {
        ("raise", 5)
    }


def test_gap_only_for_undocumented_rule(monkeypatch, tmp_path) -> None:
    calls = _stub_miner(monkeypatch, [
        DocMatch(feature="auth", doc="", match=False, quote="", confidence=0.9),
        DocMatch(
            feature="auth", doc="SKILL.md", match=True,
            quote="Sessions need a user.", confidence=0.9,
        ),
    ])
    verdicts = check_flow._reverse_feature(
        "auth", "", ["SKILL.md"], Budget(), "corr", _repo(tmp_path),
    )
    assert calls["n"] == 2
    assert [(v.verdict, v.feature) for v in verdicts] == [("gap", "auth")]
    gap = verdicts[0]
    assert gap.tier == "behavioral"
    assert gap.evidence and (gap.evidence[0].file, gap.evidence[0].line) == (
        "session.py", 8,
    )
    assert "null" in gap.reason


def test_budget_exhaustion_yields_unverifiable(monkeypatch, tmp_path) -> None:
    _stub_miner(monkeypatch, [
        DocMatch(feature="auth", doc="", match=False, quote="", confidence=0.9),
    ])
    verdicts = check_flow._reverse_feature(
        "auth", "", ["SKILL.md"], Budget(max_calls=2), "corr", _repo(tmp_path),
    )
    assert [(v.verdict, v.feature) for v in verdicts] == [
        ("unverifiable", "auth"), ("unverifiable", "auth"),
    ]
    assert all("budget exhausted" in v.reason for v in verdicts)


def test_no_docs_means_no_reverse_check(monkeypatch, tmp_path) -> None:
    _stub_miner(monkeypatch, [])
    assert check_flow._reverse_feature(
        "auth", "", [], Budget(), "corr", _repo(tmp_path)
    ) == []
