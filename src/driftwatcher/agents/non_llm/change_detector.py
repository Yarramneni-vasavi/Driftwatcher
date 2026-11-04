"""N2 ChangeDetector: diff base...HEAD plus per-file/folder hashes."""

from __future__ import annotations

from ... import gitutil
from ...contracts.changes import ChangeRequest, ChangeSet, ChangedFile
from ...contracts.envelope import Envelope
from ...observability.decorators import logged_step

AGENT_ID = "N2.ChangeDetector"


def detect(req: ChangeRequest) -> ChangeSet:
    if req.scope == "uncommitted":
        try:
            rows = gitutil.worktree_status(req.repo_root)
        except RuntimeError:
            rows = []
    elif req.scope == "committed":
        try:
            rows = gitutil.diff_name_status(req.base, req.head, req.repo_root)
        except RuntimeError:
            rows = []
    else:
        raise ValueError(
            f"scope {req.scope!r} needs no change detection "
            "(full and partial check everything under their range)"
        )
    files: list[ChangedFile] = []
    for status, path in rows:
        try:
            digest = gitutil.hash_object(path, req.repo_root)
        except RuntimeError:
            digest = ""
        files.append(ChangedFile(path=path, status=status, hash=digest))
    return ChangeSet(base=req.base, head=req.head, files=files)


@logged_step(AGENT_ID)
def handle(env: Envelope[ChangeRequest]) -> Envelope[ChangeSet]:
    req = env.payload if isinstance(env.payload, ChangeRequest) else ChangeRequest()
    return Envelope[ChangeSet](
        correlation_id=env.correlation_id,
        type="ChangeSet",
        sender=AGENT_ID,
        recipient=env.sender or "Orchestrator",
        payload=detect(req),
    )
