"""Console (pretty/plain/json) and JSONL file sinks (plan sec. 8.1)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TextIO


def now_ts() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class ConsoleSink:
    def __init__(self, format: str = "pretty", stream: TextIO | None = None) -> None:
        self.format = format
        self.stream = stream

    def write(self, event: dict) -> None:
        import sys

        out = self.stream or sys.stdout
        if self.format == "json":
            out.write(json.dumps(event) + "\n")
        else:
            out.write(render_pretty(event, plain=self.format == "plain") + "\n")
        out.flush()


def render_pretty(event: dict, plain: bool = False) -> str:
    ts = event.get("ts", "")[11:19]
    level = str(event.get("level", "INFO"))
    agent = str(event.get("agent", ""))
    step = event.get("step")
    prefix = f"[{step}] " if step else ""
    run = event.get("run", "")
    kind = event.get("event", "")
    msg = str(event.get("message", ""))
    envelope = event.get("envelope")
    duration = event.get("duration_ms")

    if kind == "run_start":
        line = f"{run} >> {msg}"
    elif kind == "run_end":
        line = f"{run} << {msg}"
    elif agent:
        line = f"{prefix}{agent}  {msg}"
    else:
        line = f"{prefix}{msg}"
    tail = ""
    if duration is not None and kind == "step_end":
        tail += f" {duration}ms"
    if envelope:
        tail += f" envelope={envelope}"
    _ = plain  # pretty and plain share the layout; plain avoids color (none used)
    return f"{ts} {level:<5} {line}{tail}"


class FileSink:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a", encoding="utf-8")

    def write(self, event: dict) -> None:
        self.handle.write(json.dumps(event) + "\n")
        self.handle.flush()

    def close(self) -> None:
        try:
            self.handle.close()
        except ValueError:
            pass
