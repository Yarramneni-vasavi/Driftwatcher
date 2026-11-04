# Driftwatch: MAP and CHECK Improvement Plan

Status: Draft v2 (post first real run on `CodeBoarding/agents`)
Companion to `driftwatch_architecture.md` and `driftwatch_implementation_plan.md`.

---

## 1. Goal and principles

**Goal:** the report shows only business-logic drift:

- **Missing:** logic the code has that the context doc never states.
- **Stale:** logic the doc states that the code does not have, or contradicts (subtype: **conflict**, where the doc says X and the code does Y).

**Principles**

1. **Code is the only source of truth.** The agent never changes code. Tests and OpenAPI specs are hints, never proof.
2. **Business logic, not structure.** No import, syntax, inheritance or "library used" findings in the default report.
3. **Evidence or it did not happen.** Every finding cites a doc line and a code `file:line`; both are validated against what was sent to the model.
4. **Deterministic first, LLM last.** Exact checks (paths, symbols, constants) run before any model call.
5. **Humans approve doc edits.** The check stage is read-only; fixes are proposed as diffs.
6. **Focus on drift accuracy.** Feature structure is declared by the user, not guessed.

---

## 2. What the first real run showed

Run: `driftwatcher check --repo CodeBoarding --scope partial --path agents` (1 contradiction, 8 unverifiable, 23 gaps, about 11 minutes).

| Observation | Cause | Fix |
|---|---|---|
| `c56` contradicted: "no pydantic BaseModel or Field" | Judge saw only lines 1-3 of `agent_responses.py`; the pydantic import is on line 5 and every model uses it. **False alarm** | Never allow `contradicted` from a truncated snippet; structural claims removed from the default run |
| 8 `unverifiable`: "Snippets show only imports" | Retrieval sent file heads, not the code a claim refers to | Retrieve by entry point and call graph, not file heads |
| 23 gaps, many duplicated | Same rule repeated (`gap-faed...` x3, `gap-748a...` x3); same rule split across two files; low-value gaps (default strings, step order) | Dedupe, group, significance filter |
| Empty `claim_id` / `feature`; tier shown as `deterministic` for judge results | Data bugs | Fix contracts and labeling |
| Structured output downgraded `json_schema` -> `json_object` | Meta API needs `additionalProperties: false` | `extra="forbid"` on models or post-process the schema |
| 11 minutes, one call 361 s | 23 sequential calls | Parallel calls, timeout, batching, caching |

Real code issues also exist in that file (not doc drift): `UpdateAnalysis.llm_str` reads `self.analysis`, which the class does not define; `ftype is Optional` in `extractor_str` never matches.

---

## 3. Target design

```
MAP    features file -> docs -> entry points -> tests / API links -> .drift.json
CHECK  scope -> entry points -> call graph + tests + spec -> flow summary
       -> doc sections -> compare (stale / missing) -> report
```

---

## 4. MAP stage improvements

