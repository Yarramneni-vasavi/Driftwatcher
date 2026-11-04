"""Provider registry builtin paths must point at the real package."""

from driftwatcher.llm import registry


def test_builtin_modules_live_under_driftwatcher() -> None:
    assert registry._BUILTIN_MODULES
    for name, module_path in registry._BUILTIN_MODULES.items():
        assert module_path.startswith("driftwatcher."), name


def test_mock_provider_resolves() -> None:
    cls = registry._resolve_class("mock")
    assert hasattr(cls, "complete")
