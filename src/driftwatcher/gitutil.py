"""Thin wrappers over the git CLI (plan sec. 1: subprocess, no extra dep)."""

from __future__ import annotations

import subprocess
from pathlib import Path


def _run(args: list[str], cwd: str | Path = ".") -> str:
    out = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    if out.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {out.stderr.strip()}")
    return out.stdout.strip()


def ls_md_files(repo_root: str | Path = ".") -> list[str]:
    out = _run(["ls-files", "*.md"], cwd=repo_root)
    return [line for line in out.splitlines() if line.strip()]


def diff_name_only(base: str, head: str = "HEAD", repo_root: str | Path = ".") -> list[str]:
    out = _run(["diff", "--name-only", f"{base}...{head}"], cwd=repo_root)
    return [line for line in out.splitlines() if line.strip()]


def diff_name_status(
    base: str, head: str = "HEAD", repo_root: str | Path = "."
) -> list[tuple[str, str]]:
    out = _run(["diff", "--name-status", f"{base}...{head}"], cwd=repo_root)
    rows: list[tuple[str, str]] = []
    for line in out.splitlines():
        parts = line.split("\t", 1)
        if len(parts) == 2:
            rows.append((parts[0].strip(), parts[1].strip()))
    return rows


def hash_object(path: str, repo_root: str | Path = ".") -> str:
    return _run(["hash-object", path], cwd=repo_root)


def list_tracked(repo_root: str | Path = ".") -> set[str]:
    out = _run(["ls-files"], cwd=repo_root)
    return {line for line in out.splitlines() if line.strip()}


def worktree_status(repo_root: str | Path = ".") -> list[tuple[str, str]]:
    """Staged + unstaged + untracked paths as (status, path) rows."""
    out = _run(
        ["status", "--porcelain=v1", "--untracked-files=all"], cwd=repo_root
    )
    rows: list[tuple[str, str]] = []
    for line in out.splitlines():
        if len(line) < 4:
            continue
        index, worktree, rest = line[0], line[1], line[3:]
        if " -> " in rest:
            rest = rest.rsplit(" -> ", 1)[-1]
        rest = rest.strip().strip('"')
        if not rest:
            continue
        if index == "?" and worktree == "?":
            rows.append(("untracked", rest))
        elif index == "U" or worktree == "U":
            rows.append(("unmerged", rest))
        else:
            rows.append(("modified", rest))
    return rows


def rev_parse_head_folder(folder: str, repo_root: str | Path = ".") -> str:
    return _run(["rev-parse", f"HEAD:{folder}"], cwd=repo_root)


def rev_parse_head(repo_root: str | Path = ".") -> str:
    return _run(["rev-parse", "HEAD"], cwd=repo_root)


def rev_parse_toplevel(repo_root: str | Path = ".") -> str:
    return _run(["rev-parse", "--show-toplevel"], cwd=repo_root)
