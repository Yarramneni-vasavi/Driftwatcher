"""Per-run LLM call/token budget (architecture sec. 11, plan sec. 5.4/7).

On exhaustion remaining claims become `unverifiable` rather than failing
the build. Limits come from `llm.budget` in `driftwatch.config.yaml`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from ..config.models import DriftConfig


class BudgetExceeded(RuntimeError):
    pass


def estimate_tokens(chars: int) -> int:
    return max(1, chars // 4)


class Budget(BaseModel):
    max_calls: int = 200
    calls: int = 0
    max_input_tokens_per_call: int = 6000
    input_tokens_used: int = 0

    @classmethod
    def from_config(cls, config: DriftConfig | None) -> Budget:
        if config is None:
            return cls()
        return cls(
            max_calls=config.llm.budget.max_calls_per_run,
            max_input_tokens_per_call=(
                config.llm.budget.max_input_tokens_per_call
            ),
        )

    def take(self) -> bool:
        if self.calls >= self.max_calls:
            return False
        self.calls += 1
        return True

    def check(self, estimated_input_tokens: int = 0) -> None:
        if self.calls >= self.max_calls:
            raise BudgetExceeded(
                f"call budget exhausted ({self.calls}/{self.max_calls})"
            )
        if estimated_input_tokens > self.max_input_tokens_per_call:
            raise BudgetExceeded(
                f"input too large (~{estimated_input_tokens} tokens, "
                f"limit {self.max_input_tokens_per_call})"
            )

    def remaining(self) -> int:
        return max(0, self.max_calls - self.calls)
