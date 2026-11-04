"""Config: precedence, secret redaction, lazy env-var check (plan sec. 12)."""

import pytest

from driftwatcher.config import loader
from driftwatcher.config.models import DriftConfig


def _write(path, text: str) -> str:
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_file_values_load(tmp_path) -> None:
    cfg_file = _write(
        tmp_path / "driftwatch.config.yaml",
        "logging:\n  level: DEBUG\ncheck:\n  default_mode: enforce\n",
    )
    config, _ = loader.load(config_path=cfg_file, repo_root=str(tmp_path))
    assert config.logging.level == "DEBUG"
    assert config.check.default_mode == "enforce"
    # Untouched sections fall back to built-in defaults.
    assert config.llm.default_profile == "meta_api"


def test_env_beats_file(tmp_path, monkeypatch) -> None:
    cfg_file = _write(
        tmp_path / "driftwatch.config.yaml", "logging:\n  level: DEBUG\n"
    )
    monkeypatch.setenv("DRIFT_LOG_LEVEL", "WARNING")
    config, sources = loader.load(config_path=cfg_file, repo_root=str(tmp_path))
    assert config.logging.level == "WARNING"
    assert sources["logging.level"] == "env"


def test_flag_beats_env(tmp_path, monkeypatch) -> None:
    cfg_file = _write(
        tmp_path / "driftwatch.config.yaml", "logging:\n  level: DEBUG\n"
    )
    monkeypatch.setenv("DRIFT_LOG_LEVEL", "WARNING")
    config, sources = loader.load(
        config_path=cfg_file, log_level="ERROR", repo_root=str(tmp_path)
    )
    assert config.logging.level == "ERROR"
    assert sources["logging.level"] == "flag"


def test_profile_flag_and_env(tmp_path, monkeypatch) -> None:
    config, sources = loader.load(profile="meta_api", repo_root=str(tmp_path))
    assert config.llm.default_profile == "meta_api"
    assert sources["llm.default_profile"] == "flag"
    monkeypatch.setenv("DRIFT_LLM_PROFILE", "meta_api")
    config2, sources2 = loader.load(repo_root=str(tmp_path))
    assert config2.llm.default_profile == "meta_api"
    assert sources2["llm.default_profile"] == "env"


def test_unknown_profile_rejected(tmp_path) -> None:
    with pytest.raises(ValueError, match="unknown profile"):
        loader.load(profile="nope", repo_root=str(tmp_path))


def test_invalid_key_says_what_is_wrong(tmp_path) -> None:
    cfg_file = _write(
        tmp_path / "driftwatch.config.yaml", "logging:\n  level: CHATTY\n"
    )
    with pytest.raises(ValueError):
        loader.load(config_path=cfg_file, repo_root=str(tmp_path))


def test_secrets_never_printed(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BASETEN_API_KEY", "super-secret-value")
    config, _ = loader.load(repo_root=str(tmp_path))
    view = loader.redacted_view(config)
    text = str(view)
    assert "super-secret-value" not in text
    assert view["keys"]["baseten"]["api_key_env"] == "BASETEN_API_KEY"
    assert view["keys"]["baseten"]["api_key_set"] is True


def test_missing_key_only_fails_for_used_profile(tmp_path, monkeypatch) -> None:
    from driftwatcher.llm import registry
    from driftwatcher.llm.providers.openai_compatible import MissingKeyError

    monkeypatch.delenv("BASETEN_API_KEY", raising=False)
    # Loading and unrelated work are fine without any key set.
    config, _ = loader.load(repo_root=str(tmp_path))
    assert config.llm.default_profile == "meta_api"
    # Only first use of the profile raises, naming the variable.
    registry.clear_cache()
    with pytest.raises(MissingKeyError, match="BASETEN_API_KEY"):
        registry.get(config.llm.profiles["baseten"])


def test_agent_profile_resolution() -> None:
    from driftwatcher.config.models import default_config

    loader.set_active(default_config())
    assert loader.normalize_agent_key("L4.Judge") == "judge"
    assert loader.normalize_agent_key("L2.DocMapper") == "doc_mapper"
    name, profile = loader.resolve_profile("L4.Judge")
    assert name == "meta_api"
    assert profile.model == "muse-spark-1.1"
    name2, _ = loader.resolve_profile("L1.FeatureScout")
    assert name2 == "meta_api"
    name3, prof3 = loader.resolve_profile("L4.Judge", model_override="x-1")
    assert name3 == "meta_api" and prof3.model == "x-1"


def test_default_config_validates() -> None:
    assert isinstance(DriftConfig.model_validate({}), DriftConfig)
