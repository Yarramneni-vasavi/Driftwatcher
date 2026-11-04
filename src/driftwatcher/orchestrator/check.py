"""Check workflow: MR/local check (architecture sec. 7.2, plan Phase 2/4).

Tier 1 (N7 RuleChecker) first, L4 judge only for leftovers, per-run
budget. Tier 3 findings are advisory until measured accuracy is
acceptable. Global files get deterministic checks only. Step lines
`[n/N]` come from this workflow definition (plan sec. 8.6).
"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import re
import threading

from ..agents.llm import claim_extractor as l3_claim_extractor
from ..agents.llm import judge as l4_judge
from ..agents.llm import rule_miner as l7_miner
from ..agents.non_llm import (
    callgraph,
    change_detector,
    code_outline,
    code_retriever,
    evidence_validator,
    mapping_store,
    reporter,
    router,
    rule_checker,
    rule_claims,
)
from ..cache import store
from ..config.loader import get_active
from ..contracts.changes import SCOPES, ChangeRequest
from ..contracts.claims import (
    Claim,
    ClaimExtractRequest,
    ClaimSet,
    CodeContext,
    CodeSnippet,
    DocText,
    JudgeRequest,
)
from ..contracts.envelope import Envelope
from ..contracts.features import DocMatch
from ..contracts.mapping import DriftFile
from ..contracts.rules import (
    BusinessRule,
    EntryOutline,
    FlowRule,
    FlowSummarizeRequest,
    FlowSummary,
    FunctionBody,
    MissingCheckRequest,
    RuleExtractRequest,
    RuleJudgeRequest,
    RuleSelectRequest,
    RuleSet,
)
from ..contracts.verdicts import DriftReport, Evidence, Verdict
from ..llm.budget import Budget, estimate_tokens
from ..observability.logger import StepTracker, get_logger
from .bus import new_correlation_id

STEPS = [
    "N2.ChangeDetector",
    "N4.Router",
    "N5.RuleClaimExtractor",
    "N7.RuleChecker",
    "L3.ClaimExtractor",
    "L4.Judge",
    "L7.RuleMiner",
    "L7.FlowMiner",
    "N10.Reporter",
]

MISSING_BATCH = 15


def _read_lines(repo_root: Path, doc_path: str) -> list[str]:
    p = repo_root / doc_path
    if not p.exists():
        return []
    return p.read_text(encoding="utf-8", errors="replace").splitlines()


def _doc_hash(doc_path: str, repo_root: str) -> str:
    from .. import gitutil

    try:
        return gitutil.hash_object(doc_path, repo_root)
    except RuntimeError:
        return ""


def _tracker() -> StepTracker:
    return StepTracker(get_logger(), STEPS)


def _log() -> StepLogger | None:
    return get_logger()


def _l3_claims(
    doc_path: str,
    feature: str,
    lines: list[str],
    doc_hash: str,
    budget: Budget,
    correlation: str,
    repo_root: str,
) -> list[Claim]:
    logger = _log()
    if not doc_hash:
        return []
    cached = store.read(store.claim_key(doc_hash), repo_root)
    if cached is not None:
        if logger is not None:
            logger.cache(f"hit claims doc={doc_path}")
        try:
            return list(ClaimSet.model_validate_json(cached).claims)
        except ValueError:
            return []
    if logger is not None:
        logger.cache(f"miss claims doc={doc_path}")
    if not budget.take():
        if logger is not None:
            logger.warning("L3.ClaimExtractor", "budget exhausted")
        return []
    req = ClaimExtractRequest(doc_path=doc_path, feature=feature, lines=lines)
    env: Envelope[ClaimExtractRequest] = Envelope(
        correlation_id=correlation,
        type="ClaimExtractRequest",
        sender="Orchestrator",
        recipient="L3.ClaimExtractor",
        payload=req,
    )
    out = l3_claim_extractor.handle(env)
    if out.error is not None or not isinstance(out.payload, ClaimSet):
        return []
    store.write(store.claim_key(doc_hash), out.payload.model_dump_json(), repo_root)
    return list(out.payload.claims)


OUTLINE_CHARS = 6000
BODIES_CHARS = 12000
DOCS_CHARS = 8000


def _outline_text(outline) -> str:  # noqa: ANN001, ANN202
    """Select-input outline with a per-file round-robin budget.

    The old code truncated one long string, so alphabetically late files
    (e.g. diff_analyzer.py after details_agent.py) never reached the
    select step. Every file now contributes its first units before any
    file contributes seconds.
    """
    per_file: dict[str, list[str]] = {}
    for unit in outline.units:
        guards = "; ".join(
            f"if {g.condition}: {g.outcome} (L{g.line})".strip(": ")
            if g.condition
            else f"{g.outcome} (L{g.line})"
            for g in unit.guards
        )
        head = f"{unit.file}:{unit.signature} L{unit.line}"
        if unit.docstring:
            head += f" - {unit.docstring}"
        per_file.setdefault(unit.file, []).append(
            head + (f" [{guards}]" if guards else "")
        )
    lines: list[str] = []
    chars = 0
    queues = [list(v) for v in per_file.values() if v]
    while queues and chars < OUTLINE_CHARS:
        progressed = False
        for queue in list(queues):
            if not queue:
                queues.remove(queue)
                continue
            head = queue.pop(0)
            if chars + len(head) + 1 > OUTLINE_CHARS:
                queues.clear()
                break
            lines.append(head)
            chars += len(head) + 1
            progressed = True
        if not progressed:
            break
    return "\n".join(lines)


def _read_segment(repo_root: str, file: str, start: int, end: int) -> str:
    try:
        lines = Path(repo_root, file).read_text(
            encoding="utf-8", errors="replace"
        ).splitlines()
    except OSError:
        return ""
    return "\n".join(lines[max(0, start - 1) : max(0, end)])[:BODIES_CHARS]


def _mine_rules(
    feature: str,
    folder: str,
    budget: Budget,
    correlation: str,
    repo_root: str,
) -> RuleSet:
    logger = _log()
    outline = code_outline.build(folder, repo_root)
    if not outline.units:
        return RuleSet(feature=feature)
    fingerprint = sha256(outline.model_dump_json().encode()).hexdigest()[:16]
    cached = store.read(store.rules_key(feature, fingerprint), repo_root)
    if cached is not None:
        if logger is not None:
            logger.cache(f"hit rules feature={feature}")
        try:
            return RuleSet.model_validate_json(cached)
        except ValueError:
            pass
    if logger is not None:
        logger.cache(f"miss rules feature={feature}")
    if not budget.take():
        if logger is not None:
            logger.warning("L7.RuleMiner", "budget exhausted")
        return RuleSet(feature=feature)
    sel_env = l7_miner.select(
        RuleSelectRequest(
            feature=feature, folder=folder,
            outline=_outline_text(outline),
        ),
        "Orchestrator", correlation,
    )
    names = (
        list(getattr(sel_env.payload, "names", []))
        if sel_env.error is None else []
    )
    bodies: list[FunctionBody] = []
    chars = 0
    wanted = {n.strip() for n in names if n.strip()}
    for unit in outline.units:
        if wanted and unit.name not in wanted:
            continue
        text = _read_segment(repo_root, unit.file, unit.line, unit.end_line)
        if not text:
            continue
        bodies.append(
            FunctionBody(file=unit.file, name=unit.name, line=unit.line, text=text)
        )
        chars += len(text)
        if chars >= BODIES_CHARS or len(bodies) >= 12:
            break
    if not bodies:
        return RuleSet(feature=feature)
    if not budget.take():
        if logger is not None:
            logger.warning("L7.RuleMiner", "budget exhausted")
        return RuleSet(feature=feature)
    ext_env = l7_miner.extract(
        RuleExtractRequest(feature=feature, folder=folder, functions=bodies),
        "Orchestrator", correlation,
    )
    if ext_env.error is not None or not isinstance(ext_env.payload, RuleSet):
        return RuleSet(feature=feature)
    rules = ext_env.payload
    rules.feature = feature
    seen: set[str] = set()
    unique: list[BusinessRule] = []
    for rule in rules.rules:
        key = re.sub(r"[^a-z0-9]+", "", rule.text.lower())
        if key and key not in seen:
            seen.add(key)
            unique.append(rule)
    if len(unique) > 30 and logger is not None:
        logger.warning(
            "L7.RuleMiner", f"capped {len(unique)} rules to 30"
        )
    rules.rules = unique[:30]
    store.write(store.rules_key(feature, fingerprint), rules.model_dump_json(), repo_root)
    return rules


def _rule_gap(
    rule: BusinessRule,
    excerpts: str,
    budget: Budget,
    correlation: str,
    repo_root: str,
) -> Verdict | None:
    """None means the rule is documented; a Verdict means gap/unverifiable."""
    from hashlib import sha256 as _sha

    logger = _log()
    key = store.verdict_key(
        rule.text, [CodeSnippet(file="docs", start=0, end=0, text=excerpts)]
    )
    cached = store.read(key, repo_root)
    if cached is not None:
        if logger is not None:
            logger.cache(f"hit rule verdict rule={rule.text[:40]}")
        try:
            verdict = Verdict.model_validate_json(cached)
            verdict.feature = rule.feature
            return verdict if verdict.verdict == "gap" else None
        except ValueError:
            pass
    if not budget.take():
        return Verdict(
            claim_id=f"gap-{_sha(rule.text.encode()).hexdigest()[:12]}",
            verdict="unverifiable", reason="LLM budget exhausted",
            tier="judge", feature=rule.feature,
        )
    out = l7_miner.judge(
        RuleJudgeRequest(feature=rule.feature, rule=rule.text, docs=[excerpts]),
        "Orchestrator", correlation,
    )
    if out.error is not None or not isinstance(out.payload, DocMatch):
        return Verdict(
            claim_id=f"gap-{_sha(rule.text.encode()).hexdigest()[:12]}",
            verdict="unverifiable", reason="rule judge error",
            tier="judge", feature=rule.feature,
        )
    judged: DocMatch = out.payload
    if judged.match and judged.quote.strip():
        store.write(
            key,
            Verdict(
                claim_id=f"gap-{_sha(rule.text.encode()).hexdigest()[:12]}",
                verdict="supported", tier="judge", feature=rule.feature,
            ).model_dump_json(),
            repo_root,
        )
        return None
    verdict = Verdict(
        claim_id=f"gap-{_sha(rule.text.encode()).hexdigest()[:12]}",
        verdict="gap",
        evidence=[Evidence(file=rule.file, line=rule.line)],
        reason=f"Undocumented {rule.kind} behavior: {rule.text}",
        tier="judge", feature=rule.feature,
    )
    store.write(key, verdict.model_dump_json(), repo_root)
    return verdict


_LOW_VALUE_PATTERNS = (
    # Step ordering ("run executes step_a then step_b ..."): control-flow
    # trivia, not behavior a doc must capture.
    re.compile(r"\b(?:executes|runs)\b.{0,80}\bthen\b", re.IGNORECASE),
    # Context-key plumbing ("stores parsed result in context[...]").
    re.compile(r"\bstores\b.{0,80}\bcontext\[", re.IGNORECASE),
    # Placeholder default strings, not real behavior.
    re.compile(r"No project context available", re.IGNORECASE),
    re.compile(r"No programming languages detected", re.IGNORECASE),
)


def _normalize_rule(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def is_low_value(text: str) -> bool:
    """True when a mined rule is noise the report should never show."""
    return any(p.search(text) for p in _LOW_VALUE_PATTERNS)


def _group_rules(
    rules: list[BusinessRule],
) -> list[tuple[BusinessRule, list[BusinessRule]]]:
    """Group identical rules (e.g. same helper in two files) keeping order.

    Returns (head, members) pairs; the head is checked once and the gap,
    if any, lists every member file.
    """
    groups: dict[str, tuple[BusinessRule, list[BusinessRule]]] = {}
    for rule in rules:
        key = _normalize_rule(rule.text)
        if not key:
            continue
        if key in groups:
            groups[key][1].append(rule)
        else:
            groups[key] = (rule, [rule])
    return list(groups.values())


def _reverse_feature(
    feature: str,
    folder: str,
    doc_paths: list[str],
    budget: Budget,
    correlation: str,
    repo_root: str,
) -> list[Verdict]:
    logger = _log()
    if not doc_paths:
        return []
    rules = _mine_rules(feature, folder, budget, correlation, repo_root)
    if not rules.rules:
        return []
    excerpts: list[str] = []
    chars = 0
    for doc_path in doc_paths:
        lines = _read_lines(Path(repo_root), doc_path)
        if not lines:
            continue
        chunk = f"=== {doc_path} ===\n" + "\n".join(lines)
        excerpts.append(chunk)
        chars += len(chunk)
        if chars >= DOCS_CHARS:
            break
    bundle = "\n".join(excerpts)[:DOCS_CHARS]
    verdicts: list[Verdict] = []
    entry_files, _ = _entry_points_for(feature, folder, repo_root)
    for head, members in _group_rules(rules.rules):
        if is_low_value(head.text):
            if logger is not None:
                logger.decision(
                    "L7.RuleMiner",
                    f"dropped low-value rule: {head.text[:80]}",
                    {},
                )
            continue
        gap = _rule_gap(head, bundle, budget, correlation, repo_root)
        if gap is not None:
            seen = {(e.file, e.line) for e in gap.evidence}
            for member in members:
                if (member.file, member.line) not in seen:
                    gap.evidence.append(
                        Evidence(file=member.file, line=member.line)
                    )
                    seen.add((member.file, member.line))
            _attribute_entry(
                gap, [e.file for e in gap.evidence], entry_files
            )
            verdicts.append(
                stamp_verdict(gap, tier="judge", feature=feature)
            )
    if logger is not None:
        logger.decision(
            "L7.RuleMiner",
            f"{feature}: rules={len(rules.rules)} gaps="
            f"{sum(1 for v in verdicts if v.verdict == 'gap')}",
            {},
        )
    return verdicts


def _doc_bundle(doc_paths: list[str], repo_root: str) -> str:
    """Whole-doc text for the B6 second pass (all sections at once)."""
    excerpts: list[str] = []
    chars = 0
    for doc_path in doc_paths:
        lines = _read_lines(Path(repo_root), doc_path)
        if not lines:
            continue
        chunk = f"=== {doc_path} ===\n" + "\n".join(lines)
        excerpts.append(chunk)
        chars += len(chunk)
        if chars >= DOCS_CHARS:
            break
    return "\n".join(excerpts)[:DOCS_CHARS]


def _flow_entries(
    feature: str, folder: str, repo_root: str
) -> list[tuple[str, str]]:
    """Entry points for the flow engine: mapping first, outline fallback.

    Returns (entry_name, file) pairs. When the features file names no
    entry points, every public top-level def/class in the folder is an
    entry candidate (B3: understand the code per entry point).
    """
    mapping = mapping_store.read(repo_root)
    feat = mapping.features.get(feature)
    raw = list(getattr(feat, "entry_points", []) or [])
    if raw:
        outline = code_outline.build(folder, repo_root)
        units = {u.name: u for u in outline.units}
        resolved = []
        for entry in raw:
            name = entry.split("(")[0].strip()
            if name in units:
                resolved.append((name, units[name].file))
        if resolved:
            return resolved
    return callgraph.entry_candidates(folder, repo_root)


def _build_entry_outline(
    feature: str,
    entry: str,
    file: str,
    folder: str,
    repo_root: str,
) -> tuple[EntryOutline, dict[int, list[str]]]:
    """Numbered reachable code + calls + test hints for one entry point.

    Returns the wire EntryOutline plus line_map {line: [files]} used by
    N8 validation and evidence attribution (FlowRule.lines are bare
    ints, so a cited line resolves to the file whose sent range holds it,
    falling back to the entry file when ambiguous).
    """
    root = Path(repo_root)
    index = callgraph.index_folder(folder, repo_root)
    segments, edges = callgraph.reachable(file, entry, index)
    numbered: list[str] = []
    sent: list[list] = []
    chars = 0
    capped = False
    for seg_file in sorted(segments):
        if capped:
            break
        try:
            lines = (root / seg_file).read_text(
                encoding="utf-8", errors="replace"
            ).splitlines()
        except OSError:
            continue
        for start, end in segments[seg_file]:
            if capped:
                break
            for ln in range(start, end + 1):
                if ln - 1 >= len(lines):
                    continue
                head = f"{seg_file}:{ln}: {lines[ln - 1]}"
                if chars + len(head) + 1 > callgraph.MAX_CODE_CHARS:
                    capped = True
                    break
                numbered.append(head)
                sent.append([seg_file, ln])
                chars += len(head) + 1
    line_map: dict[int, list[str]] = {}
    for seg_file, ln in sent:
        line_map.setdefault(ln, []).append(seg_file)
    ranges: dict[str, list[list[int]]] = {}
    for seg_file, ln in sorted(sent):
        bucket = ranges.setdefault(seg_file, [])
        if bucket and ln == bucket[-1][1] + 1:
            bucket[-1][1] = ln
        else:
            bucket.append([ln, ln])
    valid = [r for bucket in ranges.values() for r in bucket]
    hints = callgraph.find_tests(
        folder, repo_root, entry, Path(file).stem
    )
    tests = [f"{h.path}::{h.name}\n{h.body}" for h in hints]
    mod = index.get(file)
    entry_line = mod.defs[entry][0] if mod and entry in mod.defs else 0
    outline = EntryOutline(
        feature=feature,
        entry_point=entry,
        file=file,
        line=entry_line,
        code="\n".join(numbered),
        valid_ranges=valid,
        calls=edges,
        tests=tests,
        openapi="",
    )
    return outline, line_map


def _n8_validate(
    summary: FlowSummary, line_map: dict[int, list[str]]
) -> FlowSummary:
    """N8: every cited line must fall inside the code that was sent.

    Drops out-of-range lines, then drops rules left with no lines.
    """
    clean: list[FlowRule] = []
    for rule in summary.rules:
        kept = [ln for ln in rule.lines if ln in line_map]
        if kept:
            clean.append(rule.model_copy(update={"lines": kept}))
    return summary.model_copy(update={"rules": clean})


def _merge_flow_rules(rules: list[FlowRule]) -> list[FlowRule]:
    """Merge near-duplicate rules (same normalized when+then).

    Keeps first text, unions lines, prefers high significance, and
    assigns stable ids (r1, r2, ...) when missing or duplicated.
    """
    groups: dict[str, FlowRule] = {}
    order: list[str] = []
    for rule in rules:
        key = _normalize_rule(f"{rule.when}|{rule.then}")
        if not key:
            continue
        if key in groups:
            head = groups[key]
            head.lines = sorted(set(head.lines) | set(rule.lines))
            if rule.significance == "high":
                head.significance = "high"
        else:
            groups[key] = rule.model_copy()
            order.append(key)
    merged = [groups[k] for k in order]
    used: set[str] = set()
    for i, rule in enumerate(merged, 1):
        if not rule.id or rule.id in used:
            rule.id = f"r{i}"
        used.add(rule.id)
    return merged


def _score_recall(
    mined: dict[str, list[FlowRule]],
    golden_entries: dict[str, list[dict]],
) -> dict:
    """Recall/noise of mined rules vs golden rules, per entry then total.

    A golden rule counts as hit when a mined high-significance rule for
    the same entry shares at least one line. Mined high-significance
    rules with no golden line overlap are noise. Used by the live smoke
    test to gate the flow miner before the section comparer is built.
    """
    hits = 0
    total = 0
    noise: dict[str, list[str]] = {}
    for entry, golden_rules in golden_entries.items():
        want = [g for g in golden_rules if g.get("significance", "high") == "high"]
        total += len(want)
        got = [r for r in mined.get(entry, []) if r.significance == "high"]
        got_lines = [set(r.lines) for r in got]
        for g in want:
            if any(set(g.get("lines", [])) & lines for lines in got_lines):
                hits += 1
        noisy = [
            f"{r.id}: when {r.when} / then {r.then} (lines {r.lines})"
            for r, lines in zip(got, got_lines)
            if not any(
                set(g.get("lines", [])) & lines for g in want
            )
        ]
        if noisy:
            noise[entry] = noisy
    return {
        "recall": (hits / total) if total else 1.0,
        "hits": hits,
        "total": total,
        "noise": noise,
    }


def _flow_summarize(
    feature: str,
    entry: str,
    outline: EntryOutline,
    line_map: dict[int, list[str]],
    budget: Budget,
    correlation: str,
    repo_root: str,
) -> FlowSummary | None:
    """B4: one structured LLM call per entry point, cached by content."""
    logger = _log()
    fingerprint = sha256(outline.model_dump_json().encode()).hexdigest()[:16]
    slug = re.sub(r"[^a-z0-9]+", "-", entry.lower()).strip("-")
    cached = store.read(store.flow_key(feature, slug, fingerprint), repo_root)
    if cached is not None:
        if logger is not None:
            logger.cache(f"hit flow feature={feature} entry={entry}")
        try:
            return FlowSummary.model_validate_json(cached)
        except ValueError:
            pass
    if logger is not None:
        logger.cache(f"miss flow feature={feature} entry={entry}")
    if not budget.take():
        if logger is not None:
            logger.warning("L7.FlowMiner", "budget exhausted")
        return None
    env = l7_miner.summarize_flow(
        FlowSummarizeRequest(
            feature=feature,
            entry_point=entry,
            file=outline.file,
            code=outline.code,
            calls=outline.calls,
            tests=outline.tests,
            openapi=outline.openapi,
        ),
        "Orchestrator", correlation,
    )
    if env.error is not None or not isinstance(env.payload, FlowSummary):
        if logger is not None:
            logger.warning(
                "L7.FlowMiner",
                f"summarize failed feature={feature} entry={entry}",
            )
        return None
    summary: FlowSummary = env.payload
    if not summary.feature:
        summary.feature = feature
    if not summary.entry_point:
        summary.entry_point = entry
    if not summary.file:
        summary.file = outline.file
    validated = _n8_validate(summary, line_map)
    merged = _merge_flow_rules(validated.rules)
    summary = validated.model_copy(update={"rules": merged})
    store.write(
        store.flow_key(feature, slug, fingerprint),
        summary.model_dump_json(), repo_root,
    )
    if logger is not None:
        logger.decision(
            "L7.FlowMiner",
            f"summarized feature={feature} entry={entry}",
            summary.log_summary(),
        )
    return summary


def _flow_missing_pass(
    feature: str,
    entry: str,
    entry_file: str,
    rules: list[FlowRule],
    line_map: dict[int, list[str]],
    bundle: str,
    budget: Budget,
    correlation: str,
    repo_root: str,
) -> tuple[list[FlowRule], list[FlowRule]]:
    """B6 second pass: whole-doc coverage in batches of ~15 rules.

    Returns (missing, unchecked). Unchecked rules ran out of budget and
    become unverifiable, never gaps.
    """
    logger = _log()
    highs = [r for r in rules if r.significance == "high"]
    if logger is not None:
        logger.decision(
            "L7.FlowMiner",
            f"missing-pass feature={feature} entry={entry}",
            {"high": len(highs), "low_dropped": len(rules) - len(highs)},
        )
    ids = {r.id for r in rules}
    covered: set[str] = set()
    missing: set[str] = set()
    unchecked: list[FlowRule] = []
    exhausted = False
    for i in range(0, len(highs), MISSING_BATCH):
        batch = highs[i : i + MISSING_BATCH]
        if not budget.take():
            unchecked.extend(batch)
            unchecked.extend(highs[i + MISSING_BATCH :])
            exhausted = True
            break
        env = l7_miner.check_missing(
            MissingCheckRequest(
                feature=feature,
                entry_point=entry,
                doc=bundle,
                rules=batch,
            ),
            "Orchestrator", correlation,
        )
        if env.error is not None:
            unchecked.extend(batch)
            continue
        result = env.payload
        for cid in list(result.covered):
            if cid in ids:
                covered.add(cid)
        for mid in list(result.missing):
            if mid in ids:
                missing.add(mid)
        for rule in batch:
            if rule.id not in covered and rule.id not in missing:
                unchecked.append(rule)
    if exhausted and logger is not None:
        logger.warning("L7.FlowMiner", "missing-pass budget exhausted")
    by_id = {r.id: r for r in highs}
    return (
        [by_id[mid] for mid in missing if mid in by_id],
        unchecked,
    )


def _flow_feature(
    feature: str,
    folder: str,
    doc_paths: list[str],
    budget: Budget,
    correlation: str,
    repo_root: str,
) -> list[Verdict]:
    """Flow engine per feature: miner (B3+B4) then whole-doc missing (B6).

    Stops before the per-section comparer: every high-significance rule
    the whole doc does not cover becomes a gap; budget leftovers become
    unverifiable. Low-significance rules are dropped, never reported.
    """
    logger = _log()
    bundle = _doc_bundle(doc_paths, repo_root)
    if not bundle:
        return []
    entries = _flow_entries(feature, folder, repo_root)
    verdicts: list[Verdict] = []
    for entry, entry_file in entries:
        outline, line_map = _build_entry_outline(
            feature, entry, entry_file, folder, repo_root
        )
        if not outline.code.strip():
            continue
        summary = _flow_summarize(
            feature, entry, outline, line_map,
            budget, correlation, repo_root,
        )
        if summary is None or not summary.rules:
            continue
        missing, unchecked = _flow_missing_pass(
            feature, entry, entry_file, summary.rules, line_map,
            bundle, budget, correlation, repo_root,
        )
        for rule in missing:
            evidence: list[Evidence] = []
            for ln in rule.lines:
                files = line_map.get(ln, [entry_file])
                ev_file = files[0] if len(files) == 1 else entry_file
                if not any(e.file == ev_file and e.line == ln for e in evidence):
                    evidence.append(Evidence(file=ev_file, line=ln))
            verdicts.append(
                stamp_verdict(
                    Verdict(
                        claim_id=f"flow:{feature}:{entry}:{rule.id}",
                        verdict="gap",
                        evidence=evidence,
                        reason=(
                            f"Undocumented {rule.scenario} behavior: "
                            f"when {rule.when}, then {rule.then}"
                        ),
                        tier="judge", feature=feature,
                        entry_point=entry,
                    ),
                    tier="judge", feature=feature,
                )
            )
        for rule in unchecked:
            verdicts.append(
                stamp_verdict(
                    Verdict(
                        claim_id=f"flow:{feature}:{entry}:{rule.id}",
                        verdict="unverifiable",
                        reason="missing-pass budget exhausted or error",
                        tier="judge", feature=feature,
                        entry_point=entry,
                    ),
                    tier="judge", feature=feature,
                )
            )
    if logger is not None:
        logger.decision(
            "L7.FlowMiner",
            f"{feature}: entries={len(entries)} gaps="
            f"{sum(1 for v in verdicts if v.verdict == 'gap')}",
            {},
        )
    return verdicts


def _entry_points_for(
    feature: str, folder: str, repo_root: str
) -> tuple[dict[str, str], list[str]]:
    """Resolve entry point names to files; return (found, missing)."""
    mapping = mapping_store.read(repo_root)
    feat = mapping.features.get(feature)
    entry_points = list(getattr(feat, "entry_points", []) or [])
    outline = code_outline.build(folder, repo_root)
    units = {u.name: u for u in outline.units}
    found: dict[str, str] = {}
    missing: list[str] = []
    for raw in entry_points:
        name = raw.split("(")[0].strip()
        if name in units:
            found[raw] = units[name].file
        else:
            missing.append(raw)
    return found, missing


def _endpoint_claim(claim: Claim) -> bool:
    text = claim.text.lower()
    return bool(
        re.search(r"https?://|/api/|websocket|grpc", text)
        or "endpoint" in text
    )


def _attribute_entry(
    verdict: Verdict, files: list[str], entry_files: dict[str, str]
) -> Verdict:
    for name, path in entry_files.items():
        if path in files:
            verdict.entry_point = name
            break
    return verdict


def _run_parallel(
    items: list,
    fn,
    max_workers: int = 4,
    timeout_s: int = 60,
) -> list:
    """Run fn(i, item) concurrently; results in input order."""
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as _Timeout

    results: list = [None] * len(items)
    if not items:
        return results
    with ThreadPoolExecutor(max_workers=max(1, max_workers)) as pool:
        futures = {pool.submit(fn, i, item): i for i, item in enumerate(items)}
        for future, i in futures.items():
            try:
                results[i] = future.result(timeout=timeout_s)
            except _Timeout as exc:
                results[i] = exc
            except Exception as exc:  # noqa: BLE001 - mapped by caller
                results[i] = exc
    return results


def stamp_verdict(
    verdict: Verdict,
    *,
    claim_id: str = "",
    tier: str = "",
    feature: str = "",
) -> Verdict:
    """Guarantee every reported verdict has a claim id, tier, and feature.

    Applied by the orchestrator to every verdict regardless of producer
    (deterministic checker, LLM judge, cache, miner): the contract
    requires claim_id and tier, and this is the single backstop.
    """
    if not getattr(verdict, "claim_id", ""):
        seed = "|".join([
            claim_id, feature,
            getattr(verdict, "reason", ""),
            ",".join(
                f"{e.file}:{e.line}" for e in
                getattr(verdict, "evidence", [])
            ),
        ])
        verdict.claim_id = claim_id or (
            "auto-" + sha256(seed.encode()).hexdigest()[:12]
        )
    if tier and not getattr(verdict, "tier", ""):
        verdict.tier = tier  # type: ignore[assignment]
    if feature and not getattr(verdict, "feature", ""):
        verdict.feature = feature
    return verdict


def _l4_judge(
    claim: Claim,
    ctx: CodeContext,
    budget: Budget,
    correlation: str,
    repo_root: str,
    lock=None,
    entry_files: dict[str, str] | None = None,
) -> Verdict:
    logger = _log()
    entry_files = entry_files or {}
    snippet_files = [s.file for s in ctx.snippets]
    entry = next(
        (name for name, path in entry_files.items() if path in snippet_files),
        "",
    )
    key = store.verdict_key(claim.text + "|" + entry, ctx.snippets)
    cached = store.read(key, repo_root)
    if cached is not None:
        if logger is not None:
            logger.cache(f"hit verdict claim={claim.id}")
        try:
            return Verdict.model_validate_json(cached)
        except ValueError:
            pass
    if logger is not None:
        logger.cache(f"miss verdict claim={claim.id}")
        logger.decision(
            "L4.Judge",
            f"claim={claim.id} ({claim.doc_path}:{claim.line}) needs judge",
            {"snippets": len(ctx.snippets)},
        )
    take = budget.take() if lock is None else _locked_take(budget, lock)
    if not take:
        if logger is not None:
            logger.warning("L4.Judge", "budget exhausted")
        return Verdict(
            claim_id=claim.id, verdict="unverifiable",
            reason="LLM budget exhausted", tier="judge",
            entry_point=entry,
        )
    try:
        if lock is not None:
            with lock:
                budget.check(estimate_tokens(len(claim.text) + sum(len(s.text) for s in ctx.snippets)))
        else:
            budget.check(estimate_tokens(len(claim.text) + sum(len(s.text) for s in ctx.snippets)))
    except Exception as exc:  # noqa: BLE001 - BudgetExceeded
        if logger is not None:
            logger.warning("L4.Judge", str(exc))
        return Verdict(
            claim_id=claim.id, verdict="unverifiable",
            reason=str(exc), tier="judge", entry_point=entry,
        )
    req = JudgeRequest(claim=claim, snippets=ctx.snippets)
    env: Envelope[JudgeRequest] = Envelope(
        correlation_id=correlation,
        type="JudgeRequest",
        sender="Orchestrator",
        recipient="L4.Judge",
        payload=req,
    )
    out = l4_judge.handle(env)
    if out.error is not None or not isinstance(out.payload, Verdict):
        return Verdict(
            claim_id=claim.id, verdict="unverifiable",
            reason="judge error", tier="judge", entry_point=entry,
        )
    verdict = out.payload
    verdict.entry_point = verdict.entry_point or entry
    if not verdict.feature:
        verdict.feature = claim.feature
    validated = evidence_validator.validate(verdict, ctx, repo_root)
    if validated is None:
        if logger is not None:
            logger.warning(
                "N8.EvidenceValidator",
                f"rejected claim={claim.id}: cited line not in provided "
                "snippets -> unverifiable",
            )
        return Verdict(
            claim_id=claim.id, verdict="unverifiable",
            reason="evidence rejected", tier="judge", entry_point=entry,
        )
    if validated.verdict in ("supported", "contradicted") and not validated.evidence:
        validated.verdict = "unverifiable"
    store.write(key, validated.model_dump_json(), repo_root)
    return validated


def _locked_take(budget: Budget, lock) -> bool:  # noqa: ANN001, ANN202
    with lock:
        return budget.take()


def run_check(
    repo_root: str = ".",
    base: str = "origin/main",
    mode: str | None = None,
    budget: Budget | None = None,
    scope: str = "committed",
    path: str | None = None,
    engine: str = "legacy",
) -> DriftReport:
    if scope not in SCOPES:
        raise ValueError(
            f"unknown scope {scope!r} (want one of {list(SCOPES)})"
        )
    if engine not in ("legacy", "flow"):
        raise ValueError(
            f"unknown engine {engine!r} (want one of ['legacy', 'flow'])"
        )
    if scope == "partial" and not path:
        raise ValueError("--scope partial requires --path <folder>")
    if path and scope != "partial":
        raise ValueError("--path only applies to --scope partial")
    root = Path(repo_root)
    config = get_active()
    budget = budget or Budget.from_config(config)
    mode = mode or config.check.default_mode
    correlation = new_correlation_id()
    tracker = _tracker()
    logger = _log()

    mapping: DriftFile = mapping_store.read(repo_root)

    if scope in ("full", "partial"):
        if scope == "full":
            print(
                "Full check: every mapped feature is verified. "
                "This takes longer and uses more LLM calls than a diff scope."
            )
        with tracker.step(
            "N4.Router",
            {"scope": scope, "path": path or "",
             "mapping_features": len(mapping.features)},
        ) as span:
            plan = router.route_all(mapping, path or "")
            span.ok(plan)
    else:
        with tracker.step(
            "N2.ChangeDetector", {"base": base, "scope": scope}
        ) as span:
            changeset = change_detector.detect(
                ChangeRequest(base=base, repo_root=repo_root, scope=scope)
            )
            span.ok(changeset)

        with tracker.step("N4.Router", {"mapping_features": len(mapping.features)}) as span:
            plan = router.route(changeset, mapping)
            span.ok(plan)
    if logger is not None:
        logger.decision(
            "N4.Router",
            f"scope={scope} features={len(plan.features)} "
            f"global_docs={len(plan.global_docs)}",
            {},
        )
    if logger is not None:
        for item in plan.features:
            if item.case != "none":
                logger.decision(
                    "N4.Router",
                    f"{item.name}: case={item.case}",
                    {"code_files": item.code_files, "doc_files": item.doc_files},
                )

    verdicts: list[Verdict] = []
    feature_names: list[str] = []

    for item in plan.features:
        if item.case == "none":
            continue
        feature_names.append(item.name)
        tracker.use_feature(item.name)
        folder = (
            mapping.features[item.name].folder
            if item.name in mapping.features
            else ""
        )
        changed = list(item.code_files)

        doc_paths = list(item.doc_files)
        if scope in ("committed", "uncommitted") and (
            item.case == "code_only" and item.name in mapping.features
        ):
            doc_paths += [
                d for d in mapping.features[item.name].context_files
                if d not in doc_paths
            ]
        claims: list[Claim] = []
        with tracker.step(
            "N5.RuleClaimExtractor", {"feature": item.name, "docs": doc_paths}
        ) as span:
            for doc_path in doc_paths:
                lines = _read_lines(root, doc_path)
                if not lines:
                    continue
                claims.extend(
                    rule_claims.extract(
                        DocText(doc_path=doc_path, feature=item.name, lines=lines)
                    ).claims
                )
                claims.extend(
                    _l3_claims(
                        doc_path, item.name, lines,
                        _doc_hash(doc_path, repo_root),
                        budget, correlation, repo_root,
                    )
                )
            span.ok({"feature": item.name, "claims": len(claims)})

        resolved = 0
        needs_judge = 0
        skipped_endpoints = 0
        entry_files, missing_entries = _entry_points_for(
            item.name, folder, repo_root
        )
        for missing in missing_entries:
            verdicts.append(
                stamp_verdict(
                    Verdict(
                        claim_id=f"entry:{item.name}:{missing}",
                        verdict="unverifiable",
                        reason=f"entry point {missing!r} not found in code",
                        tier="deterministic", feature=item.name,
                    ),
                    claim_id=f"entry:{item.name}:{missing}",
                    tier="deterministic", feature=item.name,
                )
            )
        judge_jobs: list[tuple[Claim, CodeContext]] = []
        with tracker.step("N7.RuleChecker", {"feature": item.name}) as span:
            for claim in claims:
                if not claim.id:
                    claim.id = Claim.make_id(
                        claim.doc_path, claim.line, claim.text
                    )
                if not claim.feature:
                    claim.feature = item.name
                if claim.kind in ("behavior", "convention") and _endpoint_claim(claim):
                    api_spec = getattr(
                        mapping.features.get(item.name), "api_spec", ""
                    )
                    if not api_spec:
                        skipped_endpoints += 1
                        verdicts.append(
                            Verdict(
                                claim_id=claim.id, verdict="unverifiable",
                                reason="endpoint check skipped: no API spec provided",
                                tier="deterministic", feature=item.name,
                            )
                        )
                        continue
                result = rule_checker.check(claim, repo_root, folder)
                if isinstance(result, Verdict):
                    resolved += 1
                    if claim.kind in ("behavior", "convention"):
                        result.tier = "behavioral"
                    stamp_verdict(
                        result, claim_id=claim.id, feature=item.name
                    )
                    if result.verdict in ("supported", "contradicted") and not result.evidence:
                        if result.verdict == "supported":
                            result.verdict = "unverifiable"
                            result.reason += " (no evidence)"
                    _attribute_entry(
                        result,
                        [e.file for e in result.evidence],
                        entry_files,
                    )
                    verdicts.append(result)
                    continue
                needs_judge += 1
                ctx = code_retriever.retrieve(claim, folder, repo_root, changed)
                judge_jobs.append((claim, ctx))
            span.ok(
                {
                    "feature": item.name,
                    "resolved": resolved,
                    "needs_judge": needs_judge,
                    "skipped_endpoints": skipped_endpoints,
                    "missing_entries": missing_entries,
                }
            )
        lock = threading.Lock()
        with tracker.step("L4.Judge", {"feature": item.name}) as span:
            judged = _run_parallel(
                judge_jobs,
                lambda i, job: _l4_judge(
                    job[0], job[1], budget, correlation, repo_root,
                    lock, entry_files,
                ),
            )
            for outcome, (job_claim, _ctx) in zip(judged, judge_jobs):
                if isinstance(outcome, Verdict):
                    verdicts.append(
                        stamp_verdict(
                            outcome, claim_id=job_claim.id,
                            tier="judge", feature=item.name,
                        )
                    )
                else:
                    verdicts.append(
                        Verdict(
                            claim_id=job_claim.id,
                            verdict="unverifiable",
                            reason=f"judge timed out or failed: {outcome!r}"[:200],
                            tier="judge", feature=item.name,
                        )
                    )
            span.ok({"feature": item.name, "judged": len(judged)})
        miner_step = "L7.FlowMiner" if engine == "flow" else "L7.RuleMiner"
        with tracker.step(miner_step, {"feature": item.name}) as span:
            if engine == "flow":
                gaps = _flow_feature(
                    item.name, folder, doc_paths,
                    budget, correlation, repo_root,
                )
            else:
                gaps = _reverse_feature(
                    item.name, folder, doc_paths,
                    budget, correlation, repo_root,
                )
            verdicts.extend(gaps)
            span.ok({"feature": item.name, "gaps": len(gaps)})
        tracker.use_feature(None)

    for doc_path in plan.global_docs:
        lines = _read_lines(root, doc_path)
        for claim in rule_claims.extract(
            DocText(doc_path=doc_path, feature="global", lines=lines)
        ).claims:
            if claim.kind in ("behavior", "convention"):
                verdicts.append(
                    stamp_verdict(
                        Verdict(
                            claim_id=claim.id, verdict="unverifiable",
                            reason="global deterministic-only",
                            tier="deterministic",
                        ),
                        claim_id=claim.id, feature="global",
                    )
                )
                continue
            result = rule_checker.check(claim, repo_root, "")
            if isinstance(result, Verdict):
                verdicts.append(
                    stamp_verdict(
                        result, claim_id=claim.id, feature="global"
                    )
                )

    verdicts = [stamp_verdict(v, tier="judge") for v in verdicts]
    with tracker.step("N10.Reporter", {"mode": mode}) as span:
        report = reporter.build(
            verdicts, mode=mode,
            unmapped=plan.unmapped_folders, feature_names=feature_names,
        )
        span.ok(report)
    return report