| # | Improvement | What to build |
|---|---|---|
| M1 | **Features input file** | `drift.features.json` is the input (human-written, committed). Only `name` and `folder` are required; optional `folders`, `context_files`, `entry_points`, `owners`, `api_spec`, `global`, `ignored_docs`. `map --features FILE` skips FeatureScout (L1) and the confirm prompt. Validate with pydantic `extra="forbid"`: folders exist and are tracked, names are unique, listed docs exist; errors name the key path |
| M2 | **Merge rules** | The input file wins for folder, docs, entry points and owners. `.drift.json` keeps status, resolutions and auto-discovered fields. Show a diff before writing. A feature removed from the file becomes `unonboarded`, not silently deleted. `--refresh` re-runs discovery for `origin: auto` fields only and never touches `origin: user` |
| M3 | **Starter helper** | `map --propose > drift.features.json` runs L1 once and writes the result in the input format for the user to edit. Discovery becomes a one-time helper |
| M4 | **Doc mapping** | If `context_files` is given, use it with no LLM call and no duplicate question. Otherwise run L2 DocMapper (verbatim quote required), ask on duplicates, and offer SkillAuthor (L5) when no doc exists |
| M5 | **Entry-point discovery** | Pluggable `EntryPointSource` interface: public symbols called from outside the folder (AST), route scanner (FastAPI, Flask, Express, Spring), OpenAPI, CLI. Merge and dedupe by handler symbol. Rank by number of outside callers; cap at 10-15 per feature. User-listed ones are `origin: user, confirmed: true`; the rest are confirmed by the owner unless `--yes` |
| M6 | **OpenAPI linking (API-driven features only)** | Resolve operations to handlers deterministically: `operationId` equals function name, then method and path against the route table. An LLM guesses only leftovers, and the owner confirms. List operations with no handler. Skipped for features with no spec or routes |
| M7 | **Test linkage** | For each entry point, find tests that import or call the symbol, or call its route path. Store test file paths |
| M8 | **`review-map`** | Resolve every stored symbol (flag missing or renamed); find new public symbols or routes not in the map; propose changes for approval. A light version runs inside `check` as a warning ("entry point not found", "N new unmapped public functions", "features file changed, run map") |
| M9 | **Doc readiness** | Compute heading index and size per context file at run time. Warn when `AGENTS.md` exceeds about 200 lines or `SKILL.md` about 500 (token estimate = characters / 4; warn-only, configurable) |

### 4.1 Input file format

```json
{
  "version": 1,
  "features": [
    {
      "name": "ai-interpretation",
      "folder": "agents",
      "context_files": ["agents/SKILL.md"],
      "entry_points": ["agents/abstraction_agent.py::AbstractionAgent.run"],
      "owners": ["@team-ai"],
      "api_spec": "openapi.yaml"
    }
  ],
  "global": { "context_files": ["AGENTS.md"] },
  "ignored_docs": ["CONTRIBUTING.md"]
}
```

### 4.2 `.drift.json` entry point shape (generated)

```json
{
  "symbol": "agents/abstraction_agent.py::AbstractionAgent.run",
  "kind": "function|api|cli",
  "route": "POST /v1/analyze",
  "operation_id": "analyzeRepo",
  "tests": ["tests/test_abstraction.py"],
  "discovered_by": ["ast"],
  "origin": "auto|user",
  "confirmed": true
}
```

Use stable symbol identifiers; no line numbers or hashes are stored (those are computed at run time from git).

### 4.3 MAP is done when

- A fully specified features file produces `.drift.json` with **zero LLM calls**.
- Rerunning `map` changes nothing.
- `review-map` catches a renamed entry point.

---

## 5. CHECK stage improvements

### B1. Remove the noise first (half day)

- Drop `import`, `library usage` and `inheritance` claims from the default run (keep them behind `--structural`).
- Keep path, symbol, command and route checks, but report them in a separate **Broken references** section.
- Fix data bugs: empty `claim_id` and `feature`, wrong `tier`, duplicate gaps.
- Make schemas accept `additionalProperties: false` so `json_schema` mode stops downgrading.
- Guard: no `contradicted` verdict from "I did not see X in this snippet."

### B2. Scope and routing

- Map `git diff` and `--scope partial --path` to features and entry points. For an MR, use the call graph to find entry points whose reachable code changed.
- Keep the change matrix (code changed, doc changed, both, neither).
- Run `review-map` in light mode and report its warnings.

### B3. Understand the code (per entry point)

1. **Call graph:** follow calls into helpers inside the feature folder to depth 2-3. Stop at the feature boundary and record external calls as side effects. This fixes thin entry points such as `run` that only call `step_*`.
2. **AST outline:** guard clauses, `raise` and `except` handlers, constants and limits, side effects, return shapes, docstrings.
3. **Tests:** read test names first; select relevant tests deterministically (M7); read only those bodies. Tests are hints, never proof.
4. **OpenAPI hint (API entry points only):** summary, parameter constraints and response codes. Response codes tell the summarizer which negative scenarios to look for. The spec is never evidence on its own.

| AST signal | What it usually means |
|---|---|
| `if cond: return/raise` guards | Negative scenarios (when the feature refuses or bails out) |
| `raise X`, `except X:` | Error policy: retry, fallback, swallow, fail |
| `return` shapes | Output contract |
| Loops, batch sizes, sleeps, retry counts | Limits and thresholds |
| Calls to LLM, DB, filesystem, git, HTTP | Side effects and dependencies |
| Env or config reads | Configurable behavior |

