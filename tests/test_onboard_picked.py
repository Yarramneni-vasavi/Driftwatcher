"""Confirm step: comma-separated input maps onto features, unknown names kept."""

from driftwatcher.contracts.features import FeatureInfo
from driftwatcher.orchestrator.onboard import _apply_picked, _split_choices


def _feature(name: str) -> FeatureInfo:
    return FeatureInfo(name=name, folder=name)


def test_split_choices_splits_commas() -> None:
    assert _split_choices(["static_analyzer,diagram_analysis,agents"]) == {
        "static_analyzer",
        "diagram_analysis",
        "agents",
    }


def test_split_choices_accept_all_words_mean_accept_all() -> None:
    assert _split_choices(["accept all"]) == set()
    assert _split_choices(["all"]) == set()
    assert _split_choices(["agents, all"]) == {"agents"}


def test_apply_picked_keeps_unknown_names_as_new_features() -> None:
    result = _apply_picked([], {"agents", "static_analyzer"}, "typed")
    assert sorted((f.name, f.folder) for f in result) == [
        ("agents", "agents"),
        ("static_analyzer", "static_analyzer"),
    ]


def test_apply_picked_filters_known_and_adds_unknown() -> None:
    result = _apply_picked(
        [_feature("agents"), _feature("other")], {"agents", "new"}, "typed"
    )
    assert sorted(f.name for f in result) == ["agents", "new"]


def test_apply_picked_empty_accepts_all() -> None:
    features = [_feature("agents"), _feature("other")]
    assert [f.name for f in _apply_picked(features, set(), "typed")] == [
        "agents",
        "other",
    ]


def test_apply_picked_resolves_numbers() -> None:
    features = [_feature("agents"), _feature("other"), _feature("third")]
    assert [f.name for f in _apply_picked(features, {"1", "3"}, "typed")] == [
        "agents",
        "third",
    ]


def test_apply_picked_out_of_range_number_becomes_new_feature() -> None:
    result = _apply_picked([_feature("agents")], {"9"}, "typed")
    assert sorted(f.name for f in result) == ["9", "agents"]
