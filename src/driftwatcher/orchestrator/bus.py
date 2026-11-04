"""Orchestrator bus: build, validate, persist, log envelopes (plan sec. 4).

Every envelope is persisted as JSON in
`.drift/runs/<correlation_id>/NN_<type>.json` so CI runs are replayable
and `fix` can read a past run. Sends and receives are logged at DEBUG
with type, sender, recipient, and file path (plan sec. 8.7).
"""

from __future__ import annotations

from contextvars import ContextVar
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ValidationError

from ..contracts.envelope import Envelope, ErrorInfo

_last_path: ContextVar[str | None] = ContextVar("bus_last_path", default=None)


def last_path() -> str | None:
    return _last_path.get()


def new_correlation_id() -> str:
    return uuid4().hex[:12]


def send(
    payload: BaseModel,
    type: str,
    sender: str,
    recipient: str,
    correlation_id: str,
    repo_root: str | Path = ".",
) -> Envelope:
    env: Envelope = Envelope(
        correlation_id=correlation_id,
        type=type,
        sender=sender,
        recipient=recipient,
        payload=payload,
    )
    path = persist(env, repo_root=repo_root)
    _debug(f"send {type} {sender} -> {recipient} {path}")
    return env


def receive(env: Envelope, payload_type: type[BaseModel]) -> BaseModel | ErrorInfo:
    try:
        if isinstance(env.payload, payload_type):
            out = env.payload
        else:
            out = payload_type.model_validate(env.payload)
        _debug(f"receive {env.type} ok as {payload_type.__name__}")
        return out
    except ValidationError as exc:
        _debug(f"receive {env.type} INVALID as {payload_type.__name__}")
        return ErrorInfo(
            code="validation_error",
            message=f"Invalid {payload_type.__name__}",
            detail=str(exc),
        )


def persist(env: Envelope, repo_root: str | Path = ".") -> Path:
    run_dir = Path(repo_root) / ".drift" / "runs" / env.correlation_id
    run_dir.mkdir(parents=True, exist_ok=True)
    existing = sorted(run_dir.glob("*.json"))
    seq = len(existing) + 1
    path = run_dir / f"{seq:02d}_{env.type}.json"
    path.write_text(env.model_dump_json(indent=2), encoding="utf-8")
    try:
        _last_path.set(str(path))
    except LookupError:
        pass
    return path


def _debug(message: str) -> None:
    from ..observability.logger import get_logger
    from ..observability.sinks import now_ts

    logger = get_logger()
    if logger is not None:
        logger.emit(
            {
                "ts": now_ts(),
                "level": "DEBUG",
                "run": logger.run_id,
                "step": "",
                "agent": "bus",
                "event": "bus",
                "feature": None,
                "message": message,
            }
        )
