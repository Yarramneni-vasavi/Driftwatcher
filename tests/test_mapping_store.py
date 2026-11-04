"""MappingStore write/read round-trip (write used a bad model_dump kwarg)."""

from driftwatcher.agents.non_llm import mapping_store
from driftwatcher.agents.non_llm.mapping_store import FILENAME
from driftwatcher.contracts.mapping import DriftFile


def test_write_then_read_round_trip(tmp_path) -> None:
    mapping = DriftFile(
        features={
            "agents": {
                "folder": "agents",
                "owners": [],
                "context_files": ["agents/README.md", "overview.md"],
                "status": "onboarded",
            }
        },
        ignored_docs=["old.md"],
    )
    mapping.global_.context_files.append("overview.md")
    path = mapping_store.write(mapping, tmp_path)
    assert path == tmp_path / FILENAME
    assert mapping_store.read(tmp_path) == mapping
