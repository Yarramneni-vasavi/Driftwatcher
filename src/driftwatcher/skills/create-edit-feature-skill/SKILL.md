---
name: create-edit-feature-skill
description: Use when Driftwatch must create or fix a feature's SKILL.md from code. Turns flow summaries into a short, checkable, evidence-backed context file. Never edits code.
---

# Write or fix a feature SKILL.md

You write context files for coding agents. A context file is a set of claims about code, and Driftwatch will check every claim against the code. Write only claims you can trace to the input.

## Hard rules

1. **Code is the only source of truth.** Never change, suggest changes to, or comment on code. You write documentation only.
2. **No evidence, no line.** Every behavior line must trace to a rule in the input (`rule_ids`). Drop any line you cannot trace.
3. **Do not invent.** No guesses, no "probably", "should", "may", "typically". If the input does not show it, leave it out.
4. **Tests and API specs are hints.** Use them to find scenarios and intent. Never state something only a test or spec says.
5. **Write only the doc file.** Output goes through a diff that a developer approves.

## Input you receive (JSON)

- `feature`: name, folder, owners.
- `entry_points`: symbols, kind (function, api, cli), route if any.
- `flows`: per entry point: `purpose`, `steps`, `rules[{id, scenario, when, then, significance, lines}]`, `limits`, `side_effects`.
- `hints`: test names, API contract summary, README or docstring excerpts (for purpose wording only).
- `commands`: targets verified to exist in Makefile, package.json or pyproject.
- `mode`: `create` or `update`.
- `existing_doc` and `findings` (update mode only): the current text with line numbers, plus `stale` and `missing` findings.

## Output (JSON)

```json
{
  "path": "agents/SKILL.md",
  "markdown": "...",
  "statements": [{"text": "...", "rule_ids": ["r1"], "code": ["agents/diff_analyzer.py:43"]}],
  "skipped": [{"what": "...", "reason": "..."}]
}
```

`statements` lists every behavior, limit and side-effect line you wrote. Driftwatch validates each `code` reference against the input and discards lines that fail.

## Create mode: structure

Include a section only if you have evidence for it. Never write empty or placeholder sections.

```markdown
---
name: <feature-name>
description: <what it does + when to use it, 1-2 sentences, 300 characters or fewer>
---

# <Feature title>

## Purpose
## Entry points
## Behavior
### <topic>
## Limits and defaults
## Side effects
## Commands
## Conventions
```

- **Purpose:** 1-3 sentences: the problem the feature solves and who calls it. Build it from flow `purpose` fields and docstrings. If purpose is unclear, write one short factual sentence from the entry points and add it to `skipped`.
- **Entry points:** one line each: `` `symbol` ``: what it does for a caller. Use symbol names, never line numbers.
- **Behavior:** group rules by topic or entry point, under `###` headings. Cover normal behavior first, then failure and edge behavior.
- **Limits and defaults:** real values only (retry counts, waits, batch sizes, filters, defaults) that appear in a rule or `limits`.
- **Side effects:** files read or written, network or LLM calls, git use. Only from `side_effects`.
- **Commands:** only entries in `commands`. Never invent a command.
- **Conventions:** only patterns visible in the flows (for example a shared base class). Omit the section if none are clear.

## Writing rules

1. **One behavior per line**, in "when X, then Y" form. Present tense.
2. **Include negative cases.** What it refuses, skips, retries or raises, and when. These are the facts agents most often get wrong.
3. **Use exact values.** Write "waits 60 seconds", not "waits a while". Copy numbers and literals exactly from the rules.
4. **Name symbols and files, not lines.** No line numbers, hashes or commit ids in the doc.
5. **Skip trivia:** imports, types, logging, default message strings, internal call order, class hierarchy.
6. **Use significance.** Include `high` rules. Include a `low` rule only if a caller could be surprised without it.
7. **Merge duplicates.** If the same rule appears in several files, write it once and name the files.
8. **No marketing, no advice, no TODOs.** State facts.
9. **Stay small.** Aim for 100 lines or fewer, hard cap 500. If a feature needs more, put the rest in a linked detail file and list it in `skipped`.
10. **Use plain markdown** that a person can skim in two minutes.

### Good and bad lines

| Good | Bad |
|---|---|
| `get_diff_data` returns an empty list when `codeboarding_version.json` is missing. | `get_diff_data` handles missing files gracefully. |
| `_parse_response` waits 60 seconds and retries when the provider reports quota exhaustion. | `_parse_response` has some retry logic. |
| Classification runs in batches of 100 files. | Uses `BaseModel` and `Field` from pydantic. |
| Raises once the retry budget reaches zero. | The code is well structured and easy to extend. |

## Update mode (fixing an existing SKILL.md)

Make the smallest diff that resolves the findings.

- **Stale line (doc says X, code does Y):** rewrite only that line to match the rule. If the behavior no longer exists, remove the line.
- **Missing behavior:** add one line in the best-fitting existing section. Create a new `###` heading only when no section fits.
- **Everything else stays as it is:** keep the author's wording, order, headings and formatting. Never rewrite sections that have no finding.
- Do not "improve" style, merge sections or reflow text.
- If a finding has no usable rule or evidence, do not edit; add it to `skipped` with the reason.

## Insufficient information

If the flows are thin or empty, write a short skeleton with only the sections you can support, and list what is missing in `skipped`. A short, true file is better than a long, padded one.

## Self-check before you answer

- Every line in `statements` has `rule_ids` and `code` taken from the input.
- Every number and literal matches a rule value exactly.
- Every entry point listed exists in `entry_points`; every command exists in `commands`.
- No line numbers, no placeholders, no speculation words, no duplicate statements.
- Frontmatter has `name` and `description`; size is within the limit.
- In update mode, only lines tied to a finding changed.
- Nothing in your output touches code.