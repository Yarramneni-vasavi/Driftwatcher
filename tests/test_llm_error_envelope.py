"""run_llm surfaces LLM failures as error envelopes, never a ValidationError."""

from pydantic import BaseModel

from driftwatcher.agents.llm import base_llm_agent
from driftwatcher.llm import client as llm_client


class Strict(BaseModel):
    feature: str
    doc: str


def test_llm_error_envelope_for_strict_schema(monkeypatch) -> None:
    monkeypatch.setattr(llm_client, "load_prompt", lambda *a, **k: "prompt")

    def boom(*a, **k):
        raise RuntimeError("MODEL_API_KEY is not set")

    monkeypatch.setattr(llm_client, "call", boom)
    env = base_llm_agent.run_llm(
        "T.Agent", "x.txt", Strict(feature="f", doc="d"),
        Strict, "Orchestrator", "corr-1",
    )
    assert env.error is not None
    assert env.error.code == "llm_error"
    assert "MODEL_API_KEY" in env.error.message
    assert isinstance(env.payload, Strict)