### B4. Flow summary (structured, one call per entry point)

Output schema:

```json
{
  "purpose": "...",
  "steps": ["..."],
  "rules": [
    {"id": "r1", "scenario": "positive|negative|edge",
     "when": "codeboarding_version.json missing", "then": "returns empty list",
     "significance": "high|low", "lines": [43, 45]}
  ],
  "limits": ["..."],
  "side_effects": ["..."]
}
```

Draft prompt (about 365 characters; `test_prompts.py` enforces 500 or fewer):

> Describe the business logic of one entry point. Input: JSON with entry point, AST outline (calls, guards, raises, handlers, constants), code, test names. Output JSON: purpose, steps, rules[{scenario: positive|negative|edge, when, then, lines}], limits, side_effects. State only what the code shows; tests are hints, not proof. Skip imports, types, logging, trivia.

- N8 validates that every cited `lines` range falls inside the code that was sent.
- Cache by hash of reachable code + selected tests + spec operation. Re-summarize only affected entry points.
- Post-filters: drop `significance: low`, merge near-duplicates, group the same rule across files into one finding listing all files.

### B5. Doc side

- Split each context file by headings into sections; split further if a section is too large.
- Route each section to related entry points by symbol mentions, headings and keywords. For small features, send all flows.

### B6. Comparison (the drift)

| Finding | How it is found |
|---|---|
| **Stale** (subtype **conflict**) | Per section, against its routed flow rules. Output `stale[{doc_line, rule_id, reason}]` and `covered[rule_ids]` |
| **Missing** | High-significance rules that no section marked covered. A second pass checks them against the whole doc (or a statement index if too large), because a rule may be documented in a different section |
| **Constants (deterministic)** | Numbers and literals in the doc ("retries 3 times", "batches of 100") are compared with AST constants, with no LLM call |

Draft comparer prompt (about 380 characters):

> Compare one doc section with code flow summaries. Code is the only source of truth; never suggest code changes. Input: JSON with section text (numbered lines) and flow rules (id, when, then, lines). Output JSON: stale[{doc_line, rule_id or null, reason}], covered[rule_ids]. Stale means the doc states logic the code does not have or contradicts. Cite lines from the input only.

### B7. Guardrails

- The check stage is read-only on the repo; it writes only under `.drift/`.
- `DiffApplier` accepts only context-doc paths (`*.md`, `SKILL.md`) and refuses anything else. Add a test that feeds it a diff for a `.py` file and asserts refusal.
- LLM-based findings are marked **advisory** until accuracy is measured.
- Code is the only truth, so `needs_human` is no longer an action. Keep at most an informational note ("code looks inconsistent here") that never leads to a doc or code edit.

### B8. Report redesign

Order:

1. **Conflicts and stale statements** (doc line, rule, code `file:line`)
2. **Missing behavior**, grouped by entry point, top N
3. **Broken references** (paths, commands, symbols, routes)
4. **Unverifiable**, shown as a count only (details under `-v`)

Update the embedded `<!-- driftwatch:report {json} -->` block so `fix --pr` keeps working. Default mode stays warn-only.

### B9. Speed

- Parallel LLM calls (4-8 workers), 60 s per-call timeout, batching of small entry points, per-run call budget.
- Caching as in B4.
- **Target:** under 2 minutes for `--scope partial` on one folder, and near zero on a cached rerun (the first run took about 11 minutes).

### B10. Observability

- Keep step logs and envelope files. Add flow-summary ID and cache hit or miss to log lines.
- Optional **Langfuse** (no LangChain needed): use the `openai` drop-in wrapper in `providers/openai_compatible.py`, a span per agent in `@logged_step`, `correlation_id` as the session ID, and `CallMeta` as metadata. Keep it off by default, optional extra (`pip install driftwatch[tracing]`), fall back silently if keys are missing, and mask or self-host because requests contain source code. Flush before the CLI exits.

