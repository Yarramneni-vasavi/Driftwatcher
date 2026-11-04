"""StepLogger and run context (plan sec. 8.7).

Run context (run id, step number, feature, budget) is carried in
`contextvars`, so any agent or the LLM client can log without passing
it around. With no active run the module is silent (unit-test safe).
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING, Any

from .sinks import ConsoleSink, FileSink, now_ts
from .summarize import format_params, summarize

if TYPE_CHECKING:
    from ..config.models import DriftConfig
    from ..llm.budget import Budget

LEVELS = {"TRACE": 0, "DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40}


@dataclass
class RunContext:
    run_id: str = ""
    command: str = ""
    step: str = ""
    total_steps: int = 0
    feature: str | None = None
    budget: Budget | None = None
    repo_root: str = "."


_current: ContextVar[RunContext | None] = ContextVar("drift_run", default=None)
_active_logger: ContextVar[StepLogger | None] = ContextVar(
    "drift_logger", default=None
)


def get_context() -> RunContext | None:
    return _current.get()


def get_logger() -> StepLogger | None:
    return _active_logger.get()


class StepLogger:
    def __init__(
        self,
        config: DriftConfig | None = None,
        run_id: str = "",
        repo_root: str = ".",
        stream: Any = None,
    ) -> None:
        from ..config.models import default_config

        self.config = config or default_config()
        self.run_id = run_id
        self.repo_root = repo_root
        self.console: ConsoleSink | None = None
        if self.config.logging.console.enabled:
            self.console = ConsoleSink(
                self.config.logging.console.format, stream=stream
            )
        self.file: FileSink | None = None
        if self.config.logging.file.enabled:
            log_dir = Path(repo_root) / self.config.logging.file.dir
            log_dir.mkdir(parents=True, exist_ok=True)
            self._prune(log_dir)
            self.file = FileSink(log_dir / f"{run_id}.jsonl")

    @property
    def max_chars(self) -> int:
        return self.config.logging.max_value_chars

    @property
    def max_items(self) -> int:
        return self.config.logging.max_list_items

    @property
    def redact_keys(self) -> tuple[str, ...]:
        return tuple(self.config.logging.redact_keys)

    def _prune(self, log_dir: Path) -> None:
        keep = self.config.logging.file.keep_last_runs
        files = sorted(
            log_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime
        )
        for stale in files[: max(0, len(files) - keep)]:
            try:
                stale.unlink()
            except OSError:
                pass

    def _passes(self, level: str, sink_min: str) -> bool:
        return LEVELS[level] >= LEVELS[sink_min]

    def emit(self, event: dict) -> None:
        level = event.get("level", "INFO")
        # TRACE excerpts go to the file sink only; console starts at DEBUG.
        console_min = (
            "DEBUG"
            if LEVELS[self.config.logging.level] < LEVELS["DEBUG"]
            else self.config.logging.level
        )
        if self.console is not None and self._passes(level, console_min):
            self.console.write(event)
        if self.file is not None and self._passes(
            level, self.config.logging.level
        ):
            self.file.write(event)

    def _base(self, level: str, agent: str, kind: str) -> dict:
        ctx = get_context()
        return {
            "ts": now_ts(),
            "level": level,
            "run": self.run_id,
            "step": ctx.step if ctx else "",
            "agent": agent,
            "event": kind,
            "feature": ctx.feature if ctx else None,
        }

    def _summarized(self, payload: Any) -> dict:
        return summarize(
            payload, self.max_chars, self.max_items, self.redact_keys
        )

    def run_start(self, message: str) -> None:
        self.emit({**self._base("INFO", "", "run_start"), "message": message})

    def run_end(self, message: str) -> None:
        self.emit({**self._base("INFO", "", "run_end"), "message": message})

    def step_start(self, agent: str, params: Any = None) -> None:
        self.emit(
            {
                **self._base("INFO", agent, "step_start"),
                "message": "start " + format_params(self._summarized(params or {})),
            }
        )

    def step_end(
        self,
        agent: str,
        result: Any = None,
        duration_ms: int | None = None,
        envelope: str | None = None,
    ) -> None:
        event = {
            **self._base("INFO", agent, "step_end"),
            "message": "ok " + format_params(self._summarized(result or {})),
            "result": self._summarized(result or {}),
        }
        if duration_ms is not None:
            event["duration_ms"] = duration_ms
        if envelope:
            event["envelope"] = envelope
        self.emit(event)

    def step_skip(self, agent: str, reason: str) -> None:
        self.emit(
            {
                **self._base("INFO", agent, "step_skip"),
                "message": f"skip {reason}",
            }
        )

    def step_error(self, agent: str, error: Exception, duration_ms: int) -> None:
        self.emit(
            {
                **self._base("ERROR", agent, "error"),
                "message": f"{type(error).__name__}: {error}",
                "duration_ms": duration_ms,
            }
        )

    def decision(self, agent: str, message: str, params: Any = None) -> None:
        self.emit(
            {
                **self._base("DEBUG", agent, "decision"),
                "message": message + (
                    " " + format_params(self._summarized(params)) if params else ""
                ),
            }
        )

    def llm_call(self, message: str, params: Any = None, trace: Any = None) -> None:
        self.emit(
            {
                **self._base("INFO", "LLM", "llm_call"),
                "message": message + (
                    " " + format_params(self._summarized(params)) if params else ""
                ),
            }
        )
        if trace is not None:
            self.emit(
                {
                    **self._base("TRACE", "LLM", "llm_call"),
                    "message": "excerpts " + format_params(self._summarized(trace)),
                }
            )

    def cache(self, message: str) -> None:
        self.emit({**self._base("DEBUG", "", "cache"), "message": message})

    def warning(self, agent: str, message: str) -> None:
        self.emit({**self._base("WARNING", agent, "warning"), "message": message})

    def error(self, agent: str, message: str) -> None:
        self.emit({**self._base("ERROR", agent, "error"), "message": message})

    def close(self) -> None:
        if self.file is not None:
            self.file.close()


def init_run(
    config: DriftConfig,
    run_id: str,
    command: str,
    total_steps: int = 0,
    repo_root: str = ".",
    budget: Budget | None = None,
    stream: Any = None,
) -> tuple[StepLogger, RunContext]:
    logger = StepLogger(config, run_id, repo_root, stream=stream)
    ctx = RunContext(
        run_id=run_id, command=command, total_steps=total_steps,
        budget=budget, repo_root=repo_root,
    )
    _current.set(ctx)
    _active_logger.set(logger)
    return logger, ctx


def end_run() -> None:
    logger = _active_logger.get()
    if logger is not None:
        logger.close()
    _current.set(None)
    _active_logger.set(None)


class StepTracker:
    """`[n/N]` step counting from the workflow definition (plan sec. 8.6)."""

    def __init__(self, logger: StepLogger | None, steps: list[str]) -> None:
        self.logger = logger
        self.steps = steps

    def use_feature(self, feature: str | None) -> None:
        ctx = get_context()
        if ctx is not None:
            ctx.feature = feature

    def step(self, agent: str, params: Any = None) -> StepSpan:
        ctx = get_context()
        index = self.steps.index(agent) + 1 if agent in self.steps else 0
        if ctx is not None:
            ctx.step = f"{index}/{len(self.steps)}"
        if self.logger is not None:
            self.logger.step_start(agent, params)
        return StepSpan(self.logger, agent)


class StepSpan:
    def __init__(self, logger: StepLogger | None, agent: str) -> None:
        self.logger = logger
        self.agent = agent
        self.t0 = perf_counter()
        self.envelope: str | None = None

    def __enter__(self) -> StepSpan:
        return self

    def ok(self, result: Any = None, envelope: str | None = None) -> None:
        if self.logger is not None:
            self.logger.step_end(
                self.agent, result, self._ms(), envelope or self.envelope
            )

    def skip(self, reason: str) -> None:
        if self.logger is not None:
            self.logger.step_skip(self.agent, reason)

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        if exc is not None and self.logger is not None and isinstance(exc, Exception):
            self.logger.step_error(self.agent, exc, self._ms())
        return False

    def _ms(self) -> int:
        return int((perf_counter() - self.t0) * 1000)


def active_budget() -> Budget | None:
    ctx = get_context()
    return ctx.budget if ctx else None


def log_path() -> Path | None:
    logger = get_logger()
    if logger is not None and logger.file is not None:
        return logger.file.path
    return None
