"""N1 ContextScanner: list `.md` files, drop deny-listed, tag known names."""

from __future__ import annotations

import fnmatch
from pathlib import Path

from ... import gitutil
from ...contracts.context import ContextFile, ContextInventory, ScanRequest
from ...contracts.envelope import Envelope
from ...observability.decorators import logged_step

KNOWN = {"AGENTS.md", "SKILL.md", "CLAUDE.md", "GEMINI.md"}
AGENT_ID = "N1.ContextScanner"


def default_known_names() -> set[str]:
    try:
        from ...config.loader import get_active

        return set(get_active().scan.known_context_names)
    except Exception:  # noqa: BLE001
        return set(KNOWN)


def _denied(path: str, deny_globs: list[str]) -> bool:
    name = Path(path).name
    for glob in deny_globs:
        if fnmatch.fnmatch(path, glob) or fnmatch.fnmatch(name, glob):
            return True
    lowered = path.lower()
    if "changelog" in lowered or "license" in lowered:
        return True
    if Path(path).name.lower() in ("contributing.md", "code_of_conduct.md"):
        return True
    for vendored in ("node_modules/", "vendor/", "venv/", ".venv/"):
        if vendored in path:
            return True
    return False


def scan(req: ScanRequest, known_names: set[str] | None = None) -> ContextInventory:
    known = known_names if known_names is not None else default_known_names()
    try:
        paths = gitutil.ls_md_files(req.repo_root)
    except RuntimeError:
        paths = [str(p) for p in Path(req.repo_root).rglob("*.md")]
    files: list[ContextFile] = []
    for path in sorted(paths):
        if _denied(path, req.deny_globs):
            continue
        kind = "known" if Path(path).name in known else "candidate"
        try:
            digest = gitutil.hash_object(path, req.repo_root)
        except RuntimeError:
            digest = ""
        files.append(ContextFile(path=path, hash=digest, kind=kind))
    return ContextInventory(files=files)


@logged_step(AGENT_ID)
def handle(env: Envelope[ScanRequest]) -> Envelope[ContextInventory]:
    req = env.payload if isinstance(env.payload, ScanRequest) else ScanRequest()
    inv = scan(req)
    return Envelope[ContextInventory](
        correlation_id=env.correlation_id,
        type="ContextInventory",
        sender=AGENT_ID,
        recipient=env.sender or "Orchestrator",
        payload=inv,
    )
