"""Apply one labeled drift to a scratch copy of a repo (plan Phase 6).

Usage: python eval/inject.py <src> <drift-id> <dest>
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path


def load_drifts(path: Path) -> list[dict]:
    drifts: list[dict] = []
    current: dict = {}
    section = ""
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        if line.strip() in ("drifts:", "negative:"):
            section = line.strip().rstrip(":")
            continue
        if line.strip().startswith("- id:"):
            if current:
                drifts.append(current)
            current = {"section": section, "id": line.split(":", 1)[1].strip()}
        elif current and ":" in line and line.startswith("    "):
            key, _, value = line.strip().partition(":")
            current[key.strip()] = value.strip().strip("'\"")
    if current:
        drifts.append(current)
    return drifts


def apply_drift(repo: Path, drift: dict) -> None:
    kind = drift.get("kind", "")
    target = repo / drift["file"]
    if kind == "add-module":
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('"""New undocumented module."""\n', encoding="utf-8")
        return
    if not target.exists():
        raise FileNotFoundError(f"drift target missing: {target}")
    text = target.read_text(encoding="utf-8", errors="replace")
    if kind in ("rename", "behavior", "change-command"):
        old = drift.get("from", "")
        new = drift.get("to", "")
        if old not in text:
            raise ValueError(f"drift source text not found in {target}")
        target.write_text(text.replace(old, new), encoding="utf-8")
    elif kind == "remove-flag":
        flag = drift.get("flag", "")
        lines = [ln for ln in text.splitlines() if flag not in ln]
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    else:
        raise ValueError(f"unknown drift kind: {kind}")


def main() -> None:
    src, drift_id, dest = sys.argv[1], sys.argv[2], sys.argv[3]
    drifts = load_drifts(Path("eval/drifts.yaml"))
    match = next((d for d in drifts if d.get("id") == drift_id), None)
    if match is None:
        raise SystemExit(f"unknown drift id: {drift_id}")
    dest_path = Path(dest)
    if dest_path.exists():
        shutil.rmtree(dest_path)
    shutil.copytree(src, dest_path)
    apply_drift(dest_path, match)
    print(f"Applied {drift_id} to {dest}")


if __name__ == "__main__":
    main()