### B11. Fix loop

For stale findings, edit or remove the doc statement. For missing behavior, add a statement. Every diff needs developer approval and touches docs only.

### 5.1 CHECK is done when

- Injected behavioral drifts are caught with both citations.
- Unrelated code changes stay green.
- The `agents` folder report shows none of the import or syntax findings.

---

## 6. Contracts and agents to add

**Contracts:** `FeaturesInput`, `EntryPoint`, `FlowSummary`, `FlowRule`, `DocSection`, `DriftFinding` (relation: `stale`, `conflict`, `missing`), updated `Verdict` (adds `rule_id`, `statement_id`, `relation`).

**New deterministic agents:** EntryPointDiscoverer (with sources), CallGraphBuilder, TestLinker, DocSplitter, ConstantChecker.

**LLM agents:** FlowSummarizer (replaces the current RuleMiner) and SectionComparer. Retire or repurpose the old ClaimExtractor and Judge for behavior claims. FeatureScout stays only behind `map --propose`.

**CLI changes:** `map --features`, `--propose`, `--refresh`, `--yes`; new `review-map`; `check` keeps `--scope partial --path`.

---

## 7. Evaluation

1. **Rule recall and precision:** hand-label flows for 3-5 entry points (for example `get_diff_data`, `_parse_response`, `classify_files`). Target: above 70% recall on high-significance rules and fewer than 3 low-value rules per entry point.
2. **Injected behavioral drifts (about 20):** change a retry count, a sleep duration, a batch size, a file-extension filter; remove a guard; change a default or return value. Add **5 negative cases** (refactors and renames with no behavior change).
3. **Run on a pinned features file** so the eval measures drift detection, not feature discovery.
4. **Report:** drifts caught, missed, false alarms, runtime and number of LLM calls.

Validate the flow summarizer on the labeled entry points **before** building the comparer, since the comparer can only be as good as the rules it receives.

---

## 8. Build order (about 8-9 working days; trim from the bottom)

| Step | Work | Est. |
|---|---|---|
| 1 | B1 noise removal; M1-M4 features file and doc mapping | 1.5 days |
| 2 | M5, M7 entry-point discovery and test linkage; B3 call graph and outline | 2 days |
| 3 | B4 flow summary, validated on labeled entry points (riskiest step) | 1.5 days |
| 4 | B5, B6, B8 doc sections, comparison, report | 2 days |
| 5 | B7, M8, B9 guardrails, `review-map`, speed | 1 day |
| 6 | Evaluation (section 7) | 1 day |
| 7 | Last: M6 OpenAPI, B10 Langfuse, B11 fix-loop update | as time allows |

**Cut line:** must have steps 1-4 plus the eval metrics. Can trim OpenAPI, Langfuse, the purpose check, and test-name mining.

---

## 9. Reference: context file size guidelines

There is no hard limit; the constraint is how reliably the agent reads and follows the file. Rules of thumb:

| File type | Target | Why |
|---|---|---|
| Root `AGENTS.md` / `CLAUDE.md` | 100-200 lines (about 1-2.5k tokens) | Loaded on every request, so every line is a recurring cost |
| `SKILL.md` | Under 500 lines (about 5k tokens) | Loaded in full when triggered; long files bury key instructions |
| Feature docs | 200-300 lines, split by topic beyond that | Focused files read and retrieve better |

Line counts include blank lines, headings and code fences, so use **estimated tokens (characters / 4)** as the primary measure and non-blank lines as the human-friendly one. A 200-300 line bulleted doc is roughly 2.5-4.5k tokens. Prefer one topic per file, short bullets, one fact per line, and links to detail files (progressive disclosure).

---

## 10. Glossary

- **Entry point:** a public function, route, or command through which other code or users reach a feature.
- **Flow summary:** the structured description of an entry point's business logic, derived from code (plus tests and spec as hints).
- **Missing:** high-significance code behavior not stated in the doc.
- **Stale:** a doc statement the code does not support (subtype **conflict**: the code does something different).
- **Context file:** a `.md` file meant to inform coding agents (`AGENTS.md`, `SKILL.md`, feature docs).
