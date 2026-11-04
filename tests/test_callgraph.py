"""Deterministic tests for the B3.1 call graph (no LLM).

Pins: indexing of defs/imports/calls, reachable() depth and folder
boundary, external edges for stdlib/unknown calls, entry discovery
skipping privates and tests, and deterministic test-hint selection.
"""

from driftwatcher.agents.non_llm import callgraph


def _write_repo(root) -> None:
    (root / "helper.py").write_text(
        "def step_b(x):\n"
        "    if not x:\n"
        "        raise ValueError('bad')\n"
        "    return x\n"
    )
    (root / "main.py").write_text(
        "import os\n"
        "from helper import step_b\n"
        "from missing_mod import ghost\n"
        "\n"
        "def step_a(x):\n"
        "    ghost(x)\n"
        "    return step_b(x)\n"
        "\n"
        "def run(items):\n"
        "    total = 0\n"
        "    for it in items:\n"
        "        total += step_a(it)\n"
        "    return total\n"
        "\n"
        "def _private():\n"
        "    return 0\n"
    )
    (root / "test_main.py").write_text(
        "from main import run\n"
        "\n"
        "def test_run_totals():\n"
        "    assert run([1]) == 1\n"
        "\n"
        "def test_unrelated_other():\n"
        "    assert True\n"
    )


def test_index_records_defs_imports_calls(tmp_path) -> None:
    _write_repo(tmp_path)
    index = callgraph.index_folder("", str(tmp_path))
    assert "main.py" in index
    mod = index["main.py"]
    assert set(mod.defs) == {"step_a", "run", "_private"}
    assert mod.imports["step_b"] == "helper.step_b"
    callers = {c for calls in mod.calls.values() for c, _ in calls}
    assert callers == {"step_a", "step_b", "ghost"}


def test_reachable_follows_helpers_and_marks_external(tmp_path) -> None:
    _write_repo(tmp_path)
    index = callgraph.index_folder("", str(tmp_path))
    segments, edges = callgraph.reachable("main.py", "run", index)
    assert set(segments) == {"main.py", "helper.py"}
    internal = {(e.caller, e.callee) for e in edges if not e.external}
    assert ("run", "step_a") in internal
    assert ("step_a", "step_b") in internal
    external = {e.callee for e in edges if e.external}
    assert "ghost" in external
    assert "ValueError" in external


def test_reachable_respects_max_depth(tmp_path) -> None:
    _write_repo(tmp_path)
    index = callgraph.index_folder("", str(tmp_path))
    segments, _ = callgraph.reachable(
        "main.py", "run", index, max_depth=1
    )
    assert set(segments) == {"main.py"}


def test_entry_candidates_skip_private_and_tests(tmp_path) -> None:
    _write_repo(tmp_path)
    entries = callgraph.entry_candidates("", str(tmp_path))
    names = [name for name, _ in entries]
    assert "run" in names
    assert "step_a" in names
    assert "_private" not in names
    assert not any(name.startswith("test_") for name in names)
    assert not any("test_main" in f for _, f in entries)


def test_find_tests_selects_by_name_overlap(tmp_path) -> None:
    _write_repo(tmp_path)
    hints = callgraph.find_tests("", str(tmp_path), "run", "main")
    names = [h.name for h in hints]
    assert "test_run_totals" in names
    assert "test_unrelated_other" not in names
    assert all("test_main.py" in h.path for h in hints)
    assert all(h.body.strip() for h in hints)
