"""Agent protocol: handle(Envelope[In]) -> Envelope[Out] (plan sec. 4.1)."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel

from ..contracts.envelope import Envelope


class Agent(Protocol):
    def handle(self, env: Envelope[BaseModel]) -> Envelope[BaseModel]:
        ...
