"""Providers: registry, plug-in loading, structured-output fallback."""

import pytest

from driftwatcher.config import loader
from driftwatcher.config.models import DriftConfig, ProfileConfig
from driftwatcher.llm import client, registry
from driftwatcher.llm.budget import Budget, BudgetExceeded
from driftwatcher.llm.providers.mock import MockProvider
from pydantic import BaseModel


class Reply(BaseModel):
    ok: bool = True


@pytest.fixture(autouse=True)
def _isolated():
    MockProvider.reset()
    registry.clear_cache()
    client.reset_ladder()
    token = loader._active.set(None)
    yield
    MockProvider.reset()
    registry.clear_cache()
    client.reset_ladder()
    loader._active.reset(token)


def _mock_config() -> DriftConfig:
    return DriftConfig.model_validate(
        {
            "llm": {
                "default_profile": "mock",
                "profiles": {
                    "mock": {
                        "provider": "mock",
                        "api_key_env": "MOCK_KEY",
                        "model": "mock-model",
                    }
                },
                "agents": {},
            }
        }
    )


def _use_mock() -> None:
    loader.set_active(_mock_config())


def test_registry_lookup_and_caching() -> None:
    profile = ProfileConfig(provider="mock", api_key_env="MOCK_KEY", model="m")
    first = registry.get(profile)
    second = registry.get(profile)
    assert isinstance(first, MockProvider)
    assert first is second


def test_dotted_path_loading() -> None:
    profile = ProfileConfig(
        provider="driftwatch.llm.providers.mock:MockProvider",
        api_key_env="MOCK_KEY",
        model="m",
    )
    assert isinstance(registry.get(profile), MockProvider)


def test_unknown_provider_rejected() -> None:
    profile = ProfileConfig(provider="no_such_provider", model="m")
    with pytest.raises(ValueError, match="unknown LLM provider"):
        registry.get(profile)


def test_mock_replies_validate() -> None:
    _use_mock()
    MockProvider.enqueue({"ok": True})
    out = client.call("L1.FeatureScout", "sys", Reply(), Reply)
    assert out.ok is True


def test_structured_output_downgrade_on_400() -> None:
    _use_mock()
    MockProvider.reject_modes = {"json_schema"}
    MockProvider.enqueue({"ok": True})
    out = client.call("L1.FeatureScout", "sys", Reply(), Reply)
    assert out.ok is True
    assert client._downgraded_mode == "json_object"


def test_second_failure_raises() -> None:
    _use_mock()
    MockProvider.enqueue("not json at all {{{")
    MockProvider.enqueue("still not json")
    with pytest.raises(Exception):  # noqa: BLE001, PT011
        client.call("L1.FeatureScout", "sys", Reply(), Reply)


def test_finish_reason_captured() -> None:
    from types import SimpleNamespace

    from driftwatcher.llm.providers.openai_compatible import to_llm_response
    from driftwatcher.config.models import ProfileConfig

    def fake_r(content, finish):
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=content),
                    finish_reason=finish,
                )
            ],
            model="m",
            usage=None,
            id="r1",
        )

    profile = ProfileConfig(provider="mock", api_key_env="X", model="m")
    assert (
        to_llm_response(fake_r("hi", "stop"), profile, 1).finish_reason
        == "stop"
    )
    assert (
        to_llm_response(fake_r("cut", "length"), profile, 1).finish_reason
        == "length"
    )


def test_truncated_reply_raises(monkeypatch) -> None:
    from driftwatcher.llm.types import LLMResponse

    _use_mock()
    monkeypatch.setattr(
        MockProvider,
        "complete",
        lambda self, req: LLMResponse(
            text='{"ok": true}',
            provider="mock",
            model="mock-model",
            finish_reason="length",
        ),
    )
    with pytest.raises(ValueError, match="truncated"):
        client.call("L1.FeatureScout", "sys", Reply(), Reply)


def test_ping_reports_profile() -> None:
    _use_mock()
    MockProvider.enqueue({"ok": True})
    result = client.ping(profile_name="mock")
    assert result["ok"] is True
    assert result["provider"] == "mock"
    assert result["model"] == "mock-model"
    assert result["mode"] == "json_schema"


def test_budget_check_raises() -> None:
    budget = Budget(max_calls=1, max_input_tokens_per_call=10)
    budget.check(5)
    budget.take()
    with pytest.raises(BudgetExceeded):
        budget.check()
    with pytest.raises(BudgetExceeded, match="too large"):
        Budget().check(10**9)


def test_anthropic_stub() -> None:
    from driftwatcher.llm.providers.anthropic import AnthropicProvider
    from driftwatcher.llm.types import LLMRequest

    provider = AnthropicProvider(
        ProfileConfig(provider="anthropic", api_key_env="X", model="y")
    )
    with pytest.raises(NotImplementedError):
        provider.complete(LLMRequest())
