"""Logging: redaction, truncation, step events, JSONL validity."""

import io
import json

from driftwatcher.config.models import DriftConfig
from driftwatcher.contracts.verdicts import Evidence, Verdict
from driftwatcher.observability import viewer as log_viewer
from driftwatcher.observability.logger import (
    StepLogger,
    StepTracker,
    end_run,
    init_run,
)
from driftwatcher.observability.summarize import format_params, summarize


def _config(**overrides) -> DriftConfig:
    base = {
        "logging": {
            "level": "INFO",
            "console": {"enabled": True, "format": "plain"},
            "file": {"enabled": True, "dir": ".drift/logs", "keep_last_runs": 20},
        }
    }
    base["logging"].update(overrides.pop("logging", {}))
    base.update(overrides)
    return DriftConfig.model_validate(base)


def test_redaction() -> None:
    out = summarize(
        {"api_key": "abc123", "nested": {"auth_token": "xyz"}, "ok": "fine"},
        redact_keys=("api_key", "token"),
    )
    assert out == {"api_key": "***", "nested": {"auth_token": "***"}, "ok": "fine"}


def test_redaction_case_insensitive() -> None:
    out = summarize({"Authorization": "Bearer zzz"}, redact_keys=("authorization",))
    assert out == {"Authorization": "***"}


def test_truncation() -> None:
    out = summarize({"text": "x" * 200}, max_chars=120)
    assert out == {"text": "x" * 120 + "...(200 chars)"}


def test_list_count_and_first_items() -> None:
    out = summarize({"files": ["a", "b", "c", "d", "e"]}, max_items=3)
    assert out == {"files": {"count": 5, "items": ["a", "b", "c"]}}


def test_payload_log_summary_used() -> None:
    verdict = Verdict(
        claim_id="c1", verdict="supported",
        evidence=[Evidence(file="a.py", line=3)],
        tier="deterministic",
    )
    out = summarize(verdict)
    assert out["verdict"] == "supported"
    assert out["evidence"] == ["a.py:3"]


def test_step_events_with_params(tmp_path) -> None:
    stream = io.StringIO()
    logger, _ctx = init_run(
        _config(), "run-1", "check", repo_root=str(tmp_path), stream=stream
    )
    try:
        tracker = StepTracker(logger, ["N4.Router"])
        with tracker.step("N4.Router", {"base": "origin/main"}) as span:
            span.ok({"cases": {"auth": "both"}})
        logger.run_end("done")
    finally:
        end_run()
    lines = log_viewer.read_events(tmp_path / ".drift" / "logs" / "run-1.jsonl")
    kinds = [e["event"] for e in lines]
    assert "step_start" in kinds and "step_end" in kinds and "run_end" in kinds
    assert all(set(e) >= {"ts", "level", "run", "agent", "event"} for e in lines)
    start = next(e for e in lines if e["event"] == "step_start")
    assert "origin/main" in start["message"]
    assert "[1/1]" in start.get("step", "")
    console = stream.getvalue()
    assert "N4.Router" in console


def test_level_filtering(tmp_path) -> None:
    stream = io.StringIO()
    logger, _ctx = init_run(
        _config(), "run-2", "check", repo_root=str(tmp_path), stream=stream
    )
    try:
        logger.decision("N4.Router", "auth: case=both")
        logger.warning("N8.EvidenceValidator", "rejected claim=c1")
    finally:
        end_run()
    console = stream.getvalue()
    assert "rejected claim=c1" in console
    assert "case=both" not in console  # DEBUG hidden at INFO
    events = log_viewer.read_events(tmp_path / ".drift" / "logs" / "run-2.jsonl")
    assert any(e["event"] == "warning" for e in events)
    assert not any(e["event"] == "decision" for e in events)


def test_trace_file_only(tmp_path) -> None:
    stream = io.StringIO()
    config = _config()
    config.logging.level = "TRACE"
    logger, _ctx = init_run(
        config, "run-3", "check", repo_root=str(tmp_path), stream=stream
    )
    try:
        logger.llm_call("profile=mock", trace={"reply": "secret-excerpt"})
    finally:
        end_run()
    assert "secret-excerpt" not in stream.getvalue()
    events = log_viewer.read_events(tmp_path / ".drift" / "logs" / "run-3.jsonl")
    assert any(
        e["level"] == "TRACE" and "secret-excerpt" in e["message"] for e in events
    )


def test_viewer_filter_and_render(tmp_path) -> None:
    stream = io.StringIO()
    logger, _ctx = init_run(
        _config(), "run-4", "check", repo_root=str(tmp_path), stream=stream
    )
    try:
        StepTracker(logger, ["N4.Router", "N7.RuleChecker"])
        logger.step_start("N4.Router", {})
        logger.step_start("N7.RuleChecker", {})
    finally:
        end_run()
    path = tmp_path / ".drift" / "logs" / "run-4.jsonl"
    events = log_viewer.filter_events(log_viewer.read_events(path), agent="N7")
    assert events and all("N7" in e["agent"] for e in events)
    rendered = log_viewer.render(events)
    assert "N7.RuleChecker" in rendered


def test_format_params() -> None:
    assert format_params({"a": "both", "b": 3}) == "a=both b=3"
