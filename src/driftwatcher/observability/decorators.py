"""@logged_step for agents (plan sec. 8.7).

Wraps `handle(env)`: logs step start with the payload summary, then
step end with the output summary and envelope path, or a step error.
With no active run the function passes through untouched.
"""

from __future__ import annotations

from functools import wraps
from time import perf_counter
from typing import Callable

from .logger import get_context, get_logger


def logged_step(agent_id: str) -> Callable:
    def deco(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(env):  # noqa: ANN001, ANN202
            logger = get_logger()
            if logger is None:
                return fn(env)
            from .summarize import summarize

            logger.step_start(agent_id, summarize(env.payload))
            t0 = perf_counter()
            try:
                out = fn(env)
            except Exception as exc:  # noqa: BLE001
                logger.step_error(
                    agent_id, exc, int((perf_counter() - t0) * 1000)
                )
                raise
            envelope = _last_envelope()
            logger.step_end(
                agent_id,
                summarize(getattr(out, "payload", {})),
                int((perf_counter() - t0) * 1000),
                envelope=envelope,
            )
            return out

        return wrapper

    return deco


def _last_envelope() -> str | None:
    try:
        from ..orchestrator import bus as _bus

        return _bus.last_path()
    except Exception:  # noqa: BLE001
        return None


def use_feature(feature: str | None) -> None:
    ctx = get_context()
    if ctx is not None:
        ctx.feature = feature
