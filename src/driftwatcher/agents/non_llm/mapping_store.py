"""N9 MappingStore: read, validate, and write `.drift.json`."""

from __future__ import annotations

import json
from pathlib import Path

from ...contracts.envelope import Envelope
from ...observability.decorators import logged_step
from ...contracts.mapping import DriftFile, FeatureMapping, MappingOp

AGENT_ID = "N9.MappingStore"
FILENAME = ".drift.json"


def path_for(repo_root: str | Path = ".") -> Path:
    return Path(repo_root) / FILENAME


def read(repo_root: str | Path = ".") -> DriftFile:
    path = path_for(repo_root)
    if not path.exists():
        return DriftFile()
    return DriftFile.model_validate_json(path.read_text(encoding="utf-8"))


def write(mapping: DriftFile, repo_root: str | Path = ".") -> Path:
    path = path_for(repo_root)
    by_alias = mapping.model_dump(by_alias=True, mode="json")
    path.write_text(json.dumps(by_alias, indent=2) + "\n", encoding="utf-8")
    return path


def apply_op(mapping: DriftFile, op: MappingOp) -> DriftFile:
    if op.op == "add_feature":
        mapping.features[op.feature] = FeatureMapping(
            folder=op.folder, owners=list(op.owners),
            context_files=list(op.context_files), status=op.status,
            entry_points=list(op.entry_points), api_spec=op.api_spec,
            origin=op.origin if op.origin in ("auto", "user") else "auto",
        )
    elif op.op == "set_docs" and op.feature in mapping.features:
        mapping.features[op.feature].context_files = list(op.context_files)
    elif op.op == "set_status" and op.feature in mapping.features:
        mapping.features[op.feature].status = op.status
    elif op.op == "resolve_duplicate" and op.key:
        mapping.resolutions[op.key] = op.value
    return mapping


@logged_step(AGENT_ID)
def handle(env: Envelope[MappingOp]) -> Envelope[DriftFile]:
    op = env.payload if isinstance(env.payload, MappingOp) else MappingOp()
    mapping = apply_op(read(), op)
    return Envelope[DriftFile](
        correlation_id=env.correlation_id,
        type="DriftFile",
        sender=AGENT_ID,
        recipient=env.sender or "Orchestrator",
        payload=mapping,
    )
