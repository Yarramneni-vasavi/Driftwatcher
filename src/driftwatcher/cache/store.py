"""Claim + verdict cache under `.drift/cache/` (architecture sec. 5.3).

Claim extraction keyed by doc-file hash; verdicts keyed by
hash(claim text + referenced code snippets). Restored in CI via actions/cache.
"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from ..contracts.claims import CodeSnippet


def configured_dir(repo_root: str | Path) -> str:
    try:
        from ..config.loader import get_active

        return get_active().cache.dir
    except Exception:  # noqa: BLE001
        return ".drift/cache"


def _cache_dir(repo_root: str | Path, cache_dir: str | None = None) -> Path:
    d = Path(repo_root) / (cache_dir or configured_dir(repo_root))
    d.mkdir(parents=True, exist_ok=True)
    return d


def claim_key(doc_hash: str) -> str:
    return f"claims-{doc_hash}.json"


def verdict_key(claim_text: str, snippets: list[CodeSnippet]) -> str:
    joined = claim_text + "\n" + "\n".join(
        f"{s.file}:{s.start}-{s.end}:{s.text}" for s in snippets
    )
    return f"verdict-{sha256(joined.encode()).hexdigest()[:16]}.json"


def rules_key(feature: str, fingerprint: str) -> str:
    return f"rules-{feature}-{fingerprint}.json"


def flow_key(feature: str, entry: str, fingerprint: str) -> str:
    return f"flow-{feature}-{entry}-{fingerprint}.json"


def read(
    key: str, repo_root: str | Path = ".", cache_dir: str | None = None
) -> str | None:
    path = Path(repo_root) / (cache_dir or configured_dir(repo_root)) / key
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def write(
    key: str,
    content: str,
    repo_root: str | Path = ".",
    cache_dir: str | None = None,
) -> None:
    d = _cache_dir(repo_root, cache_dir)
    (d / key).write_text(content, encoding="utf-8")
