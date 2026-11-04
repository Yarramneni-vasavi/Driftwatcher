"""`driftwatch logs` filtering and pretty-print (plan sec. 8.7)."""

from __future__ import annotations

import json
from pathlib import Path

from ..observability.logger import LEVELS
from ..observability.sinks import render_pretty


def log_dir_for(repo_root: str | Path, log_dir: str = ".drift/logs") -> Path:
    return Path(repo_root) / log_dir


def resolve_run_file(
    repo_root: str | Path, run: str, log_dir: str = ".drift/logs"
) -> Path | None:
    directory = log_dir_for(repo_root, log_dir)
    if run in ("latest", "last"):
        files = sorted(
            directory.glob("*.jsonl"), key=lambda p: p.stat().st_mtime
        )
        return files[-1] if files else None
    candidate = directory / f"{run}.jsonl"
    if candidate.exists():
        return candidate
    candidates = list(directory.glob(f"{run}*.jsonl"))
    return candidates[0] if candidates else None


def read_events(path: str | Path) -> list[dict]:
    events: list[dict] = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def filter_events(
    events: list[dict],
    agent: str | None = None,
    feature: str | None = None,
    level: str = "INFO",
) -> list[dict]:
    threshold = LEVELS.get(level.upper(), 20)
    out: list[dict] = []
    for event in events:
        if LEVELS.get(str(event.get("level", "INFO")), 20) < threshold:
            continue
        if agent and agent not in str(event.get("agent", "")):
            continue
        if feature and event.get("feature") != feature:
            continue
        out.append(event)
    return out


def render(
    events: list[dict], format: str = "pretty", follow: bool = False
) -> str:
    _ = follow
    if format == "json":
        return "\n".join(json.dumps(e) for e in events)
    return "\n".join(render_pretty(e, plain=format == "plain") for e in events)
