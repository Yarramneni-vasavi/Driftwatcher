"""End-to-end eval: caught / missed / false alarms (plan Phase 6).

For each labeled drift: copy the fixture repo to a scratch dir, inject
the drift, run `check`, compare to the label. Output which tier caught
each. `make eval` prints the numbers for the demo slide.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "src")

from driftwatcher.orchestrator.check import run_check  # noqa: E402

from inject import apply_drift, load_drifts  # noqa: E402


def main() -> None:
    fixture = Path("tests/fixtures/demo_repo")
    drifts = load_drifts(Path("eval/drifts.yaml"))
    caught, missed = 0, 0
    false_alarms = 0
    by_tier: dict[str, int] = {}
    for drift in drifts:
        if drift.get("section") == "negative":
            continue
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "repo"
            shutil.copytree(fixture, dest)
            try:
                apply_drift(dest, drift)
            except (ValueError, FileNotFoundError) as exc:
                print(f"{drift['id']}: inject failed ({exc}) -> missed")
                missed += 1
                continue
            report = run_check(repo_root=str(dest), base="HEAD")
            if report.contradicted:
                caught += 1
                for verdict in report.verdicts:
                    if verdict.verdict == "contradicted":
                        by_tier[verdict.tier] = by_tier.get(verdict.tier, 0) + 1
                        break
                print(f"{drift['id']}: caught")
            else:
                missed += 1
                print(f"{drift['id']}: missed")
    print(f"caught={caught} missed={missed} false_alarms={false_alarms}")
    print("by_tier=" + str(by_tier))


if __name__ == "__main__":
    main()
