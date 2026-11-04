"""Shared envelope for all agent-to-agent messages.

Plan sec. 4: every hop is an Envelope with a typed payload validated on
send and receive. Plain-text hand-offs are not allowed. Every payload
type implements log_summary() (rule 6); logs reference the envelope
file for the full payload.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Generic, TypeVar
from uuid import uuid4

from pydantic import BaseModel, Field
from typing import Literal


# Canonical agent identifiers (architecture sec. 4 + plan sec. 2).
AgentId = str

MessageType = str


class ErrorInfo(BaseModel):
    code: str
    message: str
    detail: str = ""

    def log_summary(self) -> dict:
        return {"code": self.code, "message": self.message}


T = TypeVar("T")


class Envelope(BaseModel, Generic[T]):
    schema_version: Literal["1"] = "1"
    msg_id: str = Field(default_factory=lambda: uuid4().hex)
    correlation_id: str = ""
    type: MessageType = ""
    sender: AgentId = ""
    recipient: AgentId = ""
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    payload: T
    error: ErrorInfo | None = None

    def with_error(self, code: str, message: str, detail: str = "") -> Envelope[T]:
        self.error = ErrorInfo(code=code, message=message, detail=detail)
        return self

    def log_summary(self) -> dict:
        from ..observability.summarize import summarize

        return {
            "type": self.type,
            "sender": self.sender,
            "recipient": self.recipient,
            "payload": summarize(self.payload),
        }


def make_envelope(
    payload: T,
    type: str,
    sender: str,
    recipient: str,
    correlation_id: str,
) -> Envelope[T]:
    return Envelope[T](
        correlation_id=correlation_id,
        type=type,
        sender=sender,
        recipient=recipient,
        payload=payload,
    )
