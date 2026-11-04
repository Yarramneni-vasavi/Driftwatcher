"""Manual live smoke for mined-rule recall (run-2 regression).

Not part of the default suite: it needs a real repo plus an LLM key.
The user runs it and reports the output:

    set DRIFT_LIVE_SMOKE=1
    set REPO_PATH=V:\\projects\\OpenSource Contrib\\CodeBoarding   (Windows)
    poetry run pytest tests/test_miner_smoke_live.py -s

It mines the `agents` folder with the legacy miner and asserts the
diff_analyzer.py behaviors run 1 found (and run 2 lost) are present:
get_diff_data returning [] when the version file is missing, and
filter_diff keeping .py files.
"""

import os

import pytest

from driftwatcher.llm.budget import Budget
from driftwatcher.orchestrator import check as check_flow

REPO = os.environ.get("REPO_PATH", "")
NEEDS_LIVE = pytest.mark.skipif(
    os.environ.get("DRIFT_LIVE_SMOKE") != "1" or not REPO,
    reason="needs DRIFT_LIVE_SMOKE=1 and REPO_PATH=<codeboarding checkout>",
)


@NEEDS_LIVE
def test_live_miner_recalls_diff_analyzer_rules() -> None:
    rules = check_flow._mine_rules(
        "ai-interpretation", "agents", Budget(), "smoke", REPO
    )
    texts = [r.text for r in rules.rules]
    print(f"\nmined {len(texts)} rules")
    for text in texts:
        print(" -", text[:120])
    assert any("get_diff_data" in t for t in texts), (
        "get_diff_data rule missing: select starved diff_analyzer.py again"
    )
    assert any("filter_diff" in t for t in texts), (
        "filter_diff rule missing: select starved diff_analyzer.py again"
    )
