## Setup project

```
poetry env use python
poetry install
```

## Driftwatch

Detect mismatches between context files (`AGENTS.md`, `SKILL.md`) and code.
See [driftwatch_architecture_v2.md](driftwatch_architecture_v2.md) and
[driftwatch_impl_plan_v2.md](driftwatch_impl_plan_v2.md).

Commands:

```
driftwatch scan                          # discover docs, deterministic checks, no setup
driftwatch map [--feature auth]          # propose features, map docs, write .drift.json
driftwatch check --base origin/main      # MR check, same command locally and in CI
driftwatch fix [--pr N]                  # propose doc-only diffs, apply after approval
driftwatch config show                   # resolved config, secrets redacted
driftwatch llm ping [--profile meta_api] # test a provider profile
driftwatch logs --run latest             # view and filter agent logs
```

`make drift` wraps `check --base origin/main`. Global flags on every
command: `--config`, `--profile`, `--model`, `-v`/`-vv`, `--log-format`,
`--quiet`.

## Configuration

Tool settings live in `driftwatch.config.yaml` (see
[driftwatch.config.yaml](driftwatch.config.yaml) for the full example).
Precedence: CLI flags > env (`DRIFT_LLM_PROFILE`, `DRIFT_LOG_LEVEL`) >
config file > built-in defaults. Keys live only in env vars or a
gitignored `.env` (see [.env.example](.env.example)); the file names the
variable, never the value.

Two profiles ship active (Meta models only): `baseten`
(`meta-models/muse-spark-open-1026`) and `meta_api` (Meta Model API).
GPT/Claude are commented-out examples. A new OpenAI-compatible endpoint
is one profile; a new SDK is one file under `src/driftwatch/llm/providers/`.

## Logging

Every run prints `[n/N]` step lines and writes JSONL to
`.drift/logs/<run_id>.jsonl` plus full envelopes to `.drift/runs/`.
`-v` adds decisions and cache hits/misses; `-vv` adds truncated LLM
request/reply excerpts to the file only. API keys and long payloads are
never logged.

CI snippet (full job in [ci/drift-check.yml](ci/drift-check.yml)):

```yaml
- run: driftwatch check --base origin/${{ github.base_ref }} --out drift_report.md --log-format plain
  env: { BASETEN_API_KEY: ${{ secrets.BASETEN_API_KEY }}, MODEL_API_KEY: ${{ secrets.MODEL_API_KEY }} }
```
