"""Envelope and payload validation, round-trip JSON (plan sec. 9)."""

from driftwatcher.contracts.changes import ChangeSet, ChangedFile
from driftwatcher.contracts.claims import Claim
from driftwatcher.contracts.envelope import Envelope
from driftwatcher.contracts.verdicts import Evidence, Verdict


def test_envelope_round_trip() -> None:
    payload = ChangeSet(
        base="origin/main",
        head="abc123",
        files=[ChangedFile(path="services/auth/session.py", status="M")],
    )
    env: Envelope[ChangeSet] = Envelope(
        correlation_id="run-1",
        type="ChangeSet",
        sender="N2.ChangeDetector",
        recipient="N4.Router",
        payload=payload,
    )
    raw = env.model_dump_json()
    back = Envelope[ChangeSet].model_validate_json(raw)
    assert back.correlation_id == "run-1"
    assert isinstance(back.payload, ChangeSet)
    assert back.payload.files[0].path == "services/auth/session.py"


def test_verdict_requires_valid_label() -> None:
    ok = Verdict(
        claim_id="x", verdict="supported",
        evidence=[Evidence(file="a.py", line=1)],
        tier="deterministic",
    )
    assert ok.verdict == "supported"
    try:
        Verdict(claim_id="x", verdict="bogus", tier="judge")  # type: ignore[arg-type]
    except ValueError:
        pass
    else:
        raise AssertionError("invalid verdict label must fail validation")


def test_verdict_claim_id_and_tier_required() -> None:
    try:
        Verdict(verdict="supported", tier="deterministic")
    except ValueError:
        pass
    else:
        raise AssertionError("missing claim_id must fail validation")
    try:
        Verdict(claim_id="", verdict="supported", tier="deterministic")
    except ValueError:
        pass
    else:
        raise AssertionError("empty claim_id must fail validation")
    try:
        Verdict(claim_id="x", verdict="supported")  # type: ignore[call-arg]
    except ValueError:
        pass
    else:
        raise AssertionError("missing tier must fail validation")


def test_claim_id_stable() -> None:
    a = Claim.make_id("d.md", 3, "hello")
    assert a == Claim.make_id("d.md", 3, "hello")
    assert a != Claim.make_id("d.md", 4, "hello")
