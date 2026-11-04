"""Onboard workflow: scan -> map (architecture sec. 7.1, plan Phase 3).

N1 scan, L1 FeatureScout, N11 confirm/edit once, per feature N3 digest +
L2 DocMapper, every matching doc is kept (no primary), N9 save.
Per-feature onboarding supported via `feature`.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..agents.llm import doc_mapper as l2_doc_mapper
from ..agents.llm import feature_scout as l1_feature_scout
from ..agents.non_llm import (
    context_scanner,
    features_file as features_file_mod,
    folder_digester,
    mapping_store,
    markdown_sections,
    user_prompter,
)
from ..config.loader import get_active
from ..contracts.context import ScanRequest
from ..contracts.envelope import Envelope
from ..contracts.features import (
    Answer,
    DigestRequest,
    DocCandidate,
    DocMapRequest,
    FeatureInfo,
    FeatureScoutRequest,
    FolderDigest,
    Question,
)
from ..contracts.mapping import DriftFile, MappingOp
from ..observability.logger import StepTracker, get_logger
from .bus import new_correlation_id

STEPS = [
    "N1.ContextScanner",
    "L1.FeatureScout",
    "N11.UserPrompter",
    "N3.FolderDigester",
    "L2.DocMapper",
    "L5.SkillAuthor",
    "N9.MappingStore",
]


def _tree_snippet(repo_root: str, depth: int = 3) -> str:
    root = Path(repo_root)
    entries: list[str] = []
    for path in sorted(root.rglob("*")):
        if len(entries) >= 300:
            break
        try:
            rel = path.relative_to(root)
        except ValueError:
            continue
        if len(rel.parts) > depth or ".git" in rel.parts:
            continue
        entries.append(str(rel))
    return "\n".join(entries)


def _codeowners(repo_root: str) -> dict[str, list[str]]:
    owners: dict[str, list[str]] = {}
    for name in ("CODEOWNERS", ".github/CODEOWNERS", "docs/CODEOWNERS"):
        p = Path(repo_root) / name
        if p.exists():
            owners["CODEOWNERS"] = p.read_text(
                encoding="utf-8", errors="replace"
            ).splitlines()[:50]
            break
    return owners


ACCEPT_ALL_WORDS = frozenset({"all", "accept all", "yes", "y"})


def _split_choices(choices: list[str]) -> set[str]:
    """Split comma-separated answers into individual names.

    Accept-all words ("accept all", "all", "yes") contribute nothing, so an
    answer of "accept all" accepts every proposal instead of becoming a
    feature literally named "accept all".
    """
    return {
        part.strip()
        for choice in choices
        for part in choice.split(",")
        if part.strip() and part.strip().lower() not in ACCEPT_ALL_WORDS
    }


def _apply_picked(
    features: list[FeatureInfo], picked: set[str], reason: str
) -> list[FeatureInfo]:
    """Keep picked proposals; turn unknown picked names into new features.

    An empty `picked` (accept-all) keeps every proposal unchanged. Numeric
    picks ("1", "1,3") resolve against the displayed proposal order.
    """
    options = [f.name for f in features]
    resolved = set()
    for part in picked:
        if part.isdigit() and 1 <= int(part) <= len(options):
            resolved.add(options[int(part) - 1])
        else:
            resolved.add(part)
    kept = [f for f in features if f.name in resolved] if resolved else list(features)
    known = {f.name for f in kept}
    for name in resolved - known:
        kept.append(FeatureInfo(name=name, folder=name, reason=reason))
    return kept


# Filename stems that are inherently repo-global summaries. Used only for
# docs the match matrix says nothing about (zero matches) — never to
# overrule a content match.
GLOBAL_LIKE_STEMS = frozenset({"readme", "overview", "index", "home"})


def _doc_matrix(
    matched: dict[str, list[tuple[str, float]]]
) -> dict[str, set[str]]:
    """Map each doc to the features it matched (summary detection)."""
    matrix: dict[str, set[str]] = {}
    for name, pairs in matched.items():
        for doc, _ in pairs:
            matrix.setdefault(doc, set()).add(name)
    return matrix


def _pretty_name(stem: str) -> str:
    return stem.replace("_", " ").replace("-", " ")


def _name_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def propose_features(repo_root: str = ".") -> dict:
    """Run FeatureScout once and shape the proposal as an input file."""
    scout_req = FeatureScoutRequest(
        tree=_tree_snippet(repo_root),
        manifests={},
        owners=_codeowners(repo_root),
    )
    scout_env: Envelope[FeatureScoutRequest] = Envelope(
        correlation_id=new_correlation_id(), type="FeatureScoutRequest",
        sender="Orchestrator", recipient="L1.FeatureScout", payload=scout_req,
    )
    proposal = l1_feature_scout.handle(scout_env).payload
    return features_file_mod.propose_template(proposal)


def _apply_spec(
    spec: features_file_mod.FeaturesInput,
    mapping: DriftFile,
    refresh: bool,
) -> tuple[
    list[FeatureInfo], dict[str, list[str]], dict[str, dict], dict[str, str],
]:
    """Merge a features file into the mapping.

    Returns (features, locked_docs, meta, prior_status). The input file wins
    for folder, owners, entry points and explicitly listed docs; stored
    status, resolutions and auto-discovered fields are kept. Features missing
    from the file become unonboarded.
    """
    locked: dict[str, list[str]] = {}
    meta: dict[str, dict] = {}
    if spec.global_ is not None:
        mapping.global_.context_files = list(spec.global_.context_files)
    if spec.ignored_docs is not None:
        mapping.ignored_docs = sorted(set(spec.ignored_docs))
    features: list[FeatureInfo] = []
    for entry in spec.features:
        stored = mapping.features.get(entry.name)
        owners = list(entry.owners) or list(stored.owners if stored else [])
        entry_points = list(entry.entry_points) or list(
            stored.entry_points if stored else []
        )
        if entry.context_files is not None and entry.context_files:
            locked[entry.name] = list(entry.context_files)
            origin = "user"
        elif (
            stored is not None
            and stored.origin == "user"
            and stored.context_files
        ):
            locked[entry.name] = list(stored.context_files)
            origin = "user"
        elif (
            stored is not None
            and stored.origin == "auto"
            and stored.context_files
            and not refresh
        ):
            locked[entry.name] = list(stored.context_files)
            origin = "auto"
        else:
            origin = "auto"
        meta[entry.name] = {
            "owners": owners,
            "entry_points": entry_points,
            "api_spec": entry.api_spec or (stored.api_spec if stored else ""),
            "origin": origin,
        }
        features.append(
            FeatureInfo(
                name=entry.name, folder=entry.folder,
                reason="from features file",
            )
        )
    names = {f.name for f in features}
    for name, feat in mapping.features.items():
        if name not in names:
            feat.status = "unonboarded"
    prior_status = {n: f.status for n, f in mapping.features.items()}
    return features, locked, meta, prior_status


def run_onboard(
    repo_root: str = ".",
    feature: str | None = None,
    yes: bool = False,
    features_path: str | None = None,
    refresh: bool = False,
) -> DriftFile:
    config = get_active()
    correlation = new_correlation_id()
    tracker = StepTracker(get_logger(), STEPS)

    with tracker.step("N1.ContextScanner", {"repo": repo_root}) as span:
        inv = context_scanner.scan(
            ScanRequest(
                repo_root=repo_root, deny_globs=config.scan.deny_globs
            ),
            known_names=set(config.scan.known_context_names),
        )
        span.ok(inv)
    mapping = mapping_store.read(repo_root)

    file_docs: dict[str, list[str]] = {}
    file_meta: dict[str, dict] = {}
    prior_status: dict[str, str] = {}
    spec = None
    before = None
    if features_path:
        try:
            spec = features_file_mod.load_features_file(
                features_path, repo_root
            )
        except ValueError as exc:
            raise RuntimeError(str(exc)) from exc
        before = mapping.model_copy(deep=True)
        features, file_docs, file_meta, prior_status = _apply_spec(
            spec, mapping, refresh
        )
        if feature:
            features = [f for f in features if f.name == feature or f.folder == feature]
            if not features:
                features = [
                    FeatureInfo(
                        name=feature, folder=feature, reason="from --feature flag"
                    )
                ]
    else:
        scout_req = FeatureScoutRequest(
            tree=_tree_snippet(repo_root),
            manifests={},
            owners=_codeowners(repo_root),
        )
        scout_env: Envelope[FeatureScoutRequest] = Envelope(
            correlation_id=correlation, type="FeatureScoutRequest",
            sender="Orchestrator", recipient="L1.FeatureScout", payload=scout_req,
        )
        proposal = l1_feature_scout.handle(scout_env).payload
        features = list(getattr(proposal, "features", []))
        if not features and not feature:
            raise RuntimeError(
                f"FeatureScout identified no features for {repo_root}; "
                "check the LLM profile/key, or onboard one explicitly with "
                "--feature NAME"
            )
        if feature:
            features = [f for f in features if f.name == feature or f.folder == feature]
            if not features:
                features = [
                    FeatureInfo(
                        name=feature, folder=feature, reason="from --feature flag"
                    )
                ]

    if not features and not feature:
        raise RuntimeError(
            f"No features to onboard for {repo_root}; "
            "check the features file or onboard one explicitly with "
            "--feature NAME"
        )
    if not yes and spec is None:
        with tracker.step(
            "N11.UserPrompter", {"kind": "confirm_features"}
        ) as span:
            answer: Answer = user_prompter.ask(
                Question(
                    kind="confirm_features",
                    prompt=(
                        "Confirm features "
                        "(Enter = accept all, number(s), or comma-separated names):"
                    ),
                    options=[f.name for f in features],
                )
            )
            span.ok(answer)
        picked = _split_choices(
            answer.choices or ([answer.choice] if answer.choice else [])
        )
        features = _apply_picked(features, picked, "typed at confirm prompt")

    matched: dict[str, list[tuple[str, float]]] = {}
    digests: dict[str, FolderDigest] = {}

    def _collect(feat: FeatureInfo) -> None:
        tracker.use_feature(feat.name)
        if feat.name in file_docs:
            digests[feat.name] = FolderDigest(folder=feat.folder)
            matched[feat.name] = [(d, 1.0) for d in file_docs[feat.name]]
            tracker.use_feature(None)
            return
        with tracker.step("N3.FolderDigester", {"folder": feat.folder}) as span:
            if feat.folder and (Path(repo_root) / feat.folder).is_dir():
                digest = folder_digester.digest(
                    DigestRequest(folder=feat.folder), repo_root
                )
            else:
                digest = FolderDigest(folder=feat.folder)
            span.ok(digest)
        digests[feat.name] = digest
        pairs: list[tuple[str, float]] = []
        for doc in inv.files:
            excerpt = ""
            p = Path(repo_root) / doc.path
            if p.exists():
                excerpt = markdown_sections.excerpt_for(
                    p.read_text(encoding="utf-8", errors="replace"),
                    feat.name,
                    feat.folder,
                    doc.path,
                )
            map_env: Envelope[DocMapRequest] = Envelope(
                correlation_id=correlation, type="DocMapRequest",
                sender="Orchestrator", recipient="L2.DocMapper",
                payload=DocMapRequest(
                    feature_name=feat.name,
                    feature_folder=feat.folder,
                    docs=[DocCandidate(path=doc.path, excerpt=excerpt)],
                ),
            )
            out = l2_doc_mapper.handle(map_env)
            match = getattr(out.payload, "match", False)
            quote = getattr(out.payload, "quote", "")
            if match and quote.strip():
                pairs.append(
                    (doc.path, getattr(out.payload, "confidence", 0.0))
                )
        tracker.use_feature(None)
        matched[feat.name] = pairs

    for feat in features:
        _collect(feat)

    # Round 1: identical files (dedup) and uncovered docs, one bulk table.
    by_hash: dict[str, list[str]] = {}
    for doc in inv.files:
        if doc.hash:
            by_hash.setdefault(doc.hash, []).append(doc.path)
    round1: list[user_prompter.BulkRow] = []
    dup_of: dict[str, list[str]] = {}
    for paths in by_hash.values():
        if len(paths) > 1:
            label = f"identical:{paths[0]}"
            dup_of[label] = paths
            round1.append(
                user_prompter.BulkRow(
                    feature=label,
                    options=[f"keep all {len(paths)}"]
                    + [f"{p} only" for p in paths],
                )
            )
    matrix = _doc_matrix(matched)
    orphans = sorted(
        {d.path for d in inv.files} - set(matrix)
        - set(mapping.ignored_docs)
    )
    global_orphans = {
        doc for doc in orphans
        if _name_key(Path(doc).stem) in GLOBAL_LIKE_STEMS
    }
    for doc in orphans:
        if doc in global_orphans:
            round1.append(
                user_prompter.BulkRow(
                    feature=f"uncovered:{doc}",
                    options=["track as global covering doc", "ignore"],
                )
            )
        else:
            round1.append(
                user_prompter.BulkRow(
                    feature=f"uncovered:{doc}",
                    options=["onboard as new feature", "ignore"],
                )
            )
    cleanup: dict[str, str] = {}
    if round1 and not yes:
        with tracker.step(
            "N11.UserPrompter",
            {"kind": "cleanup_bulk", "rows": len(round1)},
        ) as span:
            cleanup = user_prompter.ask_bulk(round1)
            span.ok({"decisions": cleanup})

    ignored: list[str] = []
    for label, paths in dup_of.items():
        choice = cleanup.get(label, f"keep all {len(paths)}")
        if choice != f"keep all {len(paths)}":
            only = choice[: -len(" only")]
            for path in paths:
                if path != only and path not in ignored:
                    ignored.append(path)
    for doc in orphans:
        if doc in global_orphans:
            default = "track as global covering doc"
        else:
            default = "onboard as new feature"
        choice = default if yes else cleanup.get(f"uncovered:{doc}", default)
        if choice == "ignore" or yes:
            if doc not in ignored:
                ignored.append(doc)
        elif choice == "track as global covering doc":
            if doc not in mapping.global_.context_files:
                mapping.global_.context_files.append(doc)
        else:
            features.append(
                FeatureInfo(
                    name=_pretty_name(Path(doc).stem),
                    folder=Path(doc).stem,
                    reason="adopted orphan doc",
                )
            )
            _collect(features[-1])
    if yes and orphans:
        print(
            f"{len(orphans)} uncovered docs recorded as ignored "
            f"(yes mode): {', '.join(orphans)}"
        )
    mapping.ignored_docs = sorted(set(mapping.ignored_docs) | set(ignored))
    for name in matched:
        matched[name] = [m for m in matched[name] if m[0] not in ignored]
    matrix = _doc_matrix(matched)

    # No primary doc: a feature keeps every doc that references it,
    # single-feature or covering. CHECK verifies all of them.
    contexts: dict[str, list[str]] = {}
    for feat in features:
        tracker.use_feature(feat.name)
        if feat.name in file_docs:
            contexts[feat.name] = list(file_docs[feat.name])
        else:
            contexts[feat.name] = [m[0] for m in matched[feat.name]]
        with tracker.step(
            "N9.MappingStore", {"feature": feat.name}
        ) as span:
            meta = file_meta.get(feat.name, {})
            mapping = mapping_store.apply_op(
                mapping,
                MappingOp(
                    op="add_feature", feature=feat.name, folder=feat.folder,
                    context_files=contexts[feat.name],
                    owners=meta.get("owners", []),
                    entry_points=meta.get("entry_points", []),
                    api_spec=meta.get("api_spec", ""),
                    origin=meta.get("origin", "auto"),
                    status=prior_status.get(feat.name, "onboarded"),
                ),
            )
            span.ok({"feature": feat.name, "docs": contexts[feat.name]})
        tracker.use_feature(None)

    inv_docs = [d.path for d in inv.files]
    multi_docs = sorted(d for d, fs in matrix.items() if len(fs) > 1)
    uncovered = sorted(
        set(inv_docs) - set(matrix) - set(mapping.ignored_docs)
    )
    print(
        f"Coverage: {len(inv_docs)} docs - "
        f"{len(contexts)} features mapped, "
        f"{len(multi_docs)} multi-feature covering, "
        f"{len(mapping.global_.context_files)} global, "
        f"{len(mapping.ignored_docs)} ignored, "
        f"{len(uncovered)} uncovered"
    )
    if uncovered:
        print(
            "  uncovered (re-run with --feature to onboard): "
            + ", ".join(uncovered)
        )
    if spec is not None and before is not None:
        diff = features_file_mod.diff_against(spec, before)
        print(
            f"features file: {len(diff['added'])} added, "
            f"{len(diff['changed'])} changed, "
            f"{len(diff['unonboarded'])} unonboarded"
        )
        for line in diff["added"]:
            print(f"  + {line}")
        for line in diff["changed"]:
            print(f"  ~ {line}")
        for line in diff["unonboarded"]:
            print(f"  - {line} (kept as unonboarded)")
    mapping_store.write(mapping, repo_root)
    return mapping
